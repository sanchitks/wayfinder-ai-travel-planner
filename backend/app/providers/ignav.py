"""Live flight fares and booking links from Ignav (https://ignav.com).

Auth: `X-Api-Key` header. Billing: each successful (HTTP 200) call is one request
(1,000 free, then ~$2 per 1,000). Market "IN" returns fares in INR. Prices are the
total for all passengers. Ignav never issues tickets: booking links open the
airline's or an agency's own site.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from ..config import Settings
from ..geo import city_info
from ..india import indian_city
from ..models import BookingOption, FlightLeg, FlightOption, FlightSegment

log = logging.getLogger(__name__)

CABIN = {"ECONOMY": "economy", "PREMIUM_ECONOMY": "premium_economy", "BUSINESS": "business", "FIRST": "first"}
MAX_OPTIONS = 60  # keep the cheapest N distinct itineraries for ranking

_airport_cache: dict[str, str | None] = {}


class IgnavError(Exception):
    pass


class IgnavClient:
    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.ignav_api_key)

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.s.ignav_api_key}

    @staticmethod
    def _raise_for(r: httpx.Response) -> None:
        if r.status_code == 200:
            return
        try:
            err = r.json().get("error", {})
            msg = f"{err.get('code', r.status_code)}: {err.get('message', '')}"
        except ValueError:
            msg = f"HTTP {r.status_code}"
        if r.status_code == 402:
            msg = "Ignav free requests used up - add a payment method at ignav.com (" + msg + ")"
        raise IgnavError(msg)

    async def airport_code(self, client: httpx.AsyncClient, place: str) -> str | None:
        """IATA code for a city. Indian cities use the built-in table (an Ignav text search for
        "Goa" returns Genova, Italy first); elsewhere ask Ignav's airport search once and cache."""
        raw = place.strip()
        ic = indian_city(raw)  # before the 3-letter check: "Goa" is a city, not airport GOA (Genova)
        if ic:
            return ic.airport
        if len(raw) == 3 and raw.isalpha() and not city_info(raw):
            return raw.upper()
        key = raw.lower()
        if key in _airport_cache:
            return _airport_cache[key]
        r = await client.get(f"{self.s.ignav_base_url}/api/airports", params={"q": raw.split(",")[0], "limit": 5},
                             headers=self._headers())
        self._raise_for(r)
        rows = r.json()
        city = raw.split(",")[0].strip().lower()
        best = next((a for a in rows if a.get("city", "").lower() == city), rows[0] if rows else None)
        code = best["code"] if best else None
        if code is None:  # fall back to the built-in table (may be a metro code)
            info = city_info(raw)
            code = info[2] if info else None
        _airport_cache[key] = code
        return code

    async def round_trip(
        self, origin: str, dest: str, depart: date, ret: date, adults: int, children: int, cabin: str, nonstop: bool,
    ) -> list[FlightOption]:
        async with httpx.AsyncClient(timeout=60) as client:
            o = await self.airport_code(client, origin)
            d = await self.airport_code(client, dest)
            if not o or not d:
                return []
            body = {
                "origin": o, "destination": d, "departure_date": depart.isoformat(), "return_date": ret.isoformat(),
                "adults": adults, "children": children, "cabin_class": CABIN.get(cabin, "economy"),
                "market": self.s.ignav_market, "allow_self_transfer": False,
            }
            if nonstop:
                body["max_stops"] = 0
            r = await client.post(f"{self.s.ignav_base_url}/api/fares/round-trip", json=body, headers=self._headers())
            self._raise_for(r)
            data = r.json()

        options: list[FlightOption] = []
        seen: set[tuple] = set()
        for it in sorted(data.get("itineraries", []), key=lambda x: x["price"]["amount"]):
            try:
                out = _leg(it["outbound"])
                back = _leg(it["inbound"]) if it.get("inbound") else None
            except (KeyError, ValueError, IndexError) as exc:
                log.debug("skipping malformed Ignav itinerary: %s", exc)
                continue
            if not out.segments or it["price"]["amount"] <= 0:
                continue
            signature = tuple(s.flight_number for s in out.segments) + tuple(s.flight_number for s in (back.segments if back else []))
            if signature in seen:
                continue
            seen.add(signature)
            carriers = sorted({s.carrier for leg in (out, back) if leg for s in leg.segments})
            options.append(FlightOption(
                id=f"ignav-{it['ignav_id'][:16]}", provider_ref=it["ignav_id"], outbound=out, inbound=back,
                price=float(it["price"]["amount"]), currency=it["price"].get("currency", "INR"),
                price_verified=it["price"].get("status") == "verified", observed_at=data.get("observed_at"),
                cabin=(it.get("cabin_class") or CABIN.get(cabin, "economy")).upper(), carriers=carriers, source="ignav",
                booking_url=_gflights(o, d, depart, ret),
            ))
            if len(options) >= MAX_OPTIONS:
                break
        return options

    async def booking_links(self, ignav_id: str) -> list[BookingOption]:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self.s.ignav_base_url}/api/fares/booking-links", json={"ignav_id": ignav_id},
                                  headers=self._headers())
            self._raise_for(r)
            data = r.json()
        out: list[BookingOption] = []
        for opt in data.get("booking_options", []):
            legs = opt.get("legs") or []
            leg = "round trip" if len(legs) != 1 else legs[0]
            for link in opt.get("links", []):
                price = link.get("price") or {}
                amount = price.get("amount")
                verified = price.get("status") == "verified"
                if not link.get("url"):
                    continue
                out.append(BookingOption(
                    leg=leg, provider=link["provider_name"], provider_type=link.get("provider_type"),
                    # Ignav returns an unverified 0 placeholder for some manual airline links: don't show it as a fare.
                    price=float(amount) if amount and (verified or amount > 0) else None,
                    currency=price.get("currency", "INR"), price_verified=verified,
                    exact_flight=link.get("specificity") == "exact_flight", url=link["url"],
                ))
        return out


