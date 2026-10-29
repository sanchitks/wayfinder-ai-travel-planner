"""Experiences & dining: Google Places (New) Text Search and Yelp Fusion when keyed,
then real places without a key (Wikipedia sights, OpenStreetMap restaurants), then demo data."""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..config import Settings
from ..models import GeoPoint, Place
from .demo import demo_places, local_scale
from .open_places import search_open_places

log = logging.getLogger(__name__)

# query -> (category, default duration, default cost per person in INR at an Indian-metro level, tags)
_GOOGLE_QUERIES: dict[str, tuple[str, int, float, tuple[str, ...]]] = {
    "top tourist attractions": ("sight", 90, 200, ()),
    "forts palaces and heritage monuments": ("sight", 120, 300, ("heritage",)),
    "famous temples and spiritual places": ("culture", 90, 0, ("spiritual",)),
    "museums": ("culture", 120, 150, ("accessible",)),
    "parks lakes and gardens": ("nature", 90, 0, ("free", "kid-friendly")),
    "family attractions for kids": ("kids", 150, 600, ("kid-friendly", "interactive")),
    "guided tours and experiences": ("activity", 150, 1500, ()),
    "bars lounges and nightlife": ("nightlife", 120, 1200, ("evening",)),
    "ayurvedic spa": ("wellness", 120, 3500, ("exclusive",)),
    "bazaars and shopping markets": ("shopping", 90, 0, ("local",)),
}

