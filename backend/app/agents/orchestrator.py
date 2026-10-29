"""Orchestrator Agent (user-facing).

Two graph nodes:
  * orchestrator_node - understands the user's request or refinement, updates
    the trip brief/preferences, and decides which worker agents must (re)run.
    A "find a cheaper hotel" message only re-runs the Accommodation agent.
  * compile_node - merges worker output into one itinerary, reconciles the
    day plan with real flight times, totals costs, and writes the reply.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timedelta

from langgraph.graph import END
from pydantic import ValidationError

from ..geo import geocode, guess_iata
from ..india import INDIA_CONTEXT, is_indian, seasonal_tips
from ..llm import BOOL, INT, NUM, STR, arr, get_llm, nullable, obj
from ..models import CostBreakdown, DayPlan, Itinerary, TripRequest
from ..personas import PERSONAS, get_persona
from ..providers.trains import CLASS_LABEL
from .logistics import attach_booking_links
from .state import ALL_WORKERS, GeoContext, Preferences, PlannerState, emit, emit_message, money

AGENT = "orchestrator"

INTENT_SYSTEM = (
    "You are the Orchestrator of a multi-agent travel planner. Worker agents: logistics (flights and, "
    "for domestic Indian trips, Indian Railways trains), "
    "accommodation (hotels), experience (day-by-day activities and dining). Translate the traveler's "
    "message into structured updates and pick the minimal set of workers that must re-run - e.g. "
    "'find a cheaper hotel' re-runs only accommodation; changing dates, destination, travelers, persona "
    "or budget re-runs all. A pure question needs no workers. Use null for anything not mentioned. "
    "`reply` is a one-sentence acknowledgement of what you are about to do. Map Indian dietary "
    "needs to `dietary` using: jain, pure veg, vegetarian, vegan, halal, non veg (eats meat: wants places "
    "with non-veg dishes). 'Go by train' sets "
    "flights.mode=train; 'fly instead' sets flights.mode=flight. " + INDIA_CONTEXT
)

INTENT_SCHEMA = obj({
    "reply": STR,
    "targets": arr({"type": "string", "enum": ALL_WORKERS}),
    "request_updates": obj({
        "origin": nullable(STR), "destination": nullable(STR),
        "start_date": nullable(STR), "end_date": nullable(STR),
        "budget": nullable(NUM), "adults": nullable(INT), "children": nullable(INT),
        "persona": nullable({"type": "string", "enum": list(PERSONAS)}),
    }),
    "flights": obj({
        "nonstop_only": nullable(BOOL), "cheaper": nullable(BOOL), "avoid_red_eye": nullable(BOOL),
        "cabin": nullable({"type": "string", "enum": ["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"]}),
        "prefer": nullable({"type": "string", "enum": ["cheapest", "fastest", "balanced"]}),
        "mode": nullable({"type": "string", "enum": ["any", "train", "flight"]}),
    }),
    "hotel": obj({
        "cheaper": nullable(BOOL), "max_price_per_night": nullable(NUM), "min_stars": nullable(NUM),
        "must_have": arr(STR),
        "prefer": nullable({"type": "string", "enum": ["cheapest", "best_rated", "closest"]}),
    }),
    "experience": obj({
        "add_interests": arr(STR), "avoid": arr(STR), "dietary": arr(STR), "exclude_names": arr(STR),
        "pace": nullable({"type": "string", "enum": ["relaxed", "balanced", "packed"]}),
    }),
})

COMPILE_SYSTEM = (
    "You are the Orchestrator of a multi-agent travel planner, speaking directly to the traveler. "
    "You receive the final itinerary assembled by your Logistics, Accommodation and Experience agents. "
    "Write in the persona's tone. Be specific (names, prices, times); never invent options that are "
    "not in the data. If the traveler asked a question, answer it from the itinerary data. "
    "Weave in the local advice provided (season, altitude, booking windows) where relevant. " + INDIA_CONTEXT
)

COMPILE_SCHEMA = obj({"reply": STR, "summary": STR, "highlights": arr(STR)})


# --- intent -------------------------------------------------------------------

_AMENITIES = ("pool", "spa", "gym", "breakfast", "kitchen", "wifi", "parking", "kids club", "workspace", "airport transfer")
_INTERESTS = (
    "museum", "food", "nightlife", "nature", "hiking", "shopping", "art", "history", "beach", "wellness", "adventure",
    "architecture", "heritage", "temple", "spiritual", "mountain", "wildlife", "yoga", "bazaar", "ayurved", "ghat",
)
_DIETARY = ("jain", "pure veg", "vegetarian", "vegan", "halal")
_NON_VEG = re.compile(r"\bnon[- ]?veg(etarian)?\b")


def heuristic_intent(msg: str, req: TripRequest | None = None) -> dict:
    """Keyword fallback used when no LLM is configured."""
    m = msg.lower()
    intent: dict = {"targets": set(), "flights": {}, "hotel": {"must_have": []},
                    "experience": {"add_interests": [], "avoid": [], "dietary": [], "exclude_names": []}}
    hotel_words = re.search(r"hotel|stay|room|accommodation|hostel|homestay|haveli|resort|lodging|place to stay", m)
    flight_words = re.search(r"flight|fly|airline|layover|stopover|plane", m)
    cheaper = re.search(r"cheap|budget|less expensive|lower price|save money|affordable", m)

    if hotel_words:
        intent["targets"].add("accommodation")
        if cheaper:
            intent["hotel"]["cheaper"] = True
        if re.search(r"luxur|nicer|upgrade|5[- ]?star|better hotel|fancier", m):
            intent["hotel"]["prefer"] = "best_rated"
        if re.search(r"closer|central|near|walkable|location", m):
            intent["hotel"]["prefer"] = "closest"
    if re.search(r"haveli|heritage palace|palace (hotel|stay)|heritage (hotel|stay|property)", m):
        intent["hotel"]["must_have"].append("heritage")
        intent["targets"].add("accommodation")
    for a in _AMENITIES:
        if a in m:
            intent["hotel"]["must_have"].append(a)
            intent["targets"].add("accommodation")
    if flight_words or re.search(r"nonstop|non-stop|direct|red[- ]?eye", m):
        intent["targets"].add("logistics")
        if cheaper:
            intent["flights"]["cheaper"] = True
        if re.search(r"nonstop|non-stop|direct", m):
            intent["flights"]["nonstop_only"] = True
        if re.search(r"faster|fastest|shorter", m):
            intent["flights"]["prefer"] = "fastest"
        if re.search(r"red[- ]?eye|overnight|late night", m):
            intent["flights"]["avoid_red_eye"] = True
        if "business class" in m:
            intent["flights"]["cabin"] = "BUSINESS"
    if re.search(r"\btrain|\brail|irctc|rajdhani|shatabdi|vande bharat|sleeper|\b[23]ac\b|\b[123]a\b", m):
        intent["flights"]["mode"] = "train"
        intent["targets"].add("logistics")
    elif re.search(r"fly instead|by air|flights? only|prefer (a )?flight", m):
        intent["flights"]["mode"] = "flight"
        intent["targets"].add("logistics")
    if re.search(r"fastest|quickest|faster option|save time", m) and "logistics" not in intent["targets"]:
        intent["flights"]["prefer"] = "fastest"
        intent["targets"].add("logistics")
    if cheaper and not hotel_words and not flight_words:
        intent["targets"] |= {"accommodation", "logistics"}
        intent["hotel"]["cheaper"] = intent["flights"]["cheaper"] = True

    exp = intent["experience"]
    if re.search(r"relax|slower|fewer|less packed|less busy|downtime", m):
        exp["pace"] = "relaxed"
    elif re.search(r"more activities|packed|busier|more things", m):
        exp["pace"] = "packed"
    for word in _INTERESTS:
        if re.search(rf"\b(no|skip|avoid|without|less)\s+(\w+\s+)?{word}", m):
            exp["avoid"].append(word)
        elif re.search(rf"\b{word}", m):
            exp["add_interests"].append(word)
    if re.search(r"fine dining|upscale (restaurant|dining)|gourmet", m):
        exp["add_interests"].append("fine dining")
    # "non-veg" contains "veg" and "non-vegetarian" contains "vegetarian": take it out before the veg checks.
    plain = _NON_VEG.sub(" ", m)
    exp["dietary"] = [d for d in _DIETARY if d in plain] + (["non veg"] if _NON_VEG.search(m) else [])
    if re.search(r"\bveg\b", plain) and not exp["dietary"]:
        exp["dietary"].append("vegetarian")
    if exp["avoid"] or exp["add_interests"] or exp["dietary"] or exp.get("pace") or re.search(r"activit|day \d|itinerary|restaurant|dinner|lunch", m):
        intent["targets"].add("experience")

    shift = re.search(r"(\d+)\s+days?\s+(later|earlier)", m)
    if shift and req is not None:
        delta = timedelta(days=int(shift.group(1)) * (1 if shift.group(2) == "later" else -1))
        intent["request_updates"] = {"start_date": str(req.start_date + delta), "end_date": str(req.end_date + delta)}
        intent["targets"] = set(ALL_WORKERS)

    if not intent["targets"]:
        intent["targets"] = set(ALL_WORKERS)
        intent["reply"] = "I'll re-run the full plan with that in mind."
    else:
        names = {"logistics": "Logistics", "accommodation": "Accommodation", "experience": "Experience"}
        intent["reply"] = "On it - briefing the " + " & ".join(names[t] for t in ALL_WORKERS if t in intent["targets"]) + " agent(s); everything else stays as is."
    intent["targets"] = [t for t in ALL_WORKERS if t in intent["targets"]]
    return intent


def apply_intent(intent: dict, state: PlannerState) -> tuple[TripRequest, Preferences, list[str], str | None]:
    req: TripRequest = state["request"]
    prefs = state.get("prefs", Preferences()).model_copy(deep=True)
    targets = [t for t in intent.get("targets", []) if t in ALL_WORKERS]

    updates = {k: v for k, v in (intent.get("request_updates") or {}).items() if v not in (None, "")}
    error = None
    if updates:
        try:
            req = TripRequest.model_validate({**req.model_dump(), **updates})
            targets = list(ALL_WORKERS)
        except ValidationError as exc:
            error = "; ".join(e["msg"] for e in exc.errors())

    f = intent.get("flights") or {}
    flights = state.get("flights") or []
    if f.get("cheaper") and flights:
        prefs.flights.max_price = round(flights[0].price * 0.95, 2)
        prefs.flights.prefer = prefs.flights.prefer or "cheapest"
    for key in ("nonstop_only", "avoid_red_eye", "cabin", "prefer", "mode"):
        if f.get(key) is not None:
            setattr(prefs.flights, key, f[key])

    h = intent.get("hotel") or {}
    hotels = state.get("hotels") or []
    if h.get("cheaper") and hotels:
        prefs.hotel.max_price_per_night = round(hotels[0].price_per_night * 0.85, 2)
        prefs.hotel.prefer = "cheapest" if prefs.hotel.prefer in (None, "best_rated") else prefs.hotel.prefer
    for key in ("max_price_per_night", "min_stars", "prefer"):
        if h.get(key) is not None:
            setattr(prefs.hotel, key, h[key])
    prefs.hotel.must_have = sorted({*prefs.hotel.must_have, *(h.get("must_have") or [])})

    e = intent.get("experience") or {}
    xp = prefs.experience
    xp.avoid = sorted({*xp.avoid, *(e.get("avoid") or [])})
    xp.add_interests = sorted({*xp.add_interests, *(e.get("add_interests") or [])} - set(xp.avoid))
    xp.dietary = sorted({*xp.dietary, *(e.get("dietary") or [])})
    xp.exclude_names = sorted({*xp.exclude_names, *(e.get("exclude_names") or [])})
    if e.get("pace"):
        xp.pace = e["pace"]
    return req, prefs, targets, error


async def build_geo(req: TripRequest) -> GeoContext:
    origin_pt, center, work_pt = await asyncio.gather(
        geocode(req.origin),
        geocode(req.destination),
        geocode(f"{req.work_location}, {req.destination}") if req.work_location else asyncio.sleep(0, result=None),
    )
    if center is None:
        raise ValueError(f"Couldn't locate '{req.destination}'. Try a major city name (e.g. 'Lisbon').")
    return GeoContext(
        origin_code=guess_iata(req.origin), dest_code=guess_iata(req.destination), origin_point=origin_pt,
        center=center, anchor=work_pt or center,
        anchor_label=req.work_location if work_pt else f"central {req.destination.split(',')[0].strip().title()}",
        domestic=is_indian(req.origin) and is_indian(req.destination),
    )


def _describe_prefs(p: Preferences) -> str:
    bits = []
    if p.flights.mode in ("train", "flight"):
        bits.append("travel by train" if p.flights.mode == "train" else "fly, not train")
    if p.flights.nonstop_only:
        bits.append("nonstop flights")
    if p.flights.avoid_red_eye:
        bits.append("no red-eyes")
    if p.flights.cabin:
        bits.append(p.flights.cabin.replace("_", " ").lower())
    bits += [f"hotel with {a}" for a in p.hotel.must_have]
    if p.hotel.min_stars:
        bits.append(f"{p.hotel.min_stars:g}★+ hotel")
    bits += p.experience.dietary
    bits += [f"more {i}" for i in p.experience.add_interests]
    bits += [f"no {a}" for a in p.experience.avoid]
    if p.experience.pace:
        bits.append(f"{p.experience.pace} pace")
    return ", ".join(bits)


def _context(state: PlannerState) -> str:
    req = state["request"]
    lines = [f"Current brief: {req.model_dump_json()}"]
    if state.get("flights"):
        f = state["flights"][0]
        lines.append(f"Current transport: {_travel_label(f)} {money(f.price, f.currency)} ({f.mode}), outbound stops {f.outbound.stops}")
    if state.get("hotels"):
        h = state["hotels"][0]
        lines.append(f"Current hotel: {h.name} {h.stars:g}★ {money(h.price_per_night, h.currency)}/night")
    if state.get("days"):
        lines.append("Current days: " + "; ".join(
            f"Day {d.day}: " + ", ".join(a.place.name for a in d.activities) for d in state["days"]
        ))
    history = state.get("history", [])[-6:]
    if history:
        lines.append("Recent chat: " + json.dumps(history))
    return "\n".join(lines)


async def orchestrator_node(state: PlannerState) -> dict:
    msg = (state.get("user_message") or "").strip()
    refining = state.get("is_refinement", False)
    llm = get_llm()
    out: dict = {}

    selection = state.get("selection")
    if selection:
        # The traveler picked an alternative in the UI: reorder, no re-search needed.
        key = "flights" if selection["kind"] == "flight" else "hotels"
        options = state.get(key) or []
        chosen = next((o for o in options if o.id == selection["id"]), None)
        if chosen is None:
            emit_message("That option is no longer available - try refreshing the plan.")
            return {"selection": None, "targets": [], "halt": True}
        label = chosen.name if key == "hotels" else f"{_travel_label(chosen)} ({money(chosen.price, chosen.currency)})"
        emit(AGENT, "working", f"Switching to {label}...")
        if key == "flights" and chosen.source == "ignav" and not chosen.booking_options:
            emit("logistics", "working", "Getting live booking links from the airlines...")
            await attach_booking_links(chosen)
            emit("logistics", "done", f"Booking links ready for {label}")
        emit_message(f"Switching to {label}.")
        return {
            key: [chosen] + [o for o in options if o.id != chosen.id],
            "selection": None, "targets": [], "halt": False,
            "history": [{"role": "user", "content": f"Choose {label}"}],
        }

    if not refining:
        req = state["request"]
        profile = get_persona(req.persona)
        emit(AGENT, "working", f"Reading your brief: {req.nights} nights in {req.destination} as a {profile.label.lower()}...")
        geo = await build_geo(req)
        out["geo"] = geo
        prefs = Preferences()
        reply = (f"Planning {req.nights} nights in {req.destination} for {req.travelers} traveler(s) on a "
                 f"{money(req.budget)} budget. Dispatching my Logistics, Accommodation and Experience agents in parallel.")
        free_text = " ".join(x for x in (req.notes, msg) if x)
        if free_text:
            intent = None
            if llm.available:
                emit(AGENT, "working", "Extracting preferences from your notes with Claude...")
                intent = await llm.json(
                    system=INTENT_SYSTEM,
                    prompt=f"{_context({'request': req})}\n\nTraveler's notes for a brand-new plan: {free_text}",
                    schema=INTENT_SCHEMA, effort="low",
                )
            intent = intent or heuristic_intent(free_text)
            intent["request_updates"] = {}  # the form is authoritative on a fresh plan
            _, prefs, _, _ = apply_intent(intent, {"request": req})
            noted = _describe_prefs(prefs)
            if noted:
                reply += f" Noted: {noted}."
        out.update({"prefs": prefs, "targets": list(ALL_WORKERS), "halt": False, "history": [{"role": "user", "content": free_text or "Plan my trip"}]})
        emit_message(reply)
        emit(AGENT, "done", "Brief ready - agents dispatched")
        return out

    emit(AGENT, "working", f'Interpreting: "{msg[:80]}"')
    intent = None
    if llm.available:
        intent = await llm.json(
            system=INTENT_SYSTEM,
            prompt=f"{_context(state)}\n\nTraveler's new message: {msg}",
            schema=INTENT_SCHEMA, effort="low",
        )
    intent = intent or heuristic_intent(msg, state["request"])
    req, prefs, targets, error = apply_intent(intent, state)
    if error:
        emit_message(f"I couldn't apply that change: {error}")
        emit(AGENT, "done", "No changes applied")
        return {"targets": [], "halt": True, "history": [{"role": "user", "content": msg}]}

    out.update({"request": req, "prefs": prefs, "targets": targets, "halt": False, "history": [{"role": "user", "content": msg}]})
    old = state["request"]
    if (req.origin, req.destination, req.work_location) != (old.origin, old.destination, old.work_location):
        out["geo"] = await build_geo(req)
    emit_message(intent.get("reply") or "Updating your plan.")
    emit(AGENT, "done", "Dispatching: " + (", ".join(targets) if targets else "no agents (answering directly)"))
    return out


def route_workers(state: PlannerState) -> list[str]:
    if state.get("halt"):
        return [END]
    return state.get("targets") or ["compile"]


# --- compile ------------------------------------------------------------------


def _reconcile_with_flights(days: list[DayPlan], arrive: datetime | None, depart: datetime | None) -> list[str]:
    """Drop activities that collide with the actual flight times."""
    notes = []
    for d in days:
        if arrive:
            if d.date < arrive.date():
                if d.activities:
                    notes.append(f"Day {d.day} is a travel day")
                d.activities, d.theme = [], "In transit"
            elif d.date == arrive.date() and d.activities:
                # Re-time the arrival day to start 90 min after landing. Sightseeing must
                # wrap up by 21:00 (nightlife excepted); dinner may run until 23:30.
                earliest = -(-_mins((arrive + timedelta(minutes=90)).strftime("%H:%M")) // 15) * 15
                if earliest > _mins(d.activities[0].start):
                    kept, t = [], earliest
                    for a in d.activities:
                        start = max(t, _mins(a.start))
                        end = start + _mins(a.end) - _mins(a.start)
                        late_sight = a.kind == "activity" and a.place.category != "nightlife" and end > 21 * 60
                        if late_sight or end > 23 * 60 + 30:
                            continue
                        kept.append(a.model_copy(update={"start": _hhmm(start), "end": _hhmm(end)}))
                        t = end + 15
                    notes.append(f"Re-timed Day {d.day} around your {arrive:%H:%M} arrival")
                    d.activities = kept
        if depart:
            if d.date > depart.date():
                d.activities, d.theme = [], "Homeward"
            elif d.date == depart.date():
                latest = (depart - timedelta(hours=3)).strftime("%H:%M")
                kept = [a for a in d.activities if a.end <= latest] if depart.hour >= 3 else []
                if len(kept) < len(d.activities):
                    notes.append(f"Trimmed Day {d.day} to finish before your {depart:%H:%M} flight")
                d.activities = kept
    for i, d in enumerate(days):
        if not any(a.kind == "activity" for a in d.activities) and d.theme not in ("In transit", "Homeward"):
            d.theme = "Arrival & settle in" if i == 0 else "Departure day" if i == len(days) - 1 else "Free day"
    return notes


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _travel_label(f) -> str:
    if f.mode == "train":
        return f"{f.carriers[0]} ({CLASS_LABEL.get(f.cabin, f.cabin)})"
    return ", ".join(f.carriers)


def _fallback_highlights(flight, hotel, days: list[DayPlan], wanted: list[str]) -> list[str]:
    out = []
    if flight and flight.mode == "train":
        o = flight.outbound
        when = "Overnight" if o.arrive.date() > o.depart.date() else "Daytime"
        out.append(
            f"{when} {_travel_label(flight)}, {o.duration_min // 60}h{o.duration_min % 60:02d} each way, "
            f"{money(flight.price, flight.currency)} round trip for everyone"
        )
    elif flight:
        o = flight.outbound
        out.append(
            f"{'Nonstop' if o.stops == 0 else f'{o.stops}-stop'} {', '.join(flight.carriers)} flight, "
            f"{o.duration_min // 60}h{o.duration_min % 60:02d} outbound, {money(flight.price, flight.currency)} round trip"
        )
    if hotel:
        ranked = sorted(hotel.amenities, key=lambda a: (a not in wanted, wanted.index(a) if a in wanted else 0))
        perks = ", ".join(ranked[:3])
        stars = f"~{hotel.stars:g}★ (est.)" if "stars" in hotel.estimated else f"{hotel.stars:g}★"
        rated = (f", rated {hotel.rating:g}/{hotel.rating_scale}"
                 + (f" by {hotel.review_count:,} TripAdvisor reviewers" if hotel.source == "tripadvisor" else "")
                 if hotel.rating is not None else "")
        if hotel.booking_options:
            seller = hotel.booking_options[0]
            rated += f" - live price {money(seller.price or 0, seller.currency)}/night on {seller.provider}"
        where = f" - {hotel.address}" if hotel.source == "openstreetmap" and hotel.address else ""
        out.append(f"{hotel.name}: {stars}{rated}" + (f" - {perks}" if perks else where))
    sights = sorted(
        (a for d in days for a in d.activities if a.kind == "activity"), key=lambda a: a.place.score, reverse=True
    )
    if sights:
        out.append("Don't miss: " + ", ".join(
            a.place.name + (f" (★{a.place.rating})" if a.place.rating is not None else "") for a in sights[:2]))
    free = [a.place.name for d in days for a in d.activities if a.kind == "activity" and a.place.est_cost_per_person == 0]
    if free:
        out.append(f"{len(free)} free experiences, including {free[0]}")
    return out[:4]


def _changes(prev: Itinerary | None, new: Itinerary) -> list[str]:
    if prev is None:
        return []
    out = []
    if prev.flight and new.flight and prev.flight.id != new.flight.id:
        out.append(f"Travel: {_travel_label(prev.flight)} {money(prev.flight.price)} → {_travel_label(new.flight)} {money(new.flight.price)}")
    if prev.hotel and new.hotel and prev.hotel.id != new.hotel.id:
        out.append(f"Hotel: {prev.hotel.name} ({money(prev.hotel.price_per_night)}/night) → {new.hotel.name} ({money(new.hotel.price_per_night)}/night)")
    before = {a.place.name for d in prev.days for a in d.activities}
    after = {a.place.name for d in new.days for a in d.activities}
    if before != after:
        out.append(f"Itinerary: +{len(after - before)} / -{len(before - after)} stops")
    if abs(prev.costs.total - new.costs.total) >= 1:
        out.append(f"Total: {money(prev.costs.total)} → {money(new.costs.total)}")
    return out


async def compile_node(state: PlannerState) -> dict:
    req: TripRequest = state["request"]
    profile = get_persona(req.persona)
    prev: Itinerary | None = state.get("itinerary")
    emit(AGENT, "working", "Compiling your unified itinerary...")

    flights, hotels = state.get("flights") or [], state.get("hotels") or []
    flight, hotel = (flights[0] if flights else None), (hotels[0] if hotels else None)
    days = [d.model_copy(deep=True) for d in state.get("days") or []]
    trim_notes = _reconcile_with_flights(
        days, flight.outbound.arrive if flight else None, flight.inbound.depart if flight and flight.inbound else None
    )

    party = req.adults + 0.5 * req.children
    costs = CostBreakdown(
        flights=round(flight.price, 2) if flight else 0.0,
        lodging=round(hotel.total_price, 2) if hotel else 0.0,
        activities=round(sum(a.place.est_cost_per_person for d in days for a in d.activities if a.kind == "activity") * party, 2),
        food=round(sum(a.place.est_cost_per_person for d in days for a in d.activities if a.kind == "meal") * party, 2),
        budget=req.budget,
        currency=(flight.currency if flight else hotel.currency if hotel else "INR"),
    )
    costs.total = round(costs.flights + costs.lodging + costs.activities + costs.food, 2)

    itinerary = Itinerary(
        request=req, destination_center=state["geo"].center if state.get("geo") else None,
        flight=flight, flight_alternatives=flights[1:6], hotel=hotel, hotel_alternatives=hotels[1:6],
        days=days, costs=costs, data_sources=dict(state.get("sources") or {}),
        version=(prev.version + 1) if prev else 1,
    )
    changes = _changes(prev, itinerary)
    tip = state.get("flight_tip", "")
    local_advice = seasonal_tips(req.destination, req.start_date)
    if flight and flight.mode == "train":
        local_advice.append("Book on IRCTC early - reservations open 60 days ahead and AC classes sell out fast; Tatkal quota opens a day before travel.")

    llm = get_llm()
    result = None
    if llm.available:
        emit(AGENT, "working", "Writing your trip summary with Claude...")
        digest = {
            "transport": flight and {"mode": flight.mode, "operator": _travel_label(flight), "price_inr": flight.price,
                                  "outbound": f"{flight.outbound.depart:%a %H:%M} → {flight.outbound.arrive:%a %H:%M}, {flight.outbound.stops} stop(s)",
                                  "why": flight.rationale},
            "hotel": hotel and {"name": hotel.name, "stars": hotel.stars, "rating": hotel.rating,
                                "estimated_fields": hotel.estimated, "address": hotel.address,
                                "per_night": hotel.price_per_night, "why": hotel.rationale},
            "days": [{"day": d.day, "theme": d.theme, "stops": [a.place.name for a in d.activities]} for d in days],
            "costs": costs.model_dump(), "changes_since_last_version": changes, "flexible_date_tip": tip,
            "schedule_adjustments": trim_notes, "local_advice": local_advice,
        }
        latest = (state.get("user_message") or "").strip()
        result = await llm.json(
            system=COMPILE_SYSTEM,
            prompt=(
                f"Persona: {profile.label} - tone: {profile.tone}.\n"
                f"Trip: {req.nights} nights in {req.destination} from {req.origin}, {req.adults} adult(s), "
                f"{req.children} child(ren), budget {money(req.budget)}.\n"
                f"{'Traveler just asked: ' + latest if state.get('is_refinement') else 'This is the first version of the plan.'}\n\n"
                f"Itinerary data (JSON):\n{json.dumps(digest, default=str, indent=1, ensure_ascii=False)}\n\n"
                "Return: `reply` - a 2-4 sentence chat message (for a refinement, lead with what changed and the cost impact; "
                "for a question, answer it); `summary` - a 2-3 sentence overview of the whole trip; "
                "`highlights` - 3-5 short bullet strings."
            ),
            schema=COMPILE_SCHEMA,
            effort="medium",
        )

    over = costs.total - costs.budget
    budget_line = (f"Estimated total {money(costs.total, costs.currency)} - "
                   + (f"{money(-over, costs.currency)} under budget." if over <= 0 else f"{money(over, costs.currency)} over budget."))
    if result:
        itinerary.summary = result.get("summary", "")
        itinerary.highlights = result.get("highlights", [])[:5]
        reply = result.get("reply", "")
    else:
        itinerary.summary = (
            f"A {profile.label.lower()} plan for {req.nights} nights in {req.destination}"
            + ((f", travelling by {_travel_label(flight)}" if flight.mode == "train" else f", flying {_travel_label(flight)}") if flight else "")
            + (f" and staying at {hotel.name}" if hotel else "") + f". {budget_line}"
        )
        prefs = state.get("prefs") or Preferences()
        itinerary.highlights = _fallback_highlights(
            flight, hotel, days, [*prefs.hotel.must_have, *profile.preferred_amenities]
        )
        if changes:
            lead = "Here's what changed: " + "; ".join(changes) + ". "
        elif state.get("is_refinement") and state.get("targets"):
            lead = "I searched again, but nothing better matched all your requirements, so your plan stays as it is. "
        else:
            lead = "Your itinerary is ready. "
        reply = lead + budget_line
    if tip:
        itinerary.highlights.append(tip)
    for advice in local_advice:
        if advice not in itinerary.highlights:
            itinerary.highlights.append(advice)

    emit_message(reply)
    emit(AGENT, "done", f"Itinerary v{itinerary.version} ready")
    return {"itinerary": itinerary, "history": [{"role": "assistant", "content": reply}]}
