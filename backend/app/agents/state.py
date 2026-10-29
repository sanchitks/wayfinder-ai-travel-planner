from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from ..india import format_inr
from ..models import DayPlan, FlightOption, GeoPoint, HotelOption, Itinerary, TripRequest


class FlightPrefs(BaseModel):
    nonstop_only: bool = False
    max_price: float | None = None
    cabin: str | None = None
    prefer: Literal["cheapest", "fastest", "balanced"] | None = None
    avoid_red_eye: bool = False
    mode: Literal["any", "train", "flight"] | None = None  # domestic trips: rail vs air


class HotelPrefs(BaseModel):
    max_price_per_night: float | None = None
    min_stars: float | None = None
    must_have: list[str] = Field(default_factory=list)
    prefer: Literal["cheapest", "best_rated", "closest"] | None = None


class ExperiencePrefs(BaseModel):
    add_interests: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    pace: Literal["relaxed", "balanced", "packed"] | None = None
    dietary: list[str] = Field(default_factory=list)
    exclude_names: list[str] = Field(default_factory=list)


class Preferences(BaseModel):
    flights: FlightPrefs = Field(default_factory=FlightPrefs)
    hotel: HotelPrefs = Field(default_factory=HotelPrefs)
    experience: ExperiencePrefs = Field(default_factory=ExperiencePrefs)


class GeoContext(BaseModel):
    origin_code: str
    dest_code: str
    origin_point: GeoPoint | None = None
    center: GeoPoint
    anchor: GeoPoint
    anchor_label: str = "city center"
    domestic: bool = False  # both ends in India -> Indian Railways is an option


def _merge(a: dict | None, b: dict | None) -> dict:
    return {**(a or {}), **(b or {})}


class PlannerState(TypedDict, total=False):
    request: TripRequest
    prefs: Preferences
    geo: GeoContext
    user_message: str
    is_refinement: bool
    targets: list[str]
    halt: bool
    selection: dict | None
    flights: list[FlightOption]
    flight_tip: str
    hotels: list[HotelOption]
    days: list[DayPlan]
    sources: Annotated[dict[str, str], _merge]
    history: Annotated[list[dict], operator.add]
    itinerary: Itinerary | None
    errors: Annotated[list[str], operator.add]


ALL_WORKERS = ["logistics", "accommodation", "experience"]


def emit(agent: str, status: str, message: str, **extra) -> None:
    """Push a live status event to the SSE stream (stream_mode='custom')."""
    get_stream_writer()({"type": "agent", "agent": agent, "status": status, "message": message, **extra})


def emit_message(content: str) -> None:
    get_stream_writer()({"type": "message", "role": "assistant", "content": content})


def norm01(values: list[float]) -> list[float]:
    """Min-max normalize to 0..1 (all-equal input -> all 0.5)."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def money(v: float, currency: str = "INR") -> str:
    if currency == "INR":
        return format_inr(v)
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency, "")
    return f"{symbol}{v:,.0f}" if symbol else f"{v:,.0f} {currency}"
