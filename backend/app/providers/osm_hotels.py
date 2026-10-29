"""Real hotels from OpenStreetMap via Nominatim, no API key needed.

A few bounded searches ("hotel", "hostel", "guest house", "resort") inside a box
around the destination, sent sequentially at most once per second as the
Nominatim usage policy requires, and cached per city for 6 hours.

What is real: name, property type, address, map location, and any website,
phone, amenities or star rating tagged in OSM. What is *estimated*: the nightly
price and (unless tagged) the star class; both are listed in
`HotelOption.estimated` and labelled in the UI. Guest ratings are never
invented: OSM has none, so `rating` stays None.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import zlib
from datetime import date
from urllib.parse import quote_plus

import httpx

from ..models import GeoPoint, HotelOption
from .demo import local_scale

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim and Wikimedia both ask for an identifying User-Agent with contact details.
USER_AGENT = "Wayfinder-Travel-Planner/1.0 (https://github.com/sanchitks/wayfinder-ai-travel-planner)"
RADIUS_DEG = 0.12  # ~13 km box around the city centre
PHRASES = ("hotel", "hostel", "guest house", "resort")

# OSM (category, type) -> Wayfinder property kind
_KIND = {
    ("tourism", "hotel"): "hotel", ("tourism", "motel"): "hotel", ("tourism", "hostel"): "hostel",
    ("tourism", "guest_house"): "homestay", ("tourism", "chalet"): "homestay",
    ("tourism", "apartment"): "apartment", ("leisure", "resort"): "resort",
}
_GENERIC_NAMES = {"hotel", "hostel", "guest house", "guesthouse", "lodge", "resort", "homestay", "palace", "inn"}

# Brand / naming hints for an *estimated* star class when OSM has no `stars` tag.
_LUXURY = ("taj ", "the taj", "oberoi", "trident", "itc ", "the leela", "leela palace", "jw marriott", "ritz-carlton",
           "four seasons", "st. regis", "st regis", "fairmont", "rambagh", "umaid bhawan", "conrad", "park hyatt",
           "grand hyatt", "raffles", "aman")
_UPSCALE = ("marriott", "hyatt", "radisson", "hilton", "sheraton", "westin", "novotel", "crowne plaza", "le meridien",
            "courtyard", "holiday inn", "pullman", "vivanta", "welcomhotel", "fortune", "sarovar", "ramada", "the park")
_MIDSCALE = ("lemon tree", "ibis", "red fox", "keys ", "regenta", "zone by the park")
_ECONOMY = ("ginger", "fabhotel", "treebo", "oyo", "zostel", "townhouse")
_HERITAGE = ("haveli", "mahal", "bagh", "garh", "niwas", "heritage", "kothi", "vilas")
# Common Indian naming cues for unbranded hotels.
_BUDGET_NAMES = ("lodge", " inn", "rooms", "dormitory", "dharamshala", "yatri", "rest house", "guest house", "stay")
_UPPER_NAMES = ("suites", "grand", "regency", "premier", "boutique", "luxury", "international", "continental", "towers")

# Nightly base price per room (INR at an Indian-metro price level) by star class.
_BASE_PRICE = {1.5: 900, 2: 1500, 2.5: 2200, 3: 3400, 3.5: 4800, 4: 7000, 4.5: 11000, 5: 18000}

CACHE_TTL = 6 * 3600
_cache: dict[str, tuple[float, list[dict]]] = {}
_locks: dict[int, asyncio.Lock] = {}  # one per event loop (a Lock is bound to the loop it first runs on)
_last_call = 0.0


def _rate_lock() -> asyncio.Lock:
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _locks:
        _locks[loop_id] = asyncio.Lock()
    return _locks[loop_id]


def _estimate_class(name: str, kind: str) -> float:
    n = f" {name.lower()} "
    if any(b in n for b in _LUXURY):
        return 5
    if any(b in n for b in _UPSCALE):
        return 4
    if any(b in n for b in _MIDSCALE):
        return 3
    if any(b in n for b in _ECONOMY):
        return 2.5
    if kind in ("heritage", "resort", "hostel", "homestay"):
        return {"heritage": 4, "resort": 4, "hostel": 1.5, "homestay": 2.5}[kind]
    if any(b in n for b in _BUDGET_NAMES):
        return 2
    if any(b in n for b in _UPPER_NAMES):
        return 3.5
    return 3


def _is_heritage(name: str) -> bool:
    n = name.lower()
    if any(h in n for h in _HERITAGE):
        return True
    # "Hotel Shree Palace" is a classic Indian budget-hotel name, not a palace stay.
    return "palace" in n and not n.startswith(("hotel ", "hotal ", "new "))


def _amenities(extra: dict) -> list[str]:
    out = []
    if extra.get("internet_access") in ("wlan", "yes", "wifi", "wired"):
        out.append("free wifi" if extra.get("internet_access:fee") == "no" else "wifi")
    if extra.get("air_conditioning") == "yes":
        out.append("AC")
    if extra.get("parking") or extra.get("parking:fee"):
        out.append("parking")
    if extra.get("wheelchair") == "yes":
        out.append("wheelchair access")
    if extra.get("swimming_pool") == "yes":
        out.append("pool")
    if extra.get("restaurant") == "yes" or extra.get("cuisine"):
        out.append("restaurant")
    if extra.get("diet:vegetarian") == "only":
        out.append("pure veg kitchen")
    return out


def _address(a: dict) -> str:
    street = " ".join(x for x in (a.get("house_number"), a.get("road")) if x)
    area = a.get("suburb") or a.get("neighbourhood") or a.get("quarter")
    town = a.get("city") or a.get("town") or a.get("village") or a.get("county")
    return ", ".join(x for x in (street, area, town) if x)


async def _search(client: httpx.AsyncClient, phrase: str, center: GeoPoint) -> list[dict]:
    """One bounded Nominatim search, spaced >= 1.1 s from any other call in this process."""
    global _last_call
    async with _rate_lock():
        wait = 1.1 - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            r = await client.get(NOMINATIM_URL, params={
                "q": phrase, "format": "jsonv2", "limit": 40, "extratags": 1, "addressdetails": 1, "namedetails": 1,
                "viewbox": f"{center.lng - RADIUS_DEG},{center.lat + RADIUS_DEG},{center.lng + RADIUS_DEG},{center.lat - RADIUS_DEG}",
                "bounded": 1,
            })
        finally:
            _last_call = time.monotonic()
    r.raise_for_status()
    return r.json()


async def _fetch(city: str, center: GeoPoint, timeout: float) -> list[dict]:
    key = f"{city.lower()}|{center.lat:.3f},{center.lng:.3f}"
    city_word = city.split(",")[0].strip().lower()
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    rows: dict[str, dict] = {}
    names: set[str] = set()
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        for phrase in PHRASES:
            try:
                results = await _search(client, phrase, center)
            except httpx.HTTPError as exc:
                log.info("Nominatim '%s' search failed: %s", phrase, exc)
                continue
            for row in results:
                kind = _KIND.get((row.get("category"), row.get("type")))
                names_d = row.get("namedetails") or {}
                name = (names_d.get("name:en") or row.get("name") or "").strip(" ,;-")
                if kind == "hotel" and "resort" in name.lower():
                    kind = "resort"
                if (not kind or len(name) < 4 or name.lower() in _GENERIC_NAMES or name.lower() in names
                        or name.lower() == city_word):  # mis-tagged entries named just "Jaipur", "Fly", ...
                    continue
                names.add(name.lower())
                rows[f"{row['osm_type'][0].upper()}{row['osm_id']}"] = {
                    "key": f"{row['osm_type'][0].upper()}{row['osm_id']}", "name": name, "kind": kind,
                    "lat": float(row["lat"]), "lng": float(row["lon"]),
                    "address": _address(row.get("address") or {}), "extra": row.get("extratags") or {},
                }
    out = list(rows.values())
    if out:
        _cache[key] = (time.time(), out)
    return out


async def search_osm_hotels(
    city: str, center: GeoPoint, checkin: date, checkout: date, adults: int, children: int, timeout: float = 15.0,
) -> list[HotelOption]:
    rows = await _fetch(city, center, timeout)
    nights = (checkout - checkin).days
    travelers = adults + children
    rooms = max(1, math.ceil(adults / 2)) if children == 0 else max(1, math.ceil(travelers / 4))
    scale = local_scale(city)
    city_name = city.split(",")[0].strip().title()

    hotels: list[HotelOption] = []
    for row in rows:
        name, extra, kind = row["name"], row["extra"], row["kind"]
        if kind in ("hotel", "homestay") and _is_heritage(name):
            kind = "heritage"
        estimated = ["price"]
        try:
            stars = min(5.0, max(1.0, float(str(extra.get("stars", "")).rstrip("S").strip())))
        except ValueError:
            stars = _estimate_class(name, kind)
            estimated.append("stars")
        base = _BASE_PRICE[min(_BASE_PRICE, key=lambda s: abs(s - stars))]
        base *= {"heritage": 1.3, "resort": 1.4}.get(kind, 1.0)
        jitter = 0.85 + (zlib.crc32(row["key"].encode()) % 300) / 1000  # stable 0.85-1.15 per property
        nightly = base * scale * jitter * (travelers if kind == "hostel" else rooms)
        amenities = _amenities(extra)
        tags = []
        if kind == "heritage":
            tags.append("heritage")
        if kind == "resort" or "pool" in amenities:
            tags.append("family-friendly")
        if stars >= 4 or any("wifi" in a for a in amenities):
            tags.append("business-ready")
        if "pure veg kitchen" in amenities:
            tags.append("pure-veg")
        q = quote_plus(f"{name} {city_name}")
        hotels.append(HotelOption(
            id=f"osm-{row['key']}", name=name, kind=kind, stars=stars, rating=None,
            price_per_night=round(nightly, -1), total_price=round(nightly * nights, -1), currency="INR",
            location=GeoPoint(lat=row["lat"], lng=row["lng"]), address=row["address"] or city_name,
            amenities=amenities, tags=tags, source="openstreetmap", estimated=estimated,
            website=extra.get("website") or extra.get("contact:website") or "",
            phone=extra.get("phone") or extra.get("contact:phone") or "",
            maps_url=f"https://www.google.com/maps/search/?api=1&query={q}",
            booking_url=(
                f"https://www.booking.com/searchresults.en-gb.html?ss={q}&checkin={checkin}&checkout={checkout}"
                f"&group_adults={adults}&group_children={children}&no_rooms={rooms}&selected_currency=INR"
            ),
        ))
    return hotels
