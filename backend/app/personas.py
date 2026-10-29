"""Persona profiles: how each audience segment changes search, ranking and tone.

These are the knobs every agent reads. Weights are relative; each scorer
normalizes its own inputs to 0..1 before applying them. Tuned for travelers
based in India (train classes, Indian meal times, typical amenities).
"""

from dataclasses import dataclass, field

from .models import Persona


@dataclass(frozen=True)
class PersonaProfile:
    key: Persona
    label: str
    tagline: str
    tone: str

    # Budget split (fractions of total budget) used as soft targets.
    flight_share: float
    lodging_share: float
    activity_share: float
    food_share: float

    # Logistics
    cabin: str
    train_classes: tuple[str, ...]  # IRCTC classes in order of preference
    max_stops: int
    min_layover_min: int
    max_layover_min: int
    flight_weights: dict[str, float]  # price, duration, stops, layover, timing

    # Accommodation
    min_stars: float
    max_stars: float
    preferred_kinds: tuple[str, ...]
    required_tags: tuple[str, ...]
    preferred_amenities: tuple[str, ...]
    hotel_weights: dict[str, float]  # price, rating, stars, distance, amenities

    # Experiences
    activities_per_day: int
    max_price_level: int
    min_price_level: int
    day_start: str
    lunch_at: str
    dinner_at: str
    day_end: str
    favored_categories: tuple[str, ...]
    excluded_categories: tuple[str, ...] = field(default_factory=tuple)
    favored_tags: tuple[str, ...] = field(default_factory=tuple)


PERSONAS: dict[str, PersonaProfile] = {
    "budget": PersonaProfile(
        key="budget",
        label="Budget Backpacker",
        tagline="Hostels & homestays, sleeper trains and budget airlines, street food and free local gems.",
        tone="upbeat, resourceful and frugal (paisa vasool); call out money-saving tips and free things to do",
        flight_share=0.35, lodging_share=0.28, activity_share=0.12, food_share=0.25,
        cabin="ECONOMY", train_classes=("SL", "3A", "CC"), max_stops=2, min_layover_min=45, max_layover_min=10 * 60,
        flight_weights={"price": 0.70, "duration": 0.12, "stops": 0.08, "layover": 0.05, "timing": 0.05},
        min_stars=0, max_stars=3, preferred_kinds=("hostel", "homestay", "guesthouse", "hotel"),
        required_tags=(), preferred_amenities=("free wifi", "free breakfast", "kitchen", "lockers", "common room"),
        hotel_weights={"price": 0.55, "rating": 0.25, "stars": 0.0, "distance": 0.12, "amenities": 0.08},
        activities_per_day=4, max_price_level=1, min_price_level=0,
        day_start="08:30", lunch_at="13:00", dinner_at="20:00", day_end="23:00",
        favored_categories=("sight", "nature", "culture", "nightlife"),
        favored_tags=("free", "local", "walking", "spiritual"),
    ),
    "luxury": PersonaProfile(
        key="luxury",
        label="Luxury Traveler",
        tagline="Heritage palaces & 5-star resorts, business class, private chauffeurs, fine dining.",
        tone="refined, warm and concierge-like; emphasize exclusivity, comfort and seamless service",
        flight_share=0.30, lodging_share=0.45, activity_share=0.12, food_share=0.13,
        cabin="BUSINESS", train_classes=("EC", "1A"), max_stops=1, min_layover_min=60, max_layover_min=4 * 60,
        flight_weights={"price": 0.10, "duration": 0.35, "stops": 0.35, "layover": 0.10, "timing": 0.10},
        min_stars=4.5, max_stars=5, preferred_kinds=("hotel", "resort", "heritage"),
        required_tags=(), preferred_amenities=("ayurvedic spa", "spa", "concierge", "fine dining", "butler", "airport transfer", "pool"),
        hotel_weights={"price": 0.05, "rating": 0.40, "stars": 0.25, "distance": 0.10, "amenities": 0.20},
        activities_per_day=3, max_price_level=4, min_price_level=2,
        day_start="09:30", lunch_at="13:30", dinner_at="20:30", day_end="23:00",
        favored_categories=("culture", "wellness", "sight", "shopping"),
        favored_tags=("private", "exclusive", "heritage", "rooftop"),
    ),
    "business": PersonaProfile(
        key="business",
        label="Corporate / Business",
        tagline="Fastest flight or Vande Bharat, stays near the venue, reliable Wi-Fi and workspace.",
        tone="crisp, efficient and professional; lead with timings, proximity and productivity",
        flight_share=0.40, lodging_share=0.42, activity_share=0.05, food_share=0.13,
        cabin="ECONOMY", train_classes=("EC", "CC", "1A", "2A"), max_stops=1, min_layover_min=45, max_layover_min=3 * 60,
        flight_weights={"price": 0.15, "duration": 0.45, "stops": 0.25, "layover": 0.05, "timing": 0.10},
        min_stars=3.5, max_stars=5, preferred_kinds=("hotel", "apartment"),
        required_tags=(), preferred_amenities=("business center", "fast wifi", "workspace", "meeting rooms", "power backup", "gym"),
        hotel_weights={"price": 0.15, "rating": 0.20, "stars": 0.05, "distance": 0.45, "amenities": 0.15},
        activities_per_day=1, max_price_level=3, min_price_level=1,
        day_start="18:30", lunch_at="13:00", dinner_at="20:30", day_end="23:00",
        favored_categories=("sight", "culture"),
        excluded_categories=("kids",),
        favored_tags=("quick", "evening"),
    ),
    "family": PersonaProfile(
        key="family",
        label="Family",
        tagline="Family-friendly resorts, AC trains or short flights, kid-approved fun, pure-veg options.",
        tone="warm, reassuring and practical; mention safety, rest breaks, kid appeal and food options for children",
        flight_share=0.33, lodging_share=0.35, activity_share=0.15, food_share=0.17,
        cabin="ECONOMY", train_classes=("3A", "2A", "CC"), max_stops=1, min_layover_min=60, max_layover_min=3 * 60,
        flight_weights={"price": 0.30, "duration": 0.25, "stops": 0.25, "layover": 0.10, "timing": 0.10},
        min_stars=3, max_stars=5, preferred_kinds=("hotel", "resort", "apartment", "homestay", "heritage"),
        required_tags=("family-friendly",), preferred_amenities=("pool", "family rooms", "kids club", "free breakfast", "kitchenette"),
        hotel_weights={"price": 0.25, "rating": 0.25, "stars": 0.05, "distance": 0.15, "amenities": 0.30},
        activities_per_day=3, max_price_level=2, min_price_level=0,
        day_start="09:30", lunch_at="13:00", dinner_at="19:30", day_end="21:00",
        favored_categories=("kids", "nature", "sight"),
        excluded_categories=("nightlife",),
        favored_tags=("kid-friendly", "accessible", "interactive"),
    ),
}


def get_persona(key: str) -> PersonaProfile:
    return PERSONAS[key]


def persona_catalog() -> list[dict]:
    return [
        {"key": p.key, "label": p.label, "tagline": p.tagline, "cabin": p.cabin, "activities_per_day": p.activities_per_day}
        for p in PERSONAS.values()
    ]
