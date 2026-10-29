"""Indian Railways options for domestic trips.

IRCTC has no public API, so trains are modelled from route distance using
typical Indian Railways speeds and per-km class fares, then labelled as sample
data with a link to IRCTC for live availability and booking.
"""

from __future__ import annotations

import random
import zlib
from datetime import date, datetime, timedelta

from ..geo import haversine_km
from ..india import IndianCity
from ..models import FlightLeg, FlightOption, FlightSegment

IRCTC_URL = "https://www.irctc.co.in/nget/train-search"

# name, average speed (km/h), classes, max rail distance served (km), timing
TRAIN_TYPES: list[tuple[str, int, tuple[str, ...], int, str]] = [
    ("Vande Bharat Express", 80, ("CC", "EC"), 900, "day"),
    ("Shatabdi Express", 72, ("CC", "EC"), 750, "day"),
    ("Rajdhani Express", 76, ("3A", "2A", "1A"), 2600, "night"),
    ("Duronto Express", 72, ("SL", "3A", "2A", "1A"), 2600, "night"),
    ("Superfast Express", 60, ("SL", "3A", "2A"), 3000, "any"),
    ("Mail Express", 50, ("SL", "3A", "2A"), 3000, "any"),
]

# Approximate one-way fare per km on ordinary express trains and minimum fare, INR
# (incl. reservation & superfast charges). Premium trains add catering and a premium.
FARE_PER_KM = {"SL": 0.5, "3A": 1.3, "2A": 1.85, "1A": 3.1, "CC": 1.1, "EC": 2.2}
MIN_FARE = {"SL": 200, "3A": 550, "2A": 850, "1A": 1500, "CC": 400, "EC": 800}
TYPE_FARE_FACTOR = {
    "Vande Bharat Express": 2.5, "Shatabdi Express": 2.0, "Rajdhani Express": 1.75,
    "Duronto Express": 1.6, "Superfast Express": 1.05, "Mail Express": 0.95,
}

CLASS_LABEL = {
    "SL": "Sleeper", "3A": "AC 3-Tier", "2A": "AC 2-Tier", "1A": "AC First Class",
    "CC": "AC Chair Car", "EC": "Executive Chair Car",
}

MAX_TRAIN_KM = 2700  # beyond this, flying is the only sensible option


def rail_km(a: IndianCity, b: IndianCity) -> float:
    from ..models import GeoPoint

    return haversine_km(GeoPoint(lat=a.lat, lng=a.lng), GeoPoint(lat=b.lat, lng=b.lng)) * 1.25


def _leg(rng: random.Random, number: str, name: str, frm: str, to: str, day: date, km: float, speed: int, timing: str) -> FlightLeg:
    duration = int(km / speed * 60 + 20)
    # Overnight departures only make sense when the journey is long enough to sleep through.
    if (timing == "night" and duration >= 7 * 60) or (timing == "any" and duration > 9 * 60):
        hour = rng.randint(16, 22)
    else:
        hour = rng.choice([5, 6, 7, 8, 14, 15])
    depart = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour, minutes=rng.choice([0, 10, 25, 40, 55]))
    arrive = depart + timedelta(minutes=duration)
    seg = FlightSegment(carrier=name, flight_number=number, origin=frm, destination=to, depart=depart, arrive=arrive, duration_min=duration)
    return FlightLeg(segments=[seg], duration_min=duration, stops=0, max_layover_min=0)


def demo_trains(
    origin: IndianCity, dest: IndianCity, depart: date, ret: date, adults: int, children: int, classes: tuple[str, ...],
) -> list[FlightOption]:
    if not (origin.station and dest.station) or origin.station == dest.station:
        return []
    km = rail_km(origin, dest)
    if km > MAX_TRAIN_KM or km < 60:
        return []
    rng = random.Random(zlib.crc32(f"trains|{origin.station}|{dest.station}|{depart}|{ret}".encode()))
    options: list[FlightOption] = []
    for i, (name, speed, offered, max_km, timing) in enumerate(t for t in TRAIN_TYPES if km <= t[3]):
        cls = next((c for c in classes if c in offered), offered[0])
        number = str(rng.randint(12001, 22999))
        back_number = str(int(number) + 1)
        out = _leg(rng, number, name, origin.station, dest.station, depart, km, speed, timing)
        back = _leg(rng, back_number, name, dest.station, origin.station, ret, km, speed, timing)
        one_way = max(MIN_FARE[cls], FARE_PER_KM[cls] * TYPE_FARE_FACTOR[name] * km) * rng.uniform(0.95, 1.08)
        total = round(one_way * 2 * (adults + children), -1)  # children with a berth pay the full fare
        tags = ["Train", "Overnight" if out.arrive.date() > out.depart.date() else "Day train"]
        options.append(
            FlightOption(
                id=f"demo-tr-{i}", mode="train", outbound=out, inbound=back, price=total, currency="INR",
                cabin=cls, carriers=[name], source="demo", booking_url=IRCTC_URL, tags=tags,
            )
        )
    return options
