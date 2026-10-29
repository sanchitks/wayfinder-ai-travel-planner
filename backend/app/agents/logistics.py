"""Logistics Agent: sources round trips (flights, plus Indian Railways trains on
domestic routes) and ranks them for the persona."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, timedelta

from ..config import get_settings
from ..india import INDIA_CONTEXT, indian_city
from ..llm import BOOL, STR, arr, get_llm, obj
from ..models import FlightOption
from ..personas import PersonaProfile, get_persona
from ..providers.flights import search_flights
from ..providers.ignav import IgnavClient, best_link
from ..providers.trains import CLASS_LABEL, demo_trains, rail_km
from .state import FlightPrefs, PlannerState, emit, money, norm01

AGENT = "logistics"
log = logging.getLogger(__name__)

SYSTEM = (
    "You are the Logistics Agent in a multi-agent travel planner. You receive pre-ranked round-trip "
    "options - flights and, for domestic Indian routes, Indian Railways trains - and choose the single "
    "best one for the traveler persona and constraints. Weigh price against door-to-door travel time, "
    "stops, layover comfort and departure times exactly as the persona would; an overnight AC train can "
    "beat a flight for budget or family travelers on mid-length routes. Keep the rationale to one or two "
    "concrete sentences that cite numbers. " + INDIA_CONTEXT
)

PICK_SCHEMA = obj({"chosen_id": STR, "rationale": STR, "tags": arr(STR), "persona_fit": BOOL})

# Door-to-door overhead on top of in-vehicle time: airport security/boarding vs. station arrival.
OVERHEAD_MIN = {"flight": 150, "train": 40}
MODE_TAGS = {"Train", "Overnight", "Day train"}


def _timing_penalty(opt: FlightOption, profile: PersonaProfile, prefs: FlightPrefs) -> float:
    if opt.mode == "train":
        # Evening departures are normal for overnight trains; arriving 00:00-05:00 is not.
        late = sum(1 for leg in (opt.outbound, opt.inbound) if leg and leg.arrive.hour < 5)
        return min(1.0, 0.5 * late)
    penalty = 0.0
    for leg in filter(None, (opt.outbound, opt.inbound)):
        hour = leg.depart.hour
        if hour < 6 or hour >= 23:  # red-eye
            penalty += 0.5 if (prefs.avoid_red_eye or profile.key in ("family", "luxury")) else 0.15
        if profile.key == "family" and (hour < 8 or hour >= 20):
            penalty += 0.3
        if profile.key == "business" and leg is opt.outbound and 6 <= hour <= 9:
            penalty -= 0.2  # early arrival = productive first day
    return max(0.0, min(1.0, penalty))


def _door_to_door(o: FlightOption) -> int:
    legs = [leg for leg in (o.outbound, o.inbound) if leg]
    return sum(leg.duration_min + OVERHEAD_MIN[o.mode] for leg in legs)


def rank_flights(
    options: list[FlightOption], profile: PersonaProfile, prefs: FlightPrefs
) -> tuple[list[FlightOption], list[FlightOption], list[str]]:
    """Returns (matches, other scored options, notes). Matches pass every filter."""
    notes: list[str] = []
    pool = list(options)
    if prefs.mode in ("train", "flight"):
        same = [o for o in pool if o.mode == prefs.mode]
        if same:
            pool = same
        else:
            notes.append(f"No {prefs.mode} options on this route; showing what's available.")
    within = [o for o in pool if o.outbound.stops <= profile.max_stops and (o.inbound is None or o.inbound.stops <= profile.max_stops)]
    if within:
        pool = within
    else:
        notes.append(f"No itineraries within {profile.max_stops} stop(s); relaxed the stop limit.")
    if prefs.nonstop_only:
        nonstop = [o for o in pool if o.outbound.stops == 0 and (o.inbound is None or o.inbound.stops == 0)]
        if nonstop:
            pool = nonstop
        else:
            notes.append("No nonstop round trips found; showing the fewest-stop options instead.")
    if prefs.max_price:
        under = [o for o in pool if o.price <= prefs.max_price]
        if under:
            pool = under
        else:
            notes.append(f"Nothing under {money(prefs.max_price)}; showing the cheapest available.")
    comfortable = [
        o for o in pool
        if all(
            leg.stops == 0 or profile.min_layover_min <= leg.max_layover_min <= profile.max_layover_min
            for leg in filter(None, (o.outbound, o.inbound))
        )
        # Only backpackers happily sit on a train for more than ~18 hours (one night is fine).
        and not (o.mode == "train" and profile.key != "budget" and prefs.mode != "train"
                 and o.outbound.duration_min > 18 * 60)
    ]
    if comfortable:
        pool = comfortable

    w = dict(profile.flight_weights)
    if prefs.prefer == "cheapest":
        w = {**w, "price": 0.8, "duration": 0.1}
    elif prefs.prefer == "fastest":
        w = {**w, "price": 0.1, "duration": 0.6}

    # Score every option (not just matches) so non-matches can still be offered as alternatives.
    price = norm01([o.price for o in options])
    dur = norm01([_door_to_door(o) for o in options])
    stops = norm01([o.outbound.stops + (o.inbound.stops if o.inbound else 0) for o in options])
    lay = norm01([max(o.outbound.max_layover_min, o.inbound.max_layover_min if o.inbound else 0) for o in options])
    for i, o in enumerate(options):
        o.score = round(
            1
            - (w["price"] * price[i] + w["duration"] * dur[i] + w["stops"] * stops[i] + w["layover"] * lay[i]
               + w["timing"] * _timing_penalty(o, profile, prefs)),
            4,
        )
        o.tags = [t for t in o.tags if t in MODE_TAGS]
        if o.mode == "flight" and o.outbound.stops == 0 and (o.inbound is None or o.inbound.stops == 0):
            o.tags.append("Nonstop")
    pool.sort(key=lambda o: o.score, reverse=True)
    if pool:
        min(pool, key=lambda o: o.price).tags.append("Cheapest")
        min(pool, key=_door_to_door).tags.append("Fastest")
    pool_ids = {o.id for o in pool}
    others = sorted((o for o in options if o.id not in pool_ids), key=lambda o: o.score, reverse=True)
    return pool, others, notes


async def attach_booking_links(f: FlightOption) -> None:
    """For a live Ignav fare, fetch where to book it (airline sites / agencies). 1 Ignav request."""
    if f.source != "ignav" or f.booking_options or not f.provider_ref:
        return
    try:
        f.booking_options = await IgnavClient(get_settings()).booking_links(f.provider_ref)
        f.booking_url = best_link(f.booking_options) or f.booking_url
    except Exception as exc:  # booking links are a bonus; never fail the plan over them
        log.warning("Ignav booking links failed: %s", exc)


def _label(o: FlightOption) -> str:
    if o.mode == "train":
        return f"{o.carriers[0]} ({CLASS_LABEL.get(o.cabin, o.cabin)})"
    return ", ".join(o.carriers)


def _describe(o: FlightOption) -> dict:
    def leg(l):
        return {
            "depart": l.depart.strftime("%a %H:%M"), "arrive": l.arrive.strftime("%a %H:%M"),
            "duration_h": round(l.duration_min / 60, 1), "stops": l.stops, "longest_layover_min": l.max_layover_min,
            "via": [s.destination for s in l.segments[:-1]],
        }
    return {"id": o.id, "mode": o.mode, "price_inr": round(o.price), "class": CLASS_LABEL.get(o.cabin, o.cabin),
            "operator": _label(o), "outbound": leg(o.outbound), "return": leg(o.inbound) if o.inbound else None,
            "door_to_door_hours": round(_door_to_door(o) / 60, 1), "heuristic_score": o.score}


async def logistics_node(state: PlannerState) -> dict:
    req = state["request"]
    profile = get_persona(req.persona)
    prefs = state["prefs"].flights
    geo = state["geo"]
    settings = get_settings()
    cabin = prefs.cabin or profile.cabin

    emit(AGENT, "working", f"Analyzing flight paths {geo.origin_code} → {geo.dest_code} ({cabin.replace('_', ' ').lower()})...")
    try:
        date_pairs: list[tuple[date, date]] = [(req.start_date, req.end_date)]
        if req.flexible_dates:
            for shift in (-1, 1):
                s = req.start_date + timedelta(days=shift)
                if s > date.today():
                    date_pairs.append((s, req.end_date + timedelta(days=shift)))
            emit(AGENT, "working", f"Flexible dates on - also checking ±1 day ({len(date_pairs)} date pairs)...")

        searches = await asyncio.gather(*(
            search_flights(
                settings, origin=req.origin, dest=req.destination, origin_code=geo.origin_code, dest_code=geo.dest_code,
                origin_pt=geo.origin_point, dest_pt=geo.center, depart=d0, ret=d1, adults=req.adults,
                children=req.children, cabin=cabin, nonstop=prefs.nonstop_only, domestic=geo.domestic,
            )
            for d0, d1 in date_pairs
        ))
        primary, source = searches[0]
        primary = list(primary)

        trains: list[FlightOption] = []
        if geo.domestic and prefs.mode != "flight":
            o_city, d_city = indian_city(req.origin), indian_city(req.destination)
            if o_city and d_city:
                emit(AGENT, "working", "Checking Indian Railways (IRCTC) trains on this route...")
                trains = demo_trains(o_city, d_city, req.start_date, req.end_date, req.adults, req.children, profile.train_classes)
                if trains:
                    emit(AGENT, "working", f"Found {len(trains)} trains (~{rail_km(o_city, d_city):,.0f} km by rail)")
                elif not (o_city.station and d_city.station):
                    emit(AGENT, "working", f"No direct rail link to {req.destination}; comparing flights only.")
        options = primary + trains
        sources = source + ("+irctc(sample)" if trains else "")
        if source == "ignav":
            emit(AGENT, "working", f"Got {len(primary)} live fares from Ignav (India market, prices in INR)")
        emit(AGENT, "working", f"Comparing {len(options)} round trips from {sources}; ranking for {profile.label}...")

        ranked, others, notes = rank_flights(options, profile, prefs)
        if not ranked:
            emit(AGENT, "error", "No flights or trains found for these dates.")
            return {"flights": [], "sources": {"flights": source}, "errors": ["No flights found"]}

        tip = ""
        if len(searches) > 1:
            best_alt = min((o for opts, _ in searches[1:] for o in opts), key=lambda o: o.price, default=None)
            flights_main = [o for o in ranked if o.mode == "flight"]
            if best_alt and flights_main:
                cheapest_main = min(o.price for o in flights_main)
                if best_alt.price < cheapest_main * 0.92:
                    tip = (f"Flexible-date tip: flying on {best_alt.outbound.depart:%a %d %b} instead saves about "
                           f"{money(cheapest_main - best_alt.price, best_alt.currency)}.")

        shortlist = ranked[:6]
        if trains and not any(o.mode == "train" for o in shortlist):  # let the LLM weigh rail vs air
            best_train = max((o for o in ranked if o.mode == "train"), key=lambda o: o.score, default=None)
            if best_train:
                shortlist = shortlist[:5] + [best_train]
        llm = get_llm()
        choice = None
        if llm.available:
            emit(AGENT, "working", "Weighing the shortlist with Claude...")
            choice = await llm.json(
                system=SYSTEM,
                prompt=(
                    f"Persona: {profile.label} - {profile.tagline}\n"
                    f"Travelers: {req.adults} adult(s), {req.children} child(ren). Total trip budget: {money(req.budget)}; "
                    f"soft transport budget ≈ {money(req.budget * profile.flight_share)}.\n"
                    f"User preferences: {prefs.model_dump_json(exclude_defaults=True)}\n"
                    f"Traveler notes: {req.notes or 'none'}\n\n"
                    f"Shortlist (JSON):\n{json.dumps([_describe(o) for o in shortlist], indent=1, ensure_ascii=False)}\n\n"
                    "Return the id of the best option, a short rationale, and up to 3 short tags "
                    "(e.g. 'Nonstop', 'Best value', 'Overnight AC train')."
                ),
                schema=PICK_SCHEMA,
                effort="low",
            )
        chosen = next((o for o in shortlist if choice and o.id == choice.get("chosen_id")), shortlist[0])
        if choice and chosen.id == choice.get("chosen_id"):
            chosen.rationale = choice.get("rationale", "")
            chosen.tags = list(dict.fromkeys([*chosen.tags, *choice.get("tags", [])[:3]]))
        else:
            o = chosen.outbound
            if chosen.mode == "train":
                when = "overnight" if o.arrive.date() > o.depart.date() else "daytime"
                chosen.rationale = (
                    f"Best {profile.label.lower()} balance: {_label(chosen)}, {when} journey of "
                    f"{o.duration_min // 60}h{o.duration_min % 60:02d}, {money(chosen.price, chosen.currency)} round trip for everyone."
                )
            else:
                stops = "nonstop" if o.stops == 0 else f"{o.stops} stop{'s' if o.stops > 1 else ''}"
                chosen.rationale = (
                    f"Best {profile.label.lower()} balance: {money(chosen.price, chosen.currency)} total, "
                    f"{o.duration_min // 60}h{o.duration_min % 60:02d} outbound, {stops}."
                )
        ordered = ([chosen] + [o for o in ranked if o.id != chosen.id] + others)[:8]
        # Always surface the best of the other mode among the first few alternatives.
        for mode in ("train", "flight"):
            if not any(o.mode == mode for o in ordered[:5]):
                best = max((o for o in options if o.mode == mode), key=lambda o: o.score, default=None)
                if best:
                    ordered = ordered[:2] + [best] + [o for o in ordered[2:] if o.id != best.id][:5]
        for n in notes:
            emit(AGENT, "working", n)
        if chosen.source == "ignav":
            emit(AGENT, "working", "Getting live booking links from the airlines...")
            await attach_booking_links(chosen)
        emit(AGENT, "done", f"Selected {_label(chosen)} · {money(chosen.price, chosen.currency)} round trip")
        return {"flights": ordered, "flight_tip": tip, "sources": {"flights": sources}}
    except Exception as exc:  # keep the rest of the plan alive
        emit(AGENT, "error", f"Travel search failed: {exc}")
        return {"errors": [f"logistics: {exc}"]}
