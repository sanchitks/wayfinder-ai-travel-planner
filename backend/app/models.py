from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Persona = Literal["budget", "luxury", "business", "family"]
AgentName = Literal["orchestrator", "logistics", "accommodation", "experience"]


class TripRequest(BaseModel):
    origin: str = Field(..., min_length=2, max_length=80)
    destination: str = Field(..., min_length=2, max_length=80)
    start_date: date
    end_date: date
    adults: int = Field(1, ge=1, le=9)
    children: int = Field(0, ge=0, le=8)
    budget: float = Field(..., gt=0, description="Total trip budget for all travelers")
    persona: Persona
    interests: list[str] = Field(default_factory=list)
    flexible_dates: bool = False
    work_location: str | None = Field(None, description="Business travelers: venue/office to stay near")
    notes: str = Field("", max_length=2000)

    @model_validator(mode="after")
    def _check_dates(self) -> TripRequest:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if (self.end_date - self.start_date).days > 21:
            raise ValueError("Trips are limited to 21 nights")
        return self

    @property
    def nights(self) -> int:
        return (self.end_date - self.start_date).days

    @property
    def travelers(self) -> int:
        return self.adults + self.children


class GeoPoint(BaseModel):
    lat: float
    lng: float


class FlightSegment(BaseModel):
    carrier: str
    flight_number: str
    origin: str
    destination: str
    depart: datetime
    arrive: datetime
    duration_min: int


class FlightLeg(BaseModel):
    segments: list[FlightSegment]
    duration_min: int
    stops: int
    max_layover_min: int = 0

    @property
    def depart(self) -> datetime:
        return self.segments[0].depart

    @property
    def arrive(self) -> datetime:
        return self.segments[-1].arrive


class BookingOption(BaseModel):
    """Where to buy a fare (live, from Ignav). Wayfinder never takes payment; these open the seller's site."""

    leg: str  # "outbound", "inbound" or "round trip"
    provider: str
    provider_type: str | None = None  # "airline" | "third_party"
    price: float | None = None
    currency: str = "INR"
    price_verified: bool = False
    exact_flight: bool = False  # True if the link preselects this flight
    url: str


class FlightOption(BaseModel):
    """A round trip by air or rail. For trains, `cabin` is the IRCTC class
    (SL, 3A, 2A, 1A, CC, EC) and each segment's carrier is the train name."""

    id: str
    mode: Literal["flight", "train"] = "flight"
    outbound: FlightLeg
    inbound: FlightLeg | None = None
    price: float
    currency: str = "INR"
    cabin: str = "ECONOMY"
    carriers: list[str] = Field(default_factory=list)
    source: str = "demo"
    booking_url: str = ""
    provider_ref: str = ""  # e.g. Ignav's ignav_id, needed to fetch booking links
    price_verified: bool | None = None  # live sources: was the fare confirmed by the seller?
    observed_at: str | None = None  # when the live fare was retrieved (UTC)
    booking_options: list[BookingOption] = Field(default_factory=list)
    score: float = 0.0
    tags: list[str] = Field(default_factory=list)
    rationale: str = ""


class HotelOption(BaseModel):
    id: str
    name: str
    kind: str = "hotel"
    stars: float = 3
    rating: float | None = None  # guest rating; None when the source has none (never invented)
    rating_scale: int = 10  # 10 for Booking.com-style scores, 5 for TripAdvisor bubbles
    review_count: int = 0
    reviews_url: str = ""  # where the reviews/ratings come from
    price_per_night: float
    total_price: float
    currency: str = "INR"
    location: GeoPoint
    address: str = ""
    amenities: list[str] = Field(default_factory=list)
    distance_km: float = 0.0
    photo_url: str = ""
    booking_url: str = ""
    maps_url: str = ""
    website: str = ""
    phone: str = ""
    source: str = "demo"
    # Which fields are estimates rather than source data, e.g. ["price", "stars"].
    estimated: list[str] = Field(default_factory=list)
    booking_options: list[BookingOption] = Field(default_factory=list)  # live per-seller prices
    price_checked_at: str | None = None  # when live prices were fetched (UTC ISO)
    score: float = 0.0
    tags: list[str] = Field(default_factory=list)
    rationale: str = ""


PlaceCategory = Literal["sight", "food", "activity", "nightlife", "nature", "kids", "culture", "shopping", "wellness"]


class Place(BaseModel):
    id: str
    name: str
    category: PlaceCategory
    location: GeoPoint
    # Guest rating out of 5; None when the source has none (Wikipedia, OpenStreetMap) - never invented.
    rating: float | None = 4.3
    review_count: int = 0
    # 0-1 notability when there is no rating (e.g. from Wikipedia article length).
    popularity: float = 0.0
    price_level: int = Field(1, ge=0, le=4)
    est_cost_per_person: float = 0.0
    duration_min: int = 90
    address: str = ""
    url: str = ""
    image_url: str = ""
    description: str = ""
    source: str = "demo"
    tags: list[str] = Field(default_factory=list)
    score: float = 0.0


class ScheduledActivity(BaseModel):
    place: Place
    start: str
    end: str
    kind: Literal["activity", "meal"] = "activity"
    note: str = ""


class DayPlan(BaseModel):
    day: int
    date: date
    theme: str = ""
    area: str = ""
    activities: list[ScheduledActivity] = Field(default_factory=list)
    travel_km: float = 0.0
    center: GeoPoint | None = None


class CostBreakdown(BaseModel):
    flights: float = 0.0
    lodging: float = 0.0
    activities: float = 0.0
    food: float = 0.0
    total: float = 0.0
    budget: float = 0.0
    currency: str = "INR"


class Itinerary(BaseModel):
    request: TripRequest
    destination_center: GeoPoint | None = None
    flight: FlightOption | None = None
    flight_alternatives: list[FlightOption] = Field(default_factory=list)
    hotel: HotelOption | None = None
    hotel_alternatives: list[HotelOption] = Field(default_factory=list)
    days: list[DayPlan] = Field(default_factory=list)
    costs: CostBreakdown = Field(default_factory=CostBreakdown)
    summary: str = ""
    highlights: list[str] = Field(default_factory=list)
    data_sources: dict[str, str] = Field(default_factory=dict)
    version: int = 1
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --- API payloads -----------------------------------------------------------


class PlanRequest(BaseModel):
    request: TripRequest
    message: str = Field("", max_length=2000)


class RefineRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=2000)


class SelectRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    kind: Literal["flight", "hotel"]
    id: str = Field(..., min_length=1, max_length=200)


class RouteRequest(BaseModel):
    """Road routes for the map: each entry is an ordered list of stops."""

    profile: Literal["driving", "walking"] = "driving"
    routes: dict[str, list[GeoPoint]] = Field(max_length=20)
