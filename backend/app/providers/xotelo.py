"""Real hotels with live prices from Xotelo (https://xotelo.com) - free, no API key.

Xotelo exposes TripAdvisor hotel data:
  * /api/list  - hotels in a TripAdvisor location: name, type, TripAdvisor rating and
                 review count, photo, coordinates and a typical price range (USD)
  * /api/rates - live nightly rates for one hotel and date range from Booking.com,
                 Agoda, Trip.com, the hotel's own site, etc. (currency=INR supported)

City search is a paid RapidAPI feature, so destinations use the verified TripAdvisor
location keys below; other destinations fall back to OpenStreetMap hotels.

Usage is kept light: one list call per city (cached 6 h) and live rates only for the
~10 hotels the Accommodation agent shortlists (cached 30 min, max 4 in parallel).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import date, datetime, timezone
from urllib.parse import quote_plus

import httpx

from ..india import USD_TO_INR, indian_city
from ..models import BookingOption, GeoPoint, HotelOption

log = logging.getLogger(__name__)

BASE = "https://data.xotelo.com/api"
HEADERS = {"User-Agent": "Wayfinder-Travel-Planner/1.0 (local development)"}

# TripAdvisor location keys, each verified: the hotels returned sit within ~15 km of the city.
TRIPADVISOR_KEYS: dict[str, str] = {
    # India
    "delhi": "g304551", "mumbai": "g304554", "bengaluru": "g297628", "chennai": "g304556", "kolkata": "g304558",
    "hyderabad": "g297586", "pune": "g297654", "ahmedabad": "g297608", "jaipur": "g304555", "udaipur": "g297672",
    "jodhpur": "g297668", "jaisalmer": "g297667", "agra": "g297683", "varanasi": "g297685", "amritsar": "g303884",
    "goa": "g297604", "kochi": "g297633", "manali": "g297618", "shimla": "g304552", "rishikesh": "g580106",
    "leh": "g297625", "darjeeling": "g304557", "mysuru": "g304553", "lucknow": "g297684", "chandigarh": "g297596",
    "munnar": "g303881", "pondicherry": "g659792", "srinagar": "g297623", "alleppey": "g608471", "ooty": "g297679",
    "andaman": "g297584", "gangtok": "g659796", "dharamshala": "g1092107", "coorg": "g641714",
    # Popular from India
    "dubai": "g295424", "bangkok": "g293916", "singapore": "g294265", "london": "g186338", "paris": "g187147",
    "kathmandu": "g293890", "phuket": "g293920", "kuala lumpur": "g298570", "colombo": "g293962",
}

_KIND = {
    "hotel": "hotel", "small hotel": "hotel", "lodge": "hotel", "specialty hotel": "hotel", "motel": "hotel",
    "resort": "resort", "specialty resort": "resort", "hostel": "hostel", "bed and breakfast": "homestay",
    "guest house": "homestay", "guesthouse": "homestay", "inn": "homestay", "condo": "apartment", "apartment": "apartment",
}
_HERITAGE = ("haveli", "mahal", "palace", "bagh", "garh", "niwas", "heritage", "kothi", "vilas", "fort")
_LUXURY = ("taj ", "oberoi", "trident", "itc ", "leela", "jw marriott", "ritz", "four seasons", "st. regis",
           "fairmont", "luxury collection", "rambagh", "umaid bhawan", "raffles", "aman", "park hyatt", "grand hyatt")

LIST_TTL, RATES_TTL = 6 * 3600, 30 * 60
_typical_max_inr: dict[str, float] = {}  # hotel id -> top of TripAdvisor's typical nightly range, for outlier checks


def _stars_from_inr(nightly_per_room: float, name: str) -> float:
    """Estimated class from the live nightly price per room (INR)."""
    if any(b in f" {name.lower()} " for b in _LUXURY):
        return 5
    for limit, stars in ((1500, 2), (2800, 2.5), (4500, 3), (7500, 3.5), (12000, 4), (20000, 4.5)):
        if nightly_per_room < limit:
            return stars
    return 5
_list_cache: dict[str, tuple[float, list[dict]]] = {}
_rates_cache: dict[str, tuple[float, list[dict]]] = {}
MAX_PARALLEL_RATES = 4


def location_key(city: str) -> str | None:
    from ..india import ALIASES

    k = city.split(",")[0].strip().lower()
    k = ALIASES.get(k, k)
    return TRIPADVISOR_KEYS.get(k)


def _stars_from_price(min_usd: float | None, name: str, kind: str) -> float:
    """Estimated class from the typical nightly price (TripAdvisor list has no star class)."""
    n = f" {name.lower()} "
    if any(b in n for b in _LUXURY):
        return 5
    if kind == "hostel":
        return 1.5
    if not min_usd:
        return 3
    for limit, stars in ((20, 2), (35, 2.5), (55, 3), (90, 3.5), (150, 4), (250, 4.5)):
        if min_usd < limit:
            return stars
    return 5


async def _list(client: httpx.AsyncClient, key: str) -> list[dict]:
    hit = _list_cache.get(key)
    if hit and time.time() - hit[0] < LIST_TTL:
        return hit[1]
    r = await client.get(f"{BASE}/list", params={"location_key": key, "offset": 0, "limit": 100, "sort": "best_value"})
    r.raise_for_status()
    body = r.json()
    if body.get("error"):
        raise RuntimeError(f"Xotelo list error: {body['error']}")
    rows = (body.get("result") or {}).get("list") or []
    _list_cache[key] = (time.time(), rows)
    return rows


async def search_xotelo_hotels(
    city: str, center: GeoPoint, checkin: date, checkout: date, adults: int, children: int,
) -> list[HotelOption]:
    """Real hotels for a city. Prices here are *estimates* from TripAdvisor's typical range;
    call `attach_live_rates` on a shortlist to replace them with live per-seller prices."""
    key = location_key(city)
    if not key:
        return []
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        rows = await _list(client, key)
    nights = (checkout - checkin).days
    travelers = adults + children
    rooms = rooms_needed(adults, children)
    city_name = city.split(",")[0].strip().title()
    hotels: list[HotelOption] = []
    for row in rows:
        try:
            name = row["name"].strip()
            kind = _KIND.get((row.get("accommodation_type") or "hotel").lower(), "hotel")
            if kind == "hotel" and any(h in name.lower() for h in _HERITAGE) and not name.lower().startswith("hotel "):
                kind = "heritage"
            pr = row.get("price_ranges") or {}
            lo, hi = pr.get("minimum"), pr.get("maximum")
            stars = _stars_from_price(lo, name, kind)
            typical_usd = (lo + hi) / 2 if lo and hi else lo or 60
            nightly = typical_usd * USD_TO_INR * (travelers if kind == "hostel" else rooms)
            if hi:
                _typical_max_inr[f"ta-{row['key']}"] = hi * USD_TO_INR
            review = row.get("review_summary") or {}
            geo = row.get("geo") or {}
            labels = row.get("merchandising_labels") or []
            amenities = ["free breakfast"] if "Breakfast included" in labels else []
            if "All inclusive" in labels:
                amenities.append("all inclusive")
            tags = []
            if kind == "heritage":
                tags.append("heritage")
            if kind == "resort":
                tags.append("family-friendly")
            if stars >= 4:
                tags.append("business-ready")
            q = quote_plus(f"{name} {city_name}")
            hotels.append(HotelOption(
                id=f"ta-{row['key']}", name=name, kind=kind, stars=stars,
                rating=float(review["rating"]) if review.get("rating") else None, rating_scale=5,
                review_count=int(review.get("count") or 0), reviews_url=row.get("url", ""),
                price_per_night=round(nightly, -1), total_price=round(nightly * nights, -1), currency="INR",
                location=GeoPoint(lat=float(geo["latitude"]), lng=float(geo["longitude"])),
                address=city_name, amenities=amenities, tags=tags, photo_url=row.get("image") or "",
                source="tripadvisor", estimated=["price", "stars"],
                maps_url=f"https://www.google.com/maps/search/?api=1&query={q}",
                booking_url=booking_com_url(name, city_name, checkin, checkout, adults, children, rooms),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("skipping malformed Xotelo hotel: %s", exc)
    return hotels


def rooms_needed(adults: int, children: int) -> int:
    return max(1, math.ceil(adults / 2)) if children == 0 else max(1, math.ceil((adults + children) / 4))


def booking_com_url(name: str, city: str, checkin: date, checkout: date, adults: int, children: int, rooms: int) -> str:
    q = quote_plus(f"{name} {city}")
    return (f"https://www.booking.com/searchresults.en-gb.html?ss={q}&checkin={checkin}&checkout={checkout}"
            f"&group_adults={adults}&group_children={children}&no_rooms={rooms}&selected_currency=INR")


async def _rates(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, hotel_key: str, checkin: date, checkout: date,
) -> list[dict]:
    ck = f"{hotel_key}|{checkin}|{checkout}"
    hit = _rates_cache.get(ck)
    if hit and time.time() - hit[0] < RATES_TTL:
        return hit[1]
    async with sem:
        r = await client.get(f"{BASE}/rates", params={
            "hotel_key": hotel_key, "chk_in": checkin.isoformat(), "chk_out": checkout.isoformat(), "currency": "INR",
        })
    r.raise_for_status()
    body = r.json()
    rates = [x for x in ((body.get("result") or {}).get("rates") or []) if x.get("rate")]
    _rates_cache[ck] = (time.time(), rates)
    return rates


async def attach_live_rates(
    hotels: list[HotelOption], checkin: date, checkout: date, adults: int, children: int,
) -> int:
    """Replace estimated prices with live ones for these hotels. Returns how many got live prices.
    Hotels with no rates for the dates are tagged 'No live availability' and keep their estimate."""
    nights = (checkout - checkin).days
    rooms = rooms_needed(adults, children)
    now = datetime.now(timezone.utc).isoformat()
    sem = asyncio.Semaphore(MAX_PARALLEL_RATES)  # created per call: bound to the running event loop

    async def one(client: httpx.AsyncClient, h: HotelOption) -> bool:
        if h.source != "tripadvisor" or "price" not in h.estimated:
            return "price" not in h.estimated
        try:
            rates = await _rates(client, sem, h.id.removeprefix("ta-"), checkin, checkout)
        except (httpx.HTTPError, ValueError) as exc:
            log.info("Xotelo rates failed for %s: %s", h.name, exc)
            return False
        # Drop implausible rates (e.g. a suite or a feed error) far above the hotel's own typical range.
        cap = _typical_max_inr.get(h.id)
        if cap:
            rates = [x for x in rates if float(x["rate"]) <= cap * 4]
        if not rates:
            if "No live availability" not in h.tags:
                h.tags.append("No live availability")
            return False
        multiplier = rooms if h.kind != "hostel" else adults + children
        options = sorted(
            (BookingOption(
                leg="stay", provider=x.get("name") or x.get("code", "Seller"),
                provider_type="third_party" if x.get("code") in _OTAS else "hotel",
                price=round(float(x["rate"]) * multiplier, -1), currency="INR", price_verified=True,
                url=_seller_url(x.get("code", ""), h), exact_flight=False,
            ) for x in rates),
            key=lambda b: b.price or 0,
        )
        h.booking_options = options
        h.price_per_night = options[0].price or h.price_per_night
        if h.kind != "hostel":  # live price per room is a better class signal than the typical range
            h.stars = _stars_from_inr(h.price_per_night / multiplier, h.name)
        h.total_price = round(h.price_per_night * nights, -1)
        h.estimated = [e for e in h.estimated if e != "price"]
        h.price_checked_at = now
        return True

    async with httpx.AsyncClient(timeout=40, headers=HEADERS) as client:
        results = await asyncio.gather(*(one(client, h) for h in hotels))
    return sum(results)


_OTAS = {"BookingCom", "Agoda", "CtripTA", "Vio", "Expedia", "HotelsCom2", "Priceline", "Travelocity", "Orbitz",
         "MakeMyTrip", "Goibibo", "ZenHotels", "Trip", "Hotelscombined"}


def _seller_url(code: str, h: HotelOption) -> str:
    """Booking.com gets a dated deep link; other sellers open the hotel's TripAdvisor page,
    which lists the same sellers with live 'View deal' links for chosen dates."""
    if code == "BookingCom":
        return h.booking_url
    return h.reviews_url or h.booking_url
