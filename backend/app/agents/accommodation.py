"""Accommodation Agent: finds lodging that matches the persona's criteria."""

from __future__ import annotations

import json

from ..config import get_settings
from ..geo import haversine_km
from ..india import INDIA_CONTEXT
from ..llm import STR, arr, get_llm, obj
from ..models import HotelOption, TripRequest
from ..personas import PersonaProfile, get_persona
from ..providers.hotels import search_hotels
from ..providers.xotelo import attach_live_rates
from .state import HotelPrefs, PlannerState, emit, money

AGENT = "accommodation"

SYSTEM = (
    "You are the Accommodation Agent in a multi-agent travel planner. From a pre-filtered shortlist, "
    "pick the single best stay for the persona: weigh nightly price against the soft lodging budget, "
    "guest rating, star class, distance to the anchor point and persona-relevant amenities. "
    "Keep the rationale to one or two concrete sentences that cite numbers. Values named in "
    "`estimated_fields` are estimates - present them as approximate (e.g. 'about ₹4,000/night', '~4★'), "
    "and when rating_out_of_10 is null, do not mention or invent a guest rating. " + INDIA_CONTEXT
)

PICK_SCHEMA = obj({"chosen_id": STR, "rationale": STR, "tags": arr(STR)})


def _has(h: HotelOption, amenity: str) -> bool:
    a = amenity.lower()
    return any(a in x.lower() for x in h.amenities) or any(a in t.lower() for t in h.tags)


def rank_hotels(
    hotels: list[HotelOption], req: TripRequest, profile: PersonaProfile, prefs: HotelPrefs
) -> tuple[list[HotelOption], list[HotelOption], list[str]]:
    """Returns (matches, other scored properties, notes). Matches pass every filter."""
    notes: list[str] = []
    target = req.budget * profile.lodging_share / req.nights

    def apply(pool, pred, why):
        kept = [h for h in pool if pred(h)]
        if kept:
            return kept
        notes.append(why)
        return pool

    pool = list(hotels)
    # An explicit price cap ("find a cheaper hotel") outranks persona defaults like star class,
    # so it's applied first and the softer filters below relax around it if needed.
    if prefs.max_price_per_night:
        pool = apply(pool, lambda h: h.price_per_night <= prefs.max_price_per_night,
                     f"Nothing under {money(prefs.max_price_per_night)}/night; showing the cheapest available.")
    lo = prefs.min_stars if prefs.min_stars is not None else profile.min_stars
    hi = max(profile.max_stars, lo)
    pool = apply(pool, lambda h: lo - 0.5 <= h.stars <= hi + 0.01 if lo else h.stars <= hi + 0.01,
                 f"No {lo:g}-{hi:g}★ properties available; relaxed the star filter.")
    if profile.preferred_kinds:
        pool = apply(pool, lambda h: h.kind in profile.preferred_kinds, "Widened property types.")
    # Required tags are only enforced when the source reliably reports amenities
    # (live listings and OSM often don't, so missing data must not disqualify a real hotel).
    for tag in profile.required_tags:
        pool = apply(pool, lambda h, t=tag: t in h.tags or h.source != "demo", f"Few '{tag}' properties; widened search.")
    for amenity in prefs.must_have:
        pool = apply(pool, lambda h, a=amenity: _has(h, a), f"Couldn't find stays with '{amenity}'; showing the closest matches.")

    w = dict(profile.hotel_weights)
    if prefs.prefer == "cheapest":
        w = {**w, "price": 0.75, "rating": 0.15}
    elif prefs.prefer == "best_rated":
        w = {**w, "rating": 0.55, "price": 0.1}
    elif prefs.prefer == "closest":
        w = {**w, "distance": 0.6, "price": 0.1}

    wanted = [*profile.preferred_amenities, *prefs.must_have]
    for h in hotels:  # score everything so non-matches can still be offered as alternatives
        ratio = h.price_per_night / target if target > 0 else 1.0
        if profile.key == "budget" or prefs.prefer == "cheapest":
            price_fit = max(0.0, 1 - ratio / 2)  # cheaper is better
        elif profile.key == "luxury":
            # Comfortably within budget is ideal; a very cheap room is not what a luxury traveller wants.
            price_fit = 0.3 + 0.7 * min(1.0, ratio / 0.5) if ratio <= 1.3 else max(0.0, 1 - (ratio - 1))
        else:
            # Use the lodging budget well: best near the target, penalise going over it.
            price_fit = 0.6 + 0.4 * ratio if ratio <= 1 else max(0.0, 1 - (ratio - 1))
        # No guest rating (e.g. OpenStreetMap): use the star class as the quality signal instead.
        r10 = _rating10(h)
        rating = max(0.0, min(1.0, (r10 - 6) / 4)) if r10 is not None else h.stars / 5
        stars = h.stars / 5
        distance = 1 - min(h.distance_km, 8) / 8
        amen = sum(_has(h, a) for a in wanted) / len(wanted) if wanted and h.amenities else 0.4
        h.score = round(
            w["price"] * price_fit + w["rating"] * rating + w["stars"] * stars + w["distance"] * distance + w["amenities"] * amen, 4
        )
        h.tags = [t for t in h.tags if t in ("family-friendly", "business-ready", "heritage", "pure-veg")]
        if h.price_per_night <= target:
            h.tags.append("Within budget")
    pool.sort(key=lambda h: h.score, reverse=True)
    if pool:
        min(pool, key=lambda h: h.price_per_night).tags.append("Lowest price")
        rated = [h for h in pool if h.rating is not None]
        if rated:
            max(rated, key=lambda h: (_rating10(h), h.review_count)).tags.append("Top rated")
    pool_ids = {h.id for h in pool}
    others = sorted((h for h in hotels if h.id not in pool_ids), key=lambda h: h.score, reverse=True)
    return pool, others, notes


