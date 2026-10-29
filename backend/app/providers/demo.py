"""Deterministic sample inventory used when a live API key is missing or a live
call fails. Seeded by the trip parameters so the same search is stable, and
shaped exactly like live results so the agents can't tell the difference.

Localized for India: all prices are in INR. Indian destinations get Indian
airlines, hotel types (homestays, heritage havelis) and places (forts, ghats,
thali houses); destinations abroad get international inventory priced in INR.
"""

from __future__ import annotations

import math
import random
import zlib
from datetime import date, datetime, timedelta
from urllib.parse import quote_plus

from ..geo import haversine_km, offset
from ..india import (
    DOMESTIC_AIRLINES, DOMESTIC_HUBS, INTERNATIONAL_AIRLINES, INTERNATIONAL_HUBS, USD_TO_INR, indian_city,
)
from ..models import FlightLeg, FlightOption, FlightSegment, GeoPoint, HotelOption, Place


def _rng(*parts: object) -> random.Random:
    return random.Random(zlib.crc32("|".join(str(p) for p in parts).encode()))


# Relative price level of destinations abroad (1.0 = typical western European city).
FOREIGN_COST = {
    "zurich": 1.55, "london": 1.4, "new york": 1.45, "paris": 1.3, "tokyo": 1.2, "singapore": 1.25,
    "dubai": 1.2, "san francisco": 1.4, "copenhagen": 1.35, "reykjavik": 1.45, "sydney": 1.2,
    "amsterdam": 1.3, "boston": 1.3, "los angeles": 1.25, "seattle": 1.2, "hong kong": 1.2,
    "bangkok": 0.5, "bali": 0.5, "phuket": 0.55, "kathmandu": 0.4, "colombo": 0.5, "maldives": 1.6,
    "mexico city": 0.6, "istanbul": 0.65, "lisbon": 0.85, "prague": 0.75, "athens": 0.8,
    "kuala lumpur": 0.55, "hanoi": 0.45, "baku": 0.6, "almaty": 0.6, "tbilisi": 0.55,
}


def price_factor(city: str) -> float:
    """Multiplier applied to the base price tables below.

    Indian cities: relative to an Indian metro (tables are in INR).
    Abroad: USD tables converted to INR and scaled by the local price level.
    """
    ic = indian_city(city)
    if ic:
        return ic.cost
    return USD_TO_INR * FOREIGN_COST.get(city.split(",")[0].strip().lower(), 1.0)


def local_scale(city: str) -> float:
    """Price level relative to an Indian metro, for INR estimates from live APIs."""
    ic = indian_city(city)
    if ic:
        return ic.cost
    return 2.8 * FOREIGN_COST.get(city.split(",")[0].strip().lower(), 1.0)


def _gflights(origin: str, dest: str, depart: date, ret: date) -> str:
    q = quote_plus(f"Flights from {origin} to {dest} on {depart.isoformat()} through {ret.isoformat()}")
    return f"https://www.google.com/travel/flights?q={q}&curr=INR&hl=en-IN&gl=IN"


# --- Flights ------------------------------------------------------------------

CABIN_MULT = {"ECONOMY": 1.0, "PREMIUM_ECONOMY": 1.6, "BUSINESS": 3.2, "FIRST": 5.5}