def _leg(leg: dict) -> FlightLeg:
    segs = leg["segments"]
    segments = [
        FlightSegment(
            carrier=s.get("operating_carrier_name") or leg.get("carrier") or s.get("marketing_carrier_code") or "Airline",
            flight_number=f"{s.get('marketing_carrier_code') or ''} {s.get('flight_number') or ''}".strip(),
            origin=s["departure_airport"], destination=s["arrival_airport"],
            depart=datetime.fromisoformat(s["departure_time_local"]),
            arrive=datetime.fromisoformat(s["arrival_time_local"]),
            duration_min=int(s.get("duration_minutes") or 0),
        )
        for s in segs
    ]
    # Layovers from UTC times, so time-zone changes don't distort them.
    layovers = []
    for a, b in zip(segs, segs[1:]):
        if a.get("arrival_time_utc") and b.get("departure_time_utc"):
            gap = datetime.fromisoformat(b["departure_time_utc"].replace("Z", "+00:00")) - \
                datetime.fromisoformat(a["arrival_time_utc"].replace("Z", "+00:00"))
            layovers.append(int(gap.total_seconds() // 60))
    total = leg.get("duration_minutes")
    if not total and segs and segs[0].get("departure_time_utc") and segs[-1].get("arrival_time_utc"):
        total = int((datetime.fromisoformat(segs[-1]["arrival_time_utc"].replace("Z", "+00:00"))
                     - datetime.fromisoformat(segs[0]["departure_time_utc"].replace("Z", "+00:00"))).total_seconds() // 60)
    return FlightLeg(segments=segments, duration_min=int(total or sum(s.duration_min for s in segments)),
                     stops=len(segments) - 1, max_layover_min=max(layovers, default=0))


def _gflights(o: str, d: str, depart: date, ret: date) -> str:
    from urllib.parse import quote_plus

    q = quote_plus(f"Flights from {o} to {d} on {depart.isoformat()} through {ret.isoformat()}")
    return f"https://www.google.com/travel/flights?q={q}&curr=INR&hl=en-IN&gl=IN"


def best_link(options: list[BookingOption]) -> str | None:
    """Prefer an airline's own exact-flight link for the outbound leg, then any airline link."""
    ranked = sorted(options, key=lambda b: (b.leg not in ("outbound", "round trip"), b.provider_type != "airline", not b.exact_flight))
    return ranked[0].url if ranked else None
