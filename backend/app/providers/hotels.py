"""Accommodation inventory: Booking.com via RapidAPI, demo data fallback."""

from __future__ import annotations

import logging
import math
from datetime import date
from urllib.parse import quote_plus

import httpx

from ..config import Settings
from ..models import GeoPoint, HotelOption
from .demo import demo_hotels
from .osm_hotels import search_osm_hotels
from .xotelo import location_key, search_xotelo_hotels

log = logging.getLogger(__name__)

_FAMILY_HINTS = ("family", "resort", "kids", "aparthotel", "apartment", "suites", "villa")
_HERITAGE_HINTS = ("haveli", "palace", "heritage", "mahal", "fort", "bagh", "garh", "niwas")
_BUSINESS_HINTS = ("business", "executive", "conference", "convention", "marriott", "hilton", "hyatt", "westin")


class BookingClient:
    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.rapidapi_key)

    def _headers(self) -> dict[str, str]:
        return {"x-rapidapi-key": self.s.rapidapi_key, "x-rapidapi-host": self.s.booking_rapidapi_host}

    async def search(self, city: str, checkin: date, checkout: date, adults: int, children: int) -> list[HotelOption]:
        base = f"https://{self.s.booking_rapidapi_host}/api/v1/hotels"
        rooms = max(1, math.ceil(adults / 2)) if children == 0 else max(1, math.ceil((adults + children) / 4))
        nights = (checkout - checkin).days
        async with httpx.AsyncClient(timeout=self.s.http_timeout_seconds) as client:
            r = await client.get(f"{base}/searchDestination", params={"query": city.split(",")[0].strip()}, headers=self._headers())
            r.raise_for_status()
            dests = r.json().get("data") or []
            if not dests:
                return []
            dest = next((d for d in dests if d.get("search_type") == "city"), dests[0])
            params = {
                "dest_id": dest["dest_id"], "search_type": str(dest.get("search_type", "city")).upper(),
                "arrival_date": checkin.isoformat(), "departure_date": checkout.isoformat(),
                "adults": adults, "room_qty": rooms, "page_number": 1, "units": "metric",
                "languagecode": "en-gb", "currency_code": self.s.currency,
            }
            if children:
                params["children_age"] = ",".join(["8"] * children)
            r = await client.get(f"{base}/searchHotels", params=params, headers=self._headers())
            r.raise_for_status()
            hotels = (r.json().get("data") or {}).get("hotels") or []

        options: list[HotelOption] = []
        for h in hotels:
            try:
                p = h["property"]
                total = float(p["priceBreakdown"]["grossPrice"]["value"])
                name = p["name"]
                lower = name.lower()
                stars = float(p.get("propertyClass") or p.get("accuratePropertyClass") or 3)
                tags = []
                if any(k in lower for k in _FAMILY_HINTS):
                    tags.append("family-friendly")
                if any(k in lower for k in _BUSINESS_HINTS) or stars >= 4:
                    tags.append("business-ready")
                if any(k in lower for k in _HERITAGE_HINTS):
                    tags.append("heritage")
                kind = (
                    "hostel" if "hostel" in lower else "homestay" if "homestay" in lower else "resort" if "resort" in lower
                    else "heritage" if "heritage" in tags else "apartment" if "apartment" in lower else "hotel"
                )
                q = quote_plus(f"{name} {city}")
                options.append(
                    HotelOption(
                        id=f"booking-{h.get('hotel_id', p.get('id'))}", name=name, kind=kind, stars=stars,
                        rating=float(p["reviewScore"]) if p.get("reviewScore") else None,
                        review_count=int(p.get("reviewCount") or 0),
                        price_per_night=round(total / max(1, nights), 2), total_price=round(total, 2),
                        currency=p["priceBreakdown"]["grossPrice"].get("currency", self.s.currency),
                        location=GeoPoint(lat=float(p["latitude"]), lng=float(p["longitude"])),
                        address=p.get("wishlistName", city), amenities=[], tags=tags,
                        photo_url=(p.get("photoUrls") or [""])[0], source="booking.com",
                        maps_url=f"https://www.google.com/maps/search/?api=1&query={q}",
                        booking_url=(
                            f"https://www.booking.com/searchresults.en-gb.html?ss={q}&checkin={checkin}&checkout={checkout}"
                            f"&group_adults={adults}&group_children={children}&no_rooms={rooms}&selected_currency=INR"
                        ),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.debug("skipping malformed Booking.com property: %s", exc)
        return options


async def search_hotels(
    settings: Settings, *, city: str, center: GeoPoint, checkin: date, checkout: date, adults: int, children: int
) -> tuple[list[HotelOption], str]:
    booking = BookingClient(settings)
    if booking.enabled:
        try:
            found = await booking.search(city, checkin, checkout, adults, children)
            if found:
                return found, "booking.com"
        except Exception as exc:
            log.warning("Booking.com search failed: %s", exc)
    # No key needed: real hotels + TripAdvisor ratings via Xotelo; live prices are fetched
    # afterwards for the agent's shortlist only (see attach_live_rates).
    if location_key(city):
        try:
            found = await search_xotelo_hotels(city, center, checkin, checkout, adults, children)
            if len(found) >= 6:
                return found, "tripadvisor"
        except Exception as exc:
            log.warning("Xotelo hotel list failed: %s", exc)
    # No key needed: real properties from OpenStreetMap (prices estimated, clearly labelled).
    try:
        real = await search_osm_hotels(city, center, checkin, checkout, adults, children, settings.http_timeout_seconds)
        if len(real) >= 6:
            return real, "openstreetmap"
        log.info("only %d OpenStreetMap hotels near %s; using sample data", len(real), city)
    except Exception as exc:
        log.warning("OpenStreetMap hotel search failed: %s", exc)
    return demo_hotels(city, center, checkin, checkout, adults, children), "demo"
