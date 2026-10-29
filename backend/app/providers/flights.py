"""Flight inventory: Amadeus for Developers (test env) and Skyscanner via
RapidAPI (Sky Scrapper), with demo data as the last resort."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import date, datetime
from urllib.parse import quote_plus

import httpx

from ..config import Settings
from ..models import FlightLeg, FlightOption, FlightSegment, GeoPoint
from .demo import demo_flights
from .ignav import IgnavClient

log = logging.getLogger(__name__)


def _iso_minutes(duration: str) -> int:
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", duration or "")
    if not m:
        return 0
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    return d * 1440 + h * 60 + mi


def _leg_from_segments(segments: list[FlightSegment]) -> FlightLeg:
    total = int((segments[-1].arrive - segments[0].depart).total_seconds() // 60)
    layovers = [
        int((segments[i + 1].depart - segments[i].arrive).total_seconds() // 60) for i in range(len(segments) - 1)
    ]
    return FlightLeg(segments=segments, duration_min=total, stops=len(segments) - 1, max_layover_min=max(layovers, default=0))


def _gflights_url(origin: str, dest: str, depart: date, ret: date) -> str:
    q = quote_plus(f"Flights from {origin} to {dest} on {depart.isoformat()} through {ret.isoformat()}")
    return f"https://www.google.com/travel/flights?q={q}&curr=INR&hl=en-IN&gl=IN"


class AmadeusClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._token: str | None = None
        self._expires = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.s.amadeus_client_id and self.s.amadeus_client_secret)

    async def _auth(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._expires - 60:
            return self._token
        r = await client.post(
            f"{self.s.amadeus_base_url}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.s.amadeus_client_id,
                "client_secret": self.s.amadeus_client_secret,
            },
        )
        r.raise_for_status()
        body = r.json()
        self._token = body["access_token"]
        self._expires = time.time() + int(body.get("expires_in", 1799))
        return self._token

    async def resolve_code(self, client: httpx.AsyncClient, keyword: str) -> str | None:
        if len(keyword.strip()) == 3 and keyword.strip().isalpha():
            return keyword.strip().upper()
        token = await self._auth(client)
        r = await client.get(
            f"{self.s.amadeus_base_url}/v1/reference-data/locations",
            params={"subType": "CITY,AIRPORT", "keyword": keyword.split(",")[0].strip()[:30], "page[limit]": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        rows = r.json().get("data", [])
        return rows[0]["iataCode"] if rows else None

    async def search(
        self, origin: str, dest: str, depart: date, ret: date, adults: int, children: int, cabin: str, nonstop: bool
    ) -> list[FlightOption]:
        async with httpx.AsyncClient(timeout=self.s.http_timeout_seconds) as client:
            o, d = await asyncio.gather(self.resolve_code(client, origin), self.resolve_code(client, dest))
            if not o or not d:
                return []
            token = await self._auth(client)
            params = {
                "originLocationCode": o, "destinationLocationCode": d,
                "departureDate": depart.isoformat(), "returnDate": ret.isoformat(),
                "adults": adults, "travelClass": cabin, "currencyCode": self.s.currency,
                "max": 30, "nonStop": "true" if nonstop else "false",
            }
            if children:
                params["children"] = children
            r = await client.get(
                f"{self.s.amadeus_base_url}/v2/shopping/flight-offers",
                params=params, headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            body = r.json()

        carriers = body.get("dictionaries", {}).get("carriers", {})
        options: list[FlightOption] = []
        for offer in body.get("data", []):
            try:
                legs = []
                for itin in offer["itineraries"][:2]:
                    segs = [
                        FlightSegment(
                            carrier=carriers.get(s["carrierCode"], s["carrierCode"]).title(),
                            flight_number=f'{s["carrierCode"]}{s["number"]}',
                            origin=s["departure"]["iataCode"], destination=s["arrival"]["iataCode"],
                            depart=datetime.fromisoformat(s["departure"]["at"]),
                            arrive=datetime.fromisoformat(s["arrival"]["at"]),
                            duration_min=_iso_minutes(s.get("duration", "")),
                        )
                        for s in itin["segments"]
                    ]
                    legs.append(_leg_from_segments(segs))
                cabin_found = (
                    offer.get("travelerPricings", [{}])[0].get("fareDetailsBySegment", [{}])[0].get("cabin", cabin)
                )
                options.append(
                    FlightOption(
                        id=f"amadeus-{offer['id']}", outbound=legs[0], inbound=legs[1] if len(legs) > 1 else None,
                        price=float(offer["price"]["grandTotal"]), currency=offer["price"].get("currency", self.s.currency),
                        cabin=cabin_found,
                        carriers=sorted({seg.carrier for leg in legs for seg in leg.segments}),
                        source="amadeus", booking_url=_gflights_url(o, d, depart, ret),
                    )
                )
            except (KeyError, IndexError, ValueError) as exc:
                log.debug("skipping malformed Amadeus offer: %s", exc)
        return options


class SkyscannerClient:
    """Sky Scrapper (Skyscanner data) on RapidAPI. RapidAPI providers change
    shapes often, so parsing is defensive and failures fall through."""

    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.rapidapi_key)

    def _headers(self) -> dict[str, str]:
        return {"x-rapidapi-key": self.s.rapidapi_key, "x-rapidapi-host": self.s.skyscanner_rapidapi_host}

    async def _airport(self, client: httpx.AsyncClient, query: str) -> tuple[str, str] | None:
        r = await client.get(
            f"https://{self.s.skyscanner_rapidapi_host}/api/v1/flights/searchAirport",
            params={"query": query.split(",")[0].strip(), "locale": "en-IN"}, headers=self._headers(),
        )
        r.raise_for_status()
        rows = r.json().get("data") or []
        if not rows:
            return None
        row = rows[0]
        params = row.get("navigation", {}).get("relevantFlightParams", {})
        return params.get("skyId", row.get("skyId")), params.get("entityId", row.get("entityId"))

    async def search(
        self, origin: str, dest: str, depart: date, ret: date, adults: int, children: int, cabin: str
    ) -> list[FlightOption]:
        async with httpx.AsyncClient(timeout=self.s.http_timeout_seconds) as client:
            o, d = await asyncio.gather(self._airport(client, origin), self._airport(client, dest))
            if not o or not d:
                return []
            r = await client.get(
                f"https://{self.s.skyscanner_rapidapi_host}/api/v2/flights/searchFlights",
                params={
                    "originSkyId": o[0], "originEntityId": o[1], "destinationSkyId": d[0], "destinationEntityId": d[1],
                    "date": depart.isoformat(), "returnDate": ret.isoformat(), "adults": adults, "childrens": children,
                    "cabinClass": cabin.lower(), "sortBy": "best", "currency": self.s.currency,
                    "market": "en-IN", "countryCode": "IN",
                },
                headers=self._headers(),
            )
            r.raise_for_status()
            itineraries = (r.json().get("data") or {}).get("itineraries") or []

        options: list[FlightOption] = []
        for it in itineraries[:30]:
            try:
                legs = []
                for leg in it["legs"][:2]:
                    segs = [
                        FlightSegment(
                            carrier=(s.get("marketingCarrier") or {}).get("name", "Airline"),
                            flight_number=str(s.get("flightNumber", "")),
                            origin=s["origin"]["displayCode"], destination=s["destination"]["displayCode"],
                            depart=datetime.fromisoformat(s["departure"]), arrive=datetime.fromisoformat(s["arrival"]),
                            duration_min=int(s.get("durationInMinutes", 0)),
                        )
                        for s in leg["segments"]
                    ]
                    legs.append(_leg_from_segments(segs))
                options.append(
                    FlightOption(
                        id=f"sky-{it['id']}"[:80], outbound=legs[0], inbound=legs[1] if len(legs) > 1 else None,
                        price=float(it["price"]["raw"]), currency=self.s.currency, cabin=cabin,
                        carriers=sorted({seg.carrier for leg in legs for seg in leg.segments}),
                        source="skyscanner", booking_url=_gflights_url(o[0], d[0], depart, ret),
                    )
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                log.debug("skipping malformed Skyscanner itinerary: %s", exc)
        return options


async def search_flights(
    settings: Settings, *, origin: str, dest: str, origin_code: str, dest_code: str,
    origin_pt: GeoPoint | None, dest_pt: GeoPoint | None, depart: date, ret: date,
    adults: int, children: int, cabin: str, nonstop: bool, domestic: bool = False,
) -> tuple[list[FlightOption], str]:
    """Query every configured live source in parallel; fall back to demo data."""
    amadeus, sky, ignav = AmadeusClient(settings), SkyscannerClient(settings), IgnavClient(settings)
    tasks, names = [], []
    if ignav.enabled:
        tasks.append(ignav.round_trip(origin, dest, depart, ret, adults, children, cabin, nonstop))
        names.append("ignav")
    if amadeus.enabled:
        tasks.append(amadeus.search(origin, dest, depart, ret, adults, children, cabin, nonstop))
        names.append("amadeus")
    if sky.enabled:
        tasks.append(sky.search(origin, dest, depart, ret, adults, children, cabin))
        names.append("skyscanner")

    results: list[FlightOption] = []
    used: list[str] = []
    for name, res in zip(names, await asyncio.gather(*tasks, return_exceptions=True)):
        if isinstance(res, BaseException):
            log.warning("%s flight search failed: %s", name, res)
        elif res:
            results.extend(res)
            used.append(name)
    if results:
        return results, "+".join(used)
    return demo_flights(origin_code, dest_code, origin_pt, dest_pt, depart, ret, adults, children, cabin, domestic), "demo"