_PRICE_LEVELS = {
    "PRICE_LEVEL_FREE": 0, "PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}
_MEAL_COST = {0: 150, 1: 300, 2: 800, 3: 1800, 4: 5000}  # INR per person, Indian-metro level


class GooglePlacesClient:
    URL = "https://places.googleapis.com/v1/places:searchText"
    FIELDS = (
        "places.id,places.displayName,places.formattedAddress,places.location,places.rating,"
        "places.userRatingCount,places.priceLevel,places.types,places.googleMapsUri"
    )

    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.google_places_api_key)

    async def _query(self, client: httpx.AsyncClient, city: str, center: GeoPoint, query: str, meta, idx: float) -> list[Place]:
        category, duration, cost, tags = meta
        r = await client.post(
            self.URL,
            json={
                "textQuery": f"{query} in {city}", "maxResultCount": 10, "languageCode": "en", "regionCode": "IN",
                "locationBias": {"circle": {"center": {"latitude": center.lat, "longitude": center.lng}, "radius": 15000.0}},
            },
            headers={"X-Goog-Api-Key": self.s.google_places_api_key, "X-Goog-FieldMask": self.FIELDS},
        )
        r.raise_for_status()
        out = []
        for p in r.json().get("places", []):
            try:
                level = _PRICE_LEVELS.get(p.get("priceLevel", ""), 0 if category in ("nature", "sight") else 1)
                types = set(p.get("types", []))
                extra = []
                if {"amusement_park", "aquarium", "zoo", "playground"} & types:
                    extra.append("kid-friendly")
                if category == "food":
                    est = _MEAL_COST[level] * idx
                else:
                    est = 0.0 if level == 0 and cost == 0 else cost * idx * max(1, level)
                out.append(
                    Place(
                        id=f"gp-{p['id']}", name=p["displayName"]["text"], category=category,
                        location=GeoPoint(lat=p["location"]["latitude"], lng=p["location"]["longitude"]),
                        rating=float(p.get("rating", 4.2)), review_count=int(p.get("userRatingCount", 0)),
                        price_level=level, est_cost_per_person=round(est, 2), duration_min=duration,
                        address=p.get("formattedAddress", ""), url=p.get("googleMapsUri", ""),
                        source="google", tags=[*tags, *extra] + (["free"] if level == 0 else []),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.debug("skipping malformed Google place: %s", exc)
        return out

    async def search(self, city: str, center: GeoPoint, include_food: bool) -> list[Place]:
        idx = local_scale(city)
        queries = dict(_GOOGLE_QUERIES)
        if include_food:
            queries["best local restaurants"] = ("food", 75, 800, ("vegetarian",))
            queries["pure veg restaurants"] = ("food", 60, 400, ("pure-veg", "vegetarian"))
            queries["street food"] = ("food", 45, 200, ("local", "quick"))
            queries["fine dining restaurants"] = ("food", 120, 3500, ("exclusive",))
            queries["family friendly restaurants"] = ("food", 70, 700, ("kid-friendly", "vegetarian"))
        async with httpx.AsyncClient(timeout=self.s.http_timeout_seconds) as client:
            results = await asyncio.gather(
                *(self._query(client, city, center, q, meta, idx) for q, meta in queries.items()), return_exceptions=True
            )
        places: list[Place] = []
        for res in results:
            if isinstance(res, BaseException):
                log.warning("Google Places query failed: %s", res)
            else:
                places.extend(res)
        return places


class YelpClient:
    URL = "https://api.yelp.com/v3/businesses/search"

    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.yelp_api_key)

    async def search(self, city: str, center: GeoPoint) -> list[Place]:
        idx = local_scale(city)
        headers = {"Authorization": f"Bearer {self.s.yelp_api_key}"}
        out: list[Place] = []
        async with httpx.AsyncClient(timeout=self.s.http_timeout_seconds) as client:
            for price in ("1,2", "3,4"):
                r = await client.get(
                    self.URL,
                    params={
                        "latitude": center.lat, "longitude": center.lng, "term": "restaurants",
                        "price": price, "sort_by": "best_match", "limit": 25, "radius": 15000,
                    },
                    headers=headers,
                )
                r.raise_for_status()
                for b in r.json().get("businesses", []):
                    try:
                        level = len(b.get("price", "$$"))
                        cats = [c.get("title", "") for c in b.get("categories", [])]
                        tags = ["local"] if level <= 1 else []
                        if any("Vegetarian" in c or "Vegan" in c for c in cats):
                            tags += ["vegetarian", "pure-veg"]
                        elif any("Indian" in c for c in cats):
                            tags.append("vegetarian")
                        if any(c in ("Pizza", "Burgers", "Diners", "Ice Cream & Frozen Yogurt") for c in cats):
                            tags.append("kid-friendly")
                        if level >= 4:
                            tags.append("exclusive")
                        out.append(
                            Place(
                                id=f"yelp-{b['id']}", name=b["name"], category="food",
                                location=GeoPoint(lat=b["coordinates"]["latitude"], lng=b["coordinates"]["longitude"]),
                                rating=float(b.get("rating", 4.0)), review_count=int(b.get("review_count", 0)),
                                price_level=level, est_cost_per_person=round(_MEAL_COST[level] * idx, 2),
                                duration_min=60 + 20 * level, address=", ".join(b.get("location", {}).get("display_address", [])),
                                url=b.get("url", ""), image_url=b.get("image_url", ""), source="yelp", tags=tags,
                            )
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        log.debug("skipping malformed Yelp business: %s", exc)
        return out


async def search_places(settings: Settings, *, city: str, center: GeoPoint) -> tuple[list[Place], str]:
    google, yelp = GooglePlacesClient(settings), YelpClient(settings)
    tasks, names = [], []
    if google.enabled:
        # Yelp's coverage in India is thin, so Google always contributes restaurants too.
        tasks.append(google.search(city, center, include_food=True))
        names.append("google")
    if yelp.enabled:
        tasks.append(yelp.search(city, center))
        names.append("yelp")

    places: list[Place] = []
    used: list[str] = []
    for name, res in zip(names, await asyncio.gather(*tasks, return_exceptions=True)):
        if isinstance(res, BaseException):
            log.warning("%s places search failed: %s", name, res)
        elif res:
            places.extend(res)
            used.append(name)

    # Dedupe by name, keep the better-reviewed entry.
    unique: dict[str, Place] = {}
    for p in places:
        key = p.name.strip().lower()
        if key not in unique or p.review_count > unique[key].review_count:
            unique[key] = p
    places = list(unique.values())

    has_food = any(p.category == "food" for p in places)
    has_sights = sum(p.category != "food" for p in places) >= 8
    if has_food and has_sights:
        return places, "+".join(used)
    # No key (or thin results): real places from Wikipedia and OpenStreetMap.
    try:
        free = await search_open_places(city, center)
    except Exception as exc:  # noqa: BLE001 - fall through to demo data
        log.warning("open places search failed: %s", exc)
        free = []
    free_food = [p for p in free if p.category == "food"]
    free_sights = [p for p in free if p.category != "food"]
    if not has_food and len(free_food) >= 6:
        places += free_food
        has_food = True
        used.append("openstreetmap")
    if not has_sights and len(free_sights) >= 6:
        places += free_sights
        has_sights = sum(p.category != "food" for p in places) >= 6
        used.append("wikipedia")
    if has_food and has_sights:
        return places, "+".join(used)
    # Fill whatever is missing from demo data so every itinerary is complete.
    demo = demo_places(city, center)
    if not has_food:
        places += [p for p in demo if p.category == "food"]
    if not has_sights:
        places += [p for p in demo if p.category != "food"]
    return places, "+".join(used + ["demo"]) if used else "demo"