def _leg(rng: random.Random, origin: str, dest: str, day: date, base_min: int, stops: int, carrier: tuple, hubs: list[str]) -> FlightLeg:
    name, code, _ = carrier
    hubs = [h for h in hubs if h not in (origin, dest)]
    route = [origin, *rng.sample(hubs, stops), dest]
    depart = datetime.combine(day, datetime.min.time()) + timedelta(hours=rng.randint(5, 22), minutes=rng.choice([0, 5, 15, 25, 35, 45, 55]))
    flying = int(base_min * (1 + 0.1 * stops))
    shares = [rng.uniform(0.6, 1.4) for _ in range(stops + 1)]
    segments, max_layover, cur = [], 0, depart
    for i in range(stops + 1):
        dur = max(40, int(flying * shares[i] / sum(shares)))
        arrive = cur + timedelta(minutes=dur)
        segments.append(
            FlightSegment(
                carrier=name, flight_number=f"{code} {rng.randint(100, 2899)}",
                origin=route[i], destination=route[i + 1], depart=cur, arrive=arrive, duration_min=dur,
            )
        )
        if i < stops:
            layover = rng.choice([55, 70, 85, 100, 125, 150, 185, 240, 320, 430])
            max_layover = max(max_layover, layover)
            cur = arrive + timedelta(minutes=layover)
    total = int((segments[-1].arrive - segments[0].depart).total_seconds() // 60)
    return FlightLeg(segments=segments, duration_min=total, stops=stops, max_layover_min=max_layover)


def demo_flights(
    origin: str, dest: str, origin_pt: GeoPoint | None, dest_pt: GeoPoint | None,
    depart: date, ret: date, adults: int, children: int, cabin: str, domestic: bool = False, count: int = 16,
) -> list[FlightOption]:
    rng = _rng("flights", origin, dest, depart, ret, cabin)
    km = haversine_km(origin_pt, dest_pt) if origin_pt and dest_pt else 2500.0
    base_min = int(km / 760 * 60 + 35)
    airlines, hubs = (DOMESTIC_AIRLINES, DOMESTIC_HUBS) if domestic else (INTERNATIONAL_AIRLINES, INTERNATIONAL_HUBS)
    if domestic and cabin in ("BUSINESS", "FIRST"):  # only full-service carriers sell business class in India
        airlines = [a for a in airlines if a[0] in ("Air India", "IndiGo")]
    options: list[FlightOption] = []
    for i in range(count):
        carrier = rng.choice(airlines)
        if km < 900:
            stops = rng.choices([0, 1], [0.85, 0.15])[0]
        elif km < 3000:
            stops = rng.choices([0, 1, 2], [0.55, 0.4, 0.05])[0]
        else:
            stops = rng.choices([0, 1, 2], [0.3, 0.55, 0.15])[0]
        out = _leg(rng, origin, dest, depart, base_min, stops, carrier, hubs)
        back_stops = stops if rng.random() < 0.75 else min(2, max(0, stops + rng.choice([-1, 1])))
        inbound = _leg(rng, dest, origin, ret, base_min, back_stops, carrier, hubs)
        if domestic:  # round trip per adult, INR
            per_adult = (4.2 * km + 3800) * carrier[2]
        else:
            per_adult = (km * 0.085 + 70) * USD_TO_INR * carrier[2]
        per_adult *= {0: 1.18, 1: 1.0, 2: 0.88}[stops] * CABIN_MULT.get(cabin, 1.0) * rng.uniform(0.85, 1.2)
        total = round(per_adult * adults + per_adult * 0.8 * children, -1)
        options.append(
            FlightOption(
                id=f"demo-fl-{i}", outbound=out, inbound=inbound, price=total, currency="INR", cabin=cabin,
                carriers=[carrier[0]], source="demo", booking_url=_gflights(origin, dest, depart, ret),
            )
        )
    return options


# --- Hotels -------------------------------------------------------------------

# kind, stars range, base nightly price per room, priced per person?
_INDIA_TIERS = [  # INR at an Indian-metro price level
    ("hostel", (1.5, 2.5), (550, 1100), True),
    ("homestay", (2, 3), (1500, 3200), False),
    ("hotel", (3, 3), (2500, 4500), False),
    ("apartment", (3, 4), (3500, 7000), False),
    ("hotel", (4, 4), (5500, 9500), False),
    ("heritage", (4, 4.5), (6500, 15000), False),
    ("resort", (4.5, 5), (11000, 26000), False),
    ("hotel", (5, 5), (14000, 38000), False),
]
_FOREIGN_TIERS = [  # USD at a western-European price level
    ("hostel", (1.5, 2.5), (22, 45), True),
    ("guesthouse", (2, 3), (55, 95), False),
    ("hotel", (3, 3), (95, 160), False),
    ("apartment", (3, 4), (120, 220), False),
    ("hotel", (4, 4), (170, 290), False),
    ("resort", (4.5, 5), (300, 560), False),
    ("hotel", (5, 5), (380, 820), False),
]
_NAMES_IN = {
    "hostel": ["Nomad Nest", "Chai Bunks", "Wanderers' Den", "Banyan Backpackers", "Monsoon Bunkhouse"],
    "homestay": ["Tulsi", "Neem Tree", "Bougainvillea", "Courtyard", "Mango Grove"],
    "hotel": ["Kanha Residency", "The Lotus", "Sapphire Inn", "Chandan", "Marigold Regency", "Amaltas", "Peacock Grand", "Saffron Suites"],
    "apartment": ["Skyline", "Urban Nest", "Greenview"],
    "heritage": ["Chandni", "Kesariya", "Jharokha", "Rang Mahal"],
    "resort": ["Coconut Grove", "Palm Shore", "Misty Pines", "Lagoon Retreat"],
}
_LUX_IN = ["The Grand Maharani", "Kesar Palace", "The Imperial Heritage", "The Peshwa Grand", "Suryavanshi Palace"]
_SUFFIX_IN = {"hostel": "Hostel", "homestay": "Homestay", "hotel": "Hotel", "apartment": "Serviced Apartments",
              "heritage": "Haveli", "resort": "Resort & Spa"}
_NAMES_FX = {
    "hostel": ["Nomad", "Wanderlust", "Backpackers' Loft", "Social Hub", "Sunny Bunk", "Mosaic"],
    "guesthouse": ["Linden", "Old Mill", "Garden Gate", "Casa Azul", "Willow"],
    "hotel": ["Harborview", "Riverside", "Parkside", "Meridian", "Atrium", "Aurora", "Beacon", "Gallery"],
    "apartment": ["Urban Nest", "Loft Collective", "Courtyard", "Skyline"],
    "resort": ["Palm Crest", "Azure Bay", "Serenity", "Grand Lagoon"],
}
_LUX_FX = ["The Regent", "Palais Royale", "The Sovereign", "Maison Lumière", "The Imperial", "Belvedere Palace"]
_SUFFIX_FX = {"hostel": "Hostel", "guesthouse": "Guesthouse", "hotel": "Hotel", "apartment": "Residences", "resort": "Resort & Spa"}


def _amenities(rng: random.Random, kind: str, stars: float, india: bool) -> list[str]:
    a = {"free wifi", "AC"} if india else {"free wifi"}
    if kind == "hostel":
        a |= set(rng.sample(["lockers", "kitchen", "common room", "free breakfast", "cafe", "laundry"], 4))
    elif kind == "homestay":
        a |= set(rng.sample(["home-cooked meals", "free breakfast", "garden", "parking", "local host"], 3))
    else:
        a |= set(rng.sample(["free breakfast", "gym", "laundry", "24h front desk", "parking", "power backup"], 3))
    if kind == "apartment":
        a |= {"kitchenette", "family rooms"}
    if kind == "heritage":
        a |= {"heritage architecture", "courtyard dining", "cultural evenings", "pool"}
    if stars >= 3.5:
        a |= set(rng.sample(["business center", "fast wifi", "workspace", "meeting rooms", "room service", "pool"], 3))
    if stars >= 4.5:
        spa = "ayurvedic spa" if india else "spa"
        a |= {spa, "spa", "concierge", "fine dining"} | set(rng.sample(["airport transfer", "butler", "pool", "kids club", "rooftop restaurant"], 2))
    if kind == "resort":
        a |= {"pool", "kids club", "family rooms"}
    if india and rng.random() < 0.3 and kind not in ("hostel",):
        a.add("pure veg kitchen")
    return sorted(a)


def demo_hotels(city: str, center: GeoPoint, checkin: date, checkout: date, adults: int, children: int, count: int = 20) -> list[HotelOption]:
    rng = _rng("hotels", city, checkin, checkout)
    india = indian_city(city) is not None
    factor = price_factor(city)
    tiers = _INDIA_TIERS if india else _FOREIGN_TIERS
    names, suffix, lux = (_NAMES_IN, _SUFFIX_IN, _LUX_IN) if india else (_NAMES_FX, _SUFFIX_FX, _LUX_FX)
    nights = (checkout - checkin).days
    travelers = adults + children
    rooms = max(1, math.ceil(adults / 2)) if children == 0 else max(1, math.ceil(travelers / 4))
    city_name = city.split(",")[0].strip().title()
    used: set[str] = set()
    hotels: list[HotelOption] = []
    for i in range(count):
        kind, (s_lo, s_hi), (p_lo, p_hi), per_person = tiers[i % len(tiers)]
        stars = round(rng.uniform(s_lo, s_hi) * 2) / 2
        if stars >= 5 and kind == "hotel":
            candidates = [f"{n} {city_name}" for n in lux]
        else:
            candidates = [f"{n} {suffix[kind]}" for n in names[kind]]
        fresh = [n for n in candidates if n not in used]
        name = rng.choice(fresh) if fresh else f"{rng.choice(candidates)} {city_name} {i}"
        used.add(name)
        nightly = rng.uniform(p_lo, p_hi) * factor
        nightly = nightly * travelers if per_person else nightly * rooms
        radius = rng.uniform(0.2, 2.0) if stars >= 4.5 else rng.uniform(0.3, 5.0)
        angle = rng.uniform(0, 2 * math.pi)
        loc = offset(center, radius * math.sin(angle), radius * math.cos(angle))
        amenities = _amenities(rng, kind, stars, india)
        tags = []
        if kind != "hostel" and ({"pool", "family rooms", "kids club"} & set(amenities)):
            tags.append("family-friendly")
        if {"business center", "workspace", "fast wifi"} & set(amenities):
            tags.append("business-ready")
        if kind == "heritage":
            tags.append("heritage")
        if "pure veg kitchen" in amenities:
            tags.append("pure-veg")
        rating = round(min(9.8, max(6.4, rng.gauss(6.9 + stars * 0.45, 0.45))), 1)
        q = quote_plus(f"{name} {city_name}")
        street = rng.choice(["MG Road", "Station Road", "Mall Road", "Fort Road", "Lake Road", "Civil Lines", "Old City"]) if india else \
            f"{rng.choice(['Market', 'Harbor', 'Park', 'Station', 'Castle', 'River', 'Garden'])} {rng.choice(['Street', 'Lane', 'Avenue', 'Road'])}"
        hotels.append(
            HotelOption(
                id=f"demo-ht-{i}", name=name, kind=kind, stars=stars, rating=rating,
                review_count=rng.randint(80, 4200), price_per_night=round(nightly, -1),
                total_price=round(nightly * nights, -1), currency="INR", location=loc,
                address=f"{rng.randint(2, 180)}, {street}, {city_name}",
                amenities=amenities, source="demo", tags=tags,
                booking_url=(
                    f"https://www.booking.com/searchresults.en-gb.html?ss={q}&checkin={checkin}&checkout={checkout}"
                    f"&group_adults={adults}&group_children={children}&no_rooms={rooms}&selected_currency=INR"
                ),
            )
        )
    return hotels


# --- Places -------------------------------------------------------------------

# name, category, price_level, duration_min, cost_per_person (INR, Indian-metro level), tags
_INDIA_PLACES: list[tuple[str, str, int, int, float, tuple[str, ...]]] = [
    ("{city} Fort", "sight", 1, 150, 200, ("heritage", "kid-friendly")),
    ("Old City Heritage Walk", "sight", 0, 120, 0, ("free", "walking", "heritage", "local")),
    ("City Palace & Museum", "sight", 2, 150, 500, ("heritage", "accessible", "kid-friendly")),
    ("Ancient Stepwell", "sight", 0, 60, 0, ("free", "heritage", "quick")),
    ("Sunset Point", "sight", 0, 60, 0, ("free", "quick", "evening")),
    ("Colonial Quarter Walk", "sight", 0, 90, 0, ("free", "walking", "heritage")),
    ("Ancient Temple Complex", "culture", 0, 90, 0, ("free", "spiritual", "heritage", "accessible")),
    ("Evening Aarti Ceremony", "culture", 0, 75, 0, ("free", "spiritual", "evening", "local")),
    ("Gurdwara Visit & Langar", "culture", 0, 75, 0, ("free", "spiritual", "local", "kid-friendly")),
    ("State Museum", "culture", 1, 120, 100, ("accessible", "kid-friendly", "interactive")),
    ("Crafts Village & Artisan Workshop", "culture", 2, 120, 800, ("interactive", "local", "kid-friendly")),
    ("Folk Music & Dance Evening", "culture", 2, 90, 600, ("evening", "local", "kid-friendly")),
    ("Private Palace Dinner & Heritage Tour", "culture", 4, 180, 12000, ("private", "exclusive", "heritage", "evening")),
    ("Botanical Garden", "nature", 1, 90, 50, ("kid-friendly", "accessible")),
    ("Lake Promenade", "nature", 0, 75, 0, ("free", "walking", "kid-friendly", "accessible", "evening")),
    ("Sunrise Hilltop Viewpoint", "nature", 0, 120, 0, ("free", "walking")),
    ("Wildlife Sanctuary Safari", "activity", 3, 210, 2500, ("wildlife", "kid-friendly")),
    ("Science City", "kids", 2, 180, 300, ("kid-friendly", "interactive", "accessible")),
    ("Amusement & Water Park", "kids", 2, 240, 1200, ("kid-friendly",)),
    ("Zoo & Nature Park", "kids", 1, 180, 100, ("kid-friendly", "accessible", "wildlife")),
    ("Old Bazaar Food Walk", "activity", 2, 150, 1200, ("local", "walking")),
    ("Cooking Class with a Home Chef", "activity", 3, 180, 2500, ("interactive", "local")),
    ("Dawn Cycle Tour", "activity", 1, 150, 900, ("local",)),
    ("Private Chauffeured City Tour", "activity", 4, 300, 9000, ("private", "exclusive")),
    ("Hot-Air Balloon Ride", "activity", 4, 180, 14000, ("exclusive", "adventure")),
    ("Rooftop Lounge", "nightlife", 3, 120, 1800, ("rooftop", "evening")),
    ("Live Music Cafe", "nightlife", 2, 120, 900, ("evening", "local")),
    ("Night Food Market", "nightlife", 1, 90, 300, ("evening", "local", "kid-friendly")),
    ("Craft Brewery", "nightlife", 2, 120, 1200, ("evening",)),
    ("Ayurvedic Spa & Massage", "wellness", 3, 120, 4000, ("exclusive",)),
    ("Sunrise Yoga Session", "wellness", 0, 60, 0, ("free", "spiritual")),
    ("Old Bazaar & Spice Market", "shopping", 1, 90, 0, ("local", "free")),
    ("Handloom & Handicrafts Emporium", "shopping", 2, 75, 0, ("local",)),
    ("Designer Boutiques", "shopping", 3, 90, 0, ("exclusive",)),
    # food
    ("Chaat Street", "food", 1, 45, 180, ("local", "vegetarian", "quick")),
    ("Thali House", "food", 1, 60, 350, ("pure-veg", "jain", "vegetarian", "local", "kid-friendly")),
    ("South Indian Tiffin Centre", "food", 1, 45, 200, ("pure-veg", "jain", "vegetarian", "quick", "kid-friendly", "daytime")),
    ("Jain Bhojanalaya", "food", 1, 60, 300, ("jain", "pure-veg", "vegetarian")),
    ("Punjabi Dhaba", "food", 1, 60, 450, ("vegetarian", "non-veg", "local", "kid-friendly")),
    ("Biryani House", "food", 2, 60, 550, ("local", "non-veg")),
    ("Kebab Corner", "food", 2, 60, 600, ("local", "evening", "non-veg")),
    ("Family Multi-Cuisine Restaurant", "food", 2, 75, 700, ("vegetarian", "kid-friendly")),
    ("Cafe & Bakery", "food", 1, 45, 400, ("vegetarian", "quick", "kid-friendly", "daytime")),
    ("Regional Thali Experience", "food", 2, 75, 900, ("pure-veg", "jain", "vegetarian", "local")),
    ("Pure Veg Fine Dining", "food", 3, 90, 2000, ("pure-veg", "jain", "vegetarian", "exclusive")),
    ("Coastal Seafood Kitchen", "food", 2, 75, 900, ("local", "non-veg")),
    ("Mughlai Fine Dining", "food", 3, 90, 2200, ("vegetarian", "non-veg")),
    ("Business Lunch Club", "food", 3, 60, 1500, ("business", "quick", "vegetarian")),
    ("Rooftop Restaurant with City Views", "food", 3, 90, 2000, ("rooftop", "vegetarian")),
    ("Modern Indian Tasting Menu", "food", 4, 150, 6000, ("exclusive", "vegetarian")),
    ("Palace Courtyard Dining", "food", 4, 120, 5000, ("exclusive", "heritage", "vegetarian")),
]

_REGION_EXTRAS: dict[str, list[tuple[str, str, int, int, float, tuple[str, ...]]]] = {
    "beach": [
        ("Beach Sunset & Shacks", "nature", 0, 120, 0, ("free", "beach", "evening", "kid-friendly")),
        ("Water Sports at the Beach", "activity", 2, 120, 1500, ("beach", "adventure")),
        ("Backwater / Mangrove Boat Ride", "activity", 2, 120, 800, ("kid-friendly", "nature")),
        ("Portuguese-Era Church Walk", "sight", 0, 90, 0, ("free", "heritage", "walking")),
    ],
    "hills": [
        ("Mall Road Stroll", "shopping", 0, 90, 0, ("free", "walking", "evening", "kid-friendly")),
        ("Tea / Spice Plantation Walk", "nature", 1, 120, 300, ("mountain", "kid-friendly")),
        ("Paragliding", "activity", 3, 90, 3000, ("adventure", "mountain")),
        ("Waterfall Trail", "nature", 0, 150, 0, ("free", "mountain", "walking")),
    ],
    "himalaya": [
        ("Monastery Visit", "culture", 0, 90, 50, ("spiritual", "mountain", "heritage")),
        ("High-Altitude Lake Day Trip", "nature", 2, 360, 2500, ("mountain",)),
        ("River Rafting", "activity", 2, 150, 1800, ("adventure",)),
        ("Valley Viewpoint Hike", "nature", 0, 180, 0, ("free", "mountain", "walking")),
    ],
    "desert": [
        ("Desert Camel Safari & Sunset", "activity", 2, 180, 1500, ("kid-friendly", "evening")),
        ("Hilltop Fort Light & Sound Show", "culture", 1, 60, 300, ("evening", "heritage", "kid-friendly")),
        ("Block-Printing Workshop", "culture", 2, 120, 1200, ("interactive", "local")),
    ],
    "heritage": [
        ("Riverside Ghats Walk", "sight", 0, 90, 0, ("free", "spiritual", "walking")),
        ("Sunrise Boat Ride", "activity", 1, 75, 500, ("spiritual", "kid-friendly")),
        ("UNESCO Monument Complex", "sight", 2, 150, 600, ("heritage", "accessible")),
    ],
    "metro": [
        ("Modern Art Gallery", "culture", 1, 90, 150, ("accessible",)),
        ("Shopping Mall & Food Court", "shopping", 1, 120, 0, ("kid-friendly", "accessible")),
        ("Stand-up Comedy Night", "nightlife", 2, 120, 800, ("evening",)),
    ],
}

# Abroad: name, category, price_level, duration_min, cost_per_person (USD, W. Europe level), tags
_FOREIGN_PLACES: list[tuple[str, str, int, int, float, tuple[str, ...]]] = [
    ("{city} Old Town Walking Tour", "sight", 0, 120, 0, ("free", "walking", "kid-friendly", "accessible", "local")),
    ("Cathedral Square", "sight", 0, 60, 0, ("free", "accessible", "kid-friendly")),
    ("Royal Palace & Gardens", "sight", 2, 150, 22, ("accessible", "kid-friendly", "heritage")),
    ("Panorama Lookout", "sight", 0, 60, 0, ("free", "quick", "evening")),
    ("Riverside Fortress", "sight", 1, 120, 14, ("kid-friendly", "heritage")),
    ("National Art Museum", "culture", 2, 150, 18, ("accessible",)),
    ("Museum of {city} History", "culture", 1, 120, 12, ("kid-friendly", "accessible", "interactive")),
    ("Street Art Quarter Walk", "culture", 0, 90, 0, ("free", "walking", "local")),
    ("Indian Temple & Community Centre", "culture", 0, 60, 0, ("free", "spiritual")),
    ("Private After-Hours Gallery Viewing", "culture", 4, 120, 220, ("private", "exclusive", "evening")),
    ("Botanical Garden", "nature", 1, 120, 6, ("kid-friendly", "accessible")),
    ("Central Park Loop", "nature", 0, 90, 0, ("free", "kid-friendly", "accessible", "walking")),
    ("Science Discovery Center", "kids", 2, 180, 20, ("kid-friendly", "interactive", "accessible")),
    ("City Aquarium", "kids", 2, 150, 24, ("kid-friendly", "accessible", "interactive")),
    ("Theme Park", "kids", 3, 300, 70, ("kid-friendly",)),
    ("Food Market Tasting Tour", "activity", 2, 150, 55, ("local", "walking")),
    ("Harbor Sightseeing Cruise", "activity", 2, 90, 28, ("kid-friendly", "accessible", "evening")),
    ("Private Chauffeured City Tour", "activity", 4, 240, 320, ("private", "exclusive")),
    ("Desert / Countryside Day Trip", "activity", 2, 360, 60, ("adventure", "kid-friendly")),
    ("Rooftop Bar", "nightlife", 3, 120, 45, ("rooftop", "evening")),
    ("Night Market", "nightlife", 1, 120, 12, ("evening", "local", "kid-friendly")),
    ("Luxury Spa Retreat", "wellness", 4, 180, 160, ("exclusive",)),
    ("Designer Shopping Street", "shopping", 3, 120, 0, ("exclusive",)),
    ("Artisan Flea Market", "shopping", 1, 90, 0, ("local", "free", "kid-friendly")),
    ("Indian Vegetarian Restaurant", "food", 2, 70, 22, ("pure-veg", "vegetarian", "jain", "kid-friendly")),
    ("Street Food Alley", "food", 1, 60, 10, ("local", "kid-friendly", "non-veg")),
    ("Market Hall Food Court", "food", 1, 60, 14, ("kid-friendly", "local", "vegetarian")),
    ("Family Trattoria", "food", 2, 75, 28, ("kid-friendly", "vegetarian")),
    ("Vegetarian Kitchen", "food", 2, 70, 24, ("vegetarian", "pure-veg")),
    ("Dumpling House", "food", 1, 50, 12, ("quick", "kid-friendly", "non-veg")),
    ("Seafood Grill", "food", 3, 90, 60, ("non-veg",)),
    ("Executive Lunch Club", "food", 3, 60, 55, ("business", "quick", "vegetarian")),
    ("Chef's Tasting Room", "food", 4, 150, 210, ("michelin", "exclusive", "vegetarian")),
    ("Rooftop Fine Dining", "food", 4, 120, 150, ("rooftop", "exclusive")),
]


def demo_places(city: str, center: GeoPoint) -> list[Place]:
    rng = _rng("places", city)
    factor = price_factor(city)
    ic = indian_city(city)
    templates = _INDIA_PLACES + _REGION_EXTRAS.get(ic.region, []) if ic else _FOREIGN_PLACES
    city_name = city.split(",")[0].strip().title()
    # A handful of neighborhoods, so geographic clustering has real structure.
    hoods = [center] + [
        offset(center, r * math.sin(a), r * math.cos(a))
        for r, a in ((rng.uniform(1.5, 4.5), rng.uniform(0, 2 * math.pi)) for _ in range(5))
    ]
    places: list[Place] = []
    for i, (name, cat, price, dur, cost, tags) in enumerate(templates):
        hood = rng.choice(hoods)
        loc = offset(hood, rng.uniform(-0.8, 0.8), rng.uniform(-0.8, 0.8))
        full = name.format(city=city_name)
        places.append(
            Place(
                id=f"demo-pl-{i}", name=full, category=cat, location=loc,
                rating=round(rng.uniform(4.0, 4.9), 1), review_count=rng.randint(120, 18000),
                price_level=price, est_cost_per_person=round(cost * factor, -1), duration_min=dur,
                address=city_name, source="demo", tags=list(tags),
                url=f"https://www.google.com/maps/search/?api=1&query={quote_plus(full + ' ' + city_name)}",
            )
        )
    return places