def _rating10(h: HotelOption) -> float | None:
    """Guest rating on a 0-10 scale (TripAdvisor uses 5), shrunk towards 8/10 when there are
    few reviews, so 5.0 from 3 reviews doesn't beat 4.8 from 5,000."""
    if h.rating is None:
        return None
    r10 = h.rating * 10 / (h.rating_scale or 10)
    if h.review_count:
        prior, weight = 8.0, 50
        r10 = (r10 * h.review_count + prior * weight) / (h.review_count + weight)
    return r10


def _rating_text(h: HotelOption) -> str:
    if h.rating is None:
        return ""
    src = " on TripAdvisor" if h.source == "tripadvisor" else ""
    return f" rated {h.rating:g}/{h.rating_scale}{src} ({h.review_count:,} reviews),"


def _describe(h: HotelOption) -> dict:
    return {
        "id": h.id, "name": h.name, "type": h.kind, "stars": h.stars, "rating_out_of_10": _rating10(h),
        "reviews": h.review_count, "price_per_night_inr": round(h.price_per_night), "km_to_anchor": round(h.distance_km, 1),
        "estimated_fields": h.estimated, "source": h.source,
        "amenities": h.amenities[:10], "tags": h.tags, "heuristic_score": h.score,
    }


async def accommodation_node(state: PlannerState) -> dict:
    req = state["request"]
    profile = get_persona(req.persona)
    prefs = state["prefs"].hotel
    geo = state["geo"]

    emit(AGENT, "working", f"Searching stays in {req.destination} for {req.nights} night(s)...")
    try:
        hotels, source = await search_hotels(
            get_settings(), city=req.destination, center=geo.center, checkin=req.start_date,
            checkout=req.end_date, adults=req.adults, children=req.children,
        )
        for h in hotels:
            h.distance_km = round(haversine_km(geo.anchor, h.location), 2)
        filters = {
            "budget": "hostels, homestays & budget hotels", "luxury": "5-star hotels, heritage palaces & resorts",
            "business": f"business-ready hotels near {geo.anchor_label}", "family": "family-friendly stays with pools & family rooms",
        }[profile.key]
        if source == "openstreetmap":
            emit(AGENT, "working", f"Found {len(hotels)} real properties on OpenStreetMap (nightly prices are estimates)")
        emit(AGENT, "working", f"Filtering {len(hotels)} properties from {source} for {filters}...")

        ranked, others, notes = rank_hotels(hotels, req, profile, prefs)
        if source == "tripadvisor":
            # Live prices for the shortlist only (keeps the free service's load light), then re-rank on them.
            candidates = (ranked + others)[:10]
            emit(AGENT, "working", f"Found {len(hotels)} real hotels; checking live prices for the best "
                                   f"{len(candidates)} on Booking.com, Agoda, Trip.com...")
            live_count = await attach_live_rates(candidates, req.start_date, req.end_date, req.adults, req.children)
            live = [h for h in candidates if "price" not in h.estimated]
            if live:
                emit(AGENT, "working", f"Got live prices for {live_count} hotels "
                                       f"({len(candidates) - live_count} had no availability for your dates)")
                ranked, others, notes = rank_hotels(live, req, profile, prefs)
            else:
                notes.append("Live prices unavailable right now; showing typical prices from TripAdvisor.")
        for n in notes:
            emit(AGENT, "working", n)
        if not ranked:
            emit(AGENT, "error", "No properties found.")
            return {"hotels": [], "sources": {"hotels": source}, "errors": ["No hotels found"]}

        shortlist = ranked[:6]
        llm = get_llm()
        choice = None
        if llm.available:
            emit(AGENT, "working", "Comparing the top properties with Claude...")
            choice = await llm.json(
                system=SYSTEM,
                prompt=(
                    f"Persona: {profile.label} - {profile.tagline}\n"
                    f"Party: {req.adults} adult(s), {req.children} child(ren); {req.nights} nights. "
                    f"Soft lodging budget ≈ {money(req.budget * profile.lodging_share / req.nights)}/night.\n"
                    f"Anchor point: {geo.anchor_label}. Preferred amenities: {', '.join(profile.preferred_amenities)}.\n"
                    f"User preferences: {prefs.model_dump_json(exclude_defaults=True)}\n"
                    f"Traveler notes: {req.notes or 'none'}\n\n"
                    f"Shortlist (JSON):\n{json.dumps([_describe(h) for h in shortlist], indent=1, ensure_ascii=False)}\n\n"
                    "Return the id of the best option, a short rationale, and up to 3 short tags."
                ),
                schema=PICK_SCHEMA,
                effort="low",
            )
        chosen = next((h for h in shortlist if choice and h.id == choice.get("chosen_id")), shortlist[0])
        if choice and chosen.id == choice.get("chosen_id"):
            chosen.rationale = choice.get("rationale", "")
            chosen.tags = list(dict.fromkeys([*chosen.tags, *choice.get("tags", [])[:3]]))
        else:
            stars = f"~{chosen.stars:g}★" if "stars" in chosen.estimated else f"{chosen.stars:g}★"
            rated = _rating_text(chosen)
            price = ("about " if "price" in chosen.estimated else "") + f"{money(chosen.price_per_night, chosen.currency)}/night"
            chosen.rationale = (
                f"{stars} {chosen.kind}{rated} {chosen.distance_km:.1f} km from {geo.anchor_label}, at {price}."
            )
        # Strict matches first, then the best of the rest so there are always alternatives to pick.
        ordered = ([chosen] + [h for h in ranked if h.id != chosen.id] + others)[:8]
        emit(AGENT, "done", f"Selected {chosen.name} · {money(chosen.price_per_night, chosen.currency)}/night")
        return {"hotels": ordered, "sources": {"hotels": source}}
    except Exception as exc:
        emit(AGENT, "error", f"Hotel search failed: {exc}")
        return {"errors": [f"accommodation: {exc}"]}
