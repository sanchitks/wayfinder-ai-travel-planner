"""Experience Agent: builds the day-by-day plan.

Pipeline: fetch places -> persona/interest scoring -> pick the right number of
activities -> k-means them into one geographic cluster per day (balanced) ->
route each day nearest-neighbor -> slot meals near each day's cluster ->
Claude writes day themes and tips.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta

from ..config import get_settings
from ..geo import compass_label, haversine_km, kmeans, nearest_neighbor_order
from ..india import INDIA_CONTEXT
from ..llm import INT, STR, arr, get_llm, obj
from ..models import DayPlan, GeoPoint, Place, ScheduledActivity, TripRequest
from ..personas import PersonaProfile, get_persona
from ..providers.places import search_places
from .state import ExperiencePrefs, PlannerState, emit

AGENT = "experience"

INTEREST_MAP: dict[str, tuple[set[str], set[str]]] = {
    # interest keyword -> (categories, tags)
    "food": ({"food", "activity"}, {"local"}),
    "museum": ({"culture"}, set()),
    "art": ({"culture"}, set()),
    "history": ({"culture", "sight"}, set()),
    "culture": ({"culture"}, set()),
    "nature": ({"nature"}, set()),
    "hiking": ({"nature"}, {"walking"}),
    "outdoor": ({"nature", "activity"}, set()),
    "beach": ({"nature"}, set()),
    "nightlife": ({"nightlife"}, {"evening"}),
    "shopping": ({"shopping"}, set()),
    "wellness": ({"wellness"}, set()),
    "spa": ({"wellness"}, set()),
    "adventure": ({"activity", "nature"}, set()),
    "kids": ({"kids"}, {"kid-friendly"}),
    "family": ({"kids"}, {"kid-friendly"}),
    "photography": ({"sight", "nature"}, set()),
    "architecture": ({"sight"}, {"heritage"}),
    "heritage": ({"sight", "culture"}, {"heritage"}),
    "temple": ({"culture"}, {"spiritual"}),
    "spiritual": ({"culture", "wellness"}, {"spiritual"}),
    "mountain": ({"nature", "activity"}, {"mountain"}),
    "wildlife": ({"nature", "activity", "kids"}, {"wildlife"}),
    "yoga": ({"wellness"}, set()),
    "bazaar": ({"shopping"}, {"local"}),
    "ayurved": ({"wellness"}, set()),
    "ghat": ({"sight", "culture"}, {"spiritual"}),
}

# Dietary needs that restrict which restaurants may be used at all.
STRICT_DIET = {
    "jain": {"jain"},
    "pure veg": {"pure-veg", "jain"},
    "vegan": {"pure-veg"},
    "vegetarian": {"vegetarian", "pure-veg", "jain"},
}

SYSTEM = (
    "You are the Experience Agent in a multi-agent travel planner. Activities are already chosen and "
    "geographically clustered into days. Give each day a short evocative theme (max 6 words) and one "
    "practical, specific tip per activity (max 20 words) written in the persona's tone - e.g. timings "
    "that beat heat and crowds, dress codes at temples, what to order. Never invent new places. "
    + INDIA_CONTEXT
)

THEME_SCHEMA = obj({
    "days": arr(obj({
        "day": INT,
        "theme": STR,
        "tips": arr(obj({"name": STR, "tip": STR})),
    })),
})


def _interest_hits(place: Place, interests: list[str]) -> int:
    hits = 0
    for raw in interests:
        key = raw.lower()
        for word, (cats, tags) in INTEREST_MAP.items():
            if word in key and (place.category in cats or tags & set(place.tags)):
                hits += 1
                break
        else:
            if key and key in place.name.lower():
                hits += 1
    return hits


def score_places(places: list[Place], req: TripRequest, profile: PersonaProfile, prefs: ExperiencePrefs) -> list[Place]:
    avoid = [a.lower() for a in prefs.avoid]
    excluded_names = {n.lower() for n in prefs.exclude_names}
    interests = [*req.interests, *prefs.add_interests]
    # An explicit interest overrides a persona exclusion (e.g. a family that asks for nightlife).
    interest_cats = {c for i in interests for w, (cats, _) in INTEREST_MAP.items() if w in i.lower() for c in cats}
    kept: list[Place] = []
    for p in places:
        if p.category in profile.excluded_categories and p.category not in interest_cats:
            continue
        if p.name.lower() in excluded_names:
            continue
        if any(a in p.category or a in p.name.lower() or a in " ".join(p.tags) for a in avoid):
            continue
        if p.category != "food" and p.price_level > profile.max_price_level:
            continue
        if profile.key == "family" and p.category not in ("food",) and "kid-friendly" not in p.tags and p.category != "kids":
            if p.category not in ("nature", "sight"):
                continue
        if p.rating is None:  # Wikipedia / OSM: notability stands in for the missing rating
            rating, popularity = 0.35 + 0.5 * p.popularity, p.popularity
        else:
            rating = max(0.0, (p.rating - 3.5) / 1.5)
            popularity = min(1.0, math.log10(max(10, p.review_count)) / 4.5)
        favored = 1.0 if p.category in profile.favored_categories else 0.0
        tag_bonus = min(1.0, len(set(p.tags) & set(profile.favored_tags)) / 2)
        interest = min(1.0, _interest_hits(p, interests) / 1.0)
        price_fit = 1.0
        if profile.key == "budget":
            price_fit = 1.0 if p.price_level == 0 else 0.6 if p.price_level == 1 else 0.2
        elif profile.key == "luxury":
            price_fit = 0.5 + 0.125 * p.price_level
        if p.category == "food" and prefs.dietary:
            tag_text = " ".join(p.tags).replace("-", " ")
            wanted = [d.lower().replace("-", " ") for d in prefs.dietary]
            if any(d in tag_text or d in p.name.lower() for d in wanted):
                interest = 1.0
        p.score = round(0.25 * rating + 0.1 * popularity + 0.2 * favored + 0.15 * tag_bonus + 0.2 * interest + 0.1 * price_fit, 4)
        kept.append(p)
    kept.sort(key=lambda p: p.score, reverse=True)
    return kept


def _diverse_pick(places: list[Place], n: int) -> list[Place]:
    """Top-n by score with at most ~40% from any single category."""
    cap = max(1, math.ceil(n * 0.4))
    counts: dict[str, int] = {}
    picked: list[Place] = []
    for p in places:
        if len(picked) >= n:
            break
        if counts.get(p.category, 0) < cap:
            picked.append(p)
            counts[p.category] = counts.get(p.category, 0) + 1
    for p in places:  # top up if the cap was too strict
        if len(picked) >= n:
            break
        if p not in picked:
            picked.append(p)
    return picked


def _cluster_days(acts: list[Place], capacities: list[int]) -> list[list[Place]]:
    """Balanced geographic clustering: one cluster per day, sized to capacity."""
    days = len(capacities)
    if not acts:
        return [[] for _ in range(days)]
    centers = kmeans([p.location for p in acts], days)
    while len(centers) < days:
        centers.append(centers[-1])
    cap_each = max(capacities)
    groups: list[list[Place]] = [[] for _ in centers]
    # Most "decided" places first: those much closer to one center than any other.
    def margin(p: Place) -> float:
        d = sorted(haversine_km(p.location, c) for c in centers)
        return (d[1] - d[0]) if len(d) > 1 else 0.0

    for p in sorted(acts, key=margin, reverse=True):
        for idx in sorted(range(len(centers)), key=lambda i: haversine_km(p.location, centers[i])):
            if len(groups[idx]) < cap_each:
                groups[idx].append(p)
                break
    # Light days (arrival/departure) get the smallest clusters, and of those the weakest, so a
    # must-see like Amber Fort isn't parked on a departure day that the train or flight cuts short.
    order = sorted(range(len(groups)), key=lambda i: (len(groups[i]), max((p.score for p in groups[i]), default=0.0)))
    light_days = [i for i, c in enumerate(capacities) if c < cap_each][::-1]  # departure day first: it's trimmed most
    full_days = [i for i, c in enumerate(capacities) if c >= cap_each]
    result: list[list[Place]] = [[] for _ in range(days)]
    for day_idx, group_idx in zip(light_days + full_days, order):
        group = sorted(groups[group_idx], key=lambda p: p.score, reverse=True)[: capacities[day_idx]]
        result[day_idx] = group
    return result


def _t(hhmm: str) -> datetime:
    return datetime.strptime(hhmm, "%H:%M")


def _travel_minutes(a: GeoPoint, b: GeoPoint) -> int:
    km = haversine_km(a, b)
    return int(max(10, round(km / 14 * 60 / 5) * 5))  # ~14 km/h door-to-door in a city


def _pick_meal(foods: list[Place], near: GeoPoint, used: set[str], profile: PersonaProfile, kind: str) -> Place | None:
    lo, hi = profile.min_price_level, profile.max_price_level
    if profile.key == "luxury" and kind == "dinner":
        lo = 3
    if profile.key == "luxury" and kind == "lunch":
        lo = 2
    if kind == "dinner":  # tiffin centres and bakeries are lunch spots
        foods = [f for f in foods if "daytime" not in f.tags] or foods
    candidates = (
        [f for f in foods if f.id not in used and lo <= f.price_level <= hi]
        or [f for f in foods if f.id not in used]
        or [f for f in foods if lo <= f.price_level <= hi]  # short list (e.g. Jain only): revisit a favourite
        or foods
    )
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.score - 0.08 * haversine_km(near, f.location))


def build_day(
    day_no: int, day_date, acts: list[Place], foods: list[Place], used_food: set[str], profile: PersonaProfile,
    center: GeoPoint, start_override: str | None = None, include_lunch: bool = True,
) -> DayPlan:
    day_center = GeoPoint(lat=sum(a.location.lat for a in acts) / len(acts), lng=sum(a.location.lng for a in acts) / len(acts)) if acts else center
    evening = [a for a in acts if a.category == "nightlife"]
    daytime = nearest_neighbor_order(day_center, [a for a in acts if a.category != "nightlife"], key=lambda a: a.location)
    # Evening-only experiences (aarti, sunset points, light shows) go last, just before dinner.
    daytime = [a for a in daytime if "evening" not in a.tags] + [a for a in daytime if "evening" in a.tags]

    schedule: list[ScheduledActivity] = []
    t = _t(start_override or profile.day_start)
    lunch_t, dinner_t = _t(profile.lunch_at), _t(profile.dinner_at)
    pos: GeoPoint | None = None
    lunch_done = not include_lunch or t >= lunch_t + timedelta(hours=1)
    km = 0.0

    def place(p: Place, start: datetime, kind: str = "activity") -> datetime:
        nonlocal pos, km
        end = start + timedelta(minutes=p.duration_min)
        schedule.append(ScheduledActivity(place=p, start=start.strftime("%H:%M"), end=end.strftime("%H:%M"), kind=kind))
        if pos is not None:
            km += haversine_km(pos, p.location)
        pos = p.location
        return end

    for act in daytime:
        if not lunch_done and t + timedelta(minutes=act.duration_min // 2) >= lunch_t:
            meal = _pick_meal(foods, pos or day_center, used_food, profile, "lunch")
            if meal:
                used_food.add(meal.id)
                t = place(meal, max(t, lunch_t - timedelta(minutes=30)), "meal") + timedelta(minutes=_travel_minutes(meal.location, act.location))
            lunch_done = True
        if pos is not None:
            t += timedelta(minutes=_travel_minutes(pos, act.location))
        t = place(act, t)
    if not lunch_done and t <= lunch_t + timedelta(hours=1) and profile.key != "business":
        meal = _pick_meal(foods, pos or day_center, used_food, profile, "lunch")
        if meal:
            used_food.add(meal.id)
            t = place(meal, max(t, lunch_t), "meal")
    dinner = _pick_meal(foods, pos or day_center, used_food, profile, "dinner")
    if dinner:
        used_food.add(dinner.id)
        travel = _travel_minutes(pos, dinner.location) if pos else 0
        t = place(dinner, max(t + timedelta(minutes=travel), dinner_t), "meal")
    for night in evening:
        t = place(night, t + timedelta(minutes=_travel_minutes(pos, night.location) if pos else 0))

    return DayPlan(
        day=day_no, date=day_date, area=compass_label(center, day_center), activities=schedule,
        travel_km=round(km, 1), center=day_center,
    )


async def experience_node(state: PlannerState) -> dict:
    req = state["request"]
    profile = get_persona(req.persona)
    prefs = state["prefs"].experience
    geo = state["geo"]

    emit(AGENT, "working", f"Discovering experiences and dining in {req.destination}...")
    try:
        places, source = await search_places(get_settings(), city=req.destination, center=geo.center)
        emit(AGENT, "working", f"Scoring {len(places)} places from {source} for {profile.label.lower()} interests...")
        scored = score_places(places, req, profile, prefs)
        foods = [p for p in scored if p.category == "food"]
        acts = [p for p in scored if p.category != "food"]
        for diet in prefs.dietary:
            if diet.lower().replace("-", " ").startswith("non veg"):
                # Pure-veg and Jain kitchens serve no meat; skip them when there's enough else to choose from.
                meaty = [f for f in foods if not {"pure-veg", "jain"} & set(f.tags)]
                known = [f for f in meaty if "non-veg" in f.tags]  # kebab, biryani, seafood, grill...
                if len(known) >= 3:
                    meaty = known
                if len(meaty) >= 3:
                    foods = meaty
                    emit(AGENT, "working", f"Choosing restaurants with non-veg dishes ({len(meaty)} found)")
                continue
            allowed = STRICT_DIET.get(diet.lower())
            matching = [f for f in foods if allowed and allowed & set(f.tags)]
            if diet.lower() == "jain" and len(matching) < 3:
                # Open data rarely tags Jain kitchens; pure-veg ones usually cook Jain food on request.
                matching = [f for f in foods if "pure-veg" in f.tags]
                for f in matching:
                    if "jain" not in f.tags:
                        f.tags.append("jain-on-request")
            if diet.lower() == "pure veg" and len(matching) < 3:
                # Too few confirmed all-veg kitchens: add places with vegetarian dishes, labelled as such.
                for f in foods:
                    if "vegetarian" in f.tags and "pure-veg" not in f.tags and f not in matching:
                        f.tags.append("veg-options")
                        matching.append(f)
            if allowed and len(matching) >= 3:
                foods = matching
                emit(AGENT, "working", f"Restricting meals to {diet} restaurants ({len(matching)} found)")

        n_days = req.nights + 1
        per_day = profile.activities_per_day + {"relaxed": -1, "packed": 1}.get(prefs.pace or "", 0)
        per_day = max(1, per_day)
        light = max(1, per_day // 2)
        capacities = [light] + [per_day] * max(0, n_days - 2) + ([light] if n_days > 1 else [])
        chosen = _diverse_pick(acts, sum(capacities))
        emit(AGENT, "working", f"Clustering {len(chosen)} activities into {n_days} walkable day(s)...")
        groups = _cluster_days(chosen, capacities)

        used_food: set[str] = set()
        days: list[DayPlan] = []
        for i, group in enumerate(groups):
            first, last = i == 0, i == n_days - 1
            start = None
            if first and profile.key != "business":
                start = max(profile.day_start, "15:00")
            days.append(build_day(
                i + 1, req.start_date + timedelta(days=i), group, foods, used_food, profile, geo.center,
                start_override=start, include_lunch=not first,
            ))
            if last and n_days > 1:
                # Departure day: keep only the morning.
                days[-1].activities = [a for a in days[-1].activities if a.start < "13:00"] or days[-1].activities[:1]

        llm = get_llm()
        result = None
        if llm.available:
            emit(AGENT, "working", "Writing day themes and local tips with Claude...")
            outline = [
                {"day": d.day, "date": d.date.isoformat(), "area": d.area,
                 "items": [{"name": a.place.name, "category": a.place.category, "time": a.start} for a in d.activities]}
                for d in days
            ]
            result = await llm.json(
                system=SYSTEM,
                prompt=(
                    f"Destination: {req.destination}. Persona: {profile.label} (tone: {profile.tone}).\n"
                    f"Party: {req.adults} adult(s), {req.children} child(ren). Interests: {', '.join(req.interests) or 'general'}.\n"
                    f"Dietary: {', '.join(prefs.dietary) or 'none'}. Notes: {req.notes or 'none'}\n\n"
                    f"Day outline (JSON):\n{json.dumps(outline, indent=1, ensure_ascii=False)}"
                ),
                schema=THEME_SCHEMA,
                effort="low",
            )
        by_day = {d.get("day"): d for d in (result or {}).get("days", [])}
        for d in days:
            info = by_day.get(d.day)
            if info:
                d.theme = info.get("theme", "")
                tips = {t.get("name", "").lower(): t.get("tip", "") for t in info.get("tips", [])}
                for a in d.activities:
                    a.note = tips.get(a.place.name.lower(), "")
            if not d.theme:
                cats = [a.place.category for a in d.activities if a.kind == "activity"]
                top = max(set(cats), key=cats.count) if cats else "food"
                label = {"sight": "Landmarks", "culture": "Museums & Culture", "nature": "Parks & Outdoors", "kids": "Family Fun",
                         "activity": "Hands-on Experiences", "nightlife": "Night Out", "wellness": "Slow & Restorative",
                         "shopping": "Markets & Shopping", "food": "Arrival & Dinner"}[top]
                d.theme = f"{label} · {d.area}"
            for a in d.activities:
                if "jain-on-request" in a.place.tags:
                    a.note = "Pure-veg kitchen: ask for Jain food (no onion, garlic or root vegetables). " + a.note
                elif "veg-options" in a.place.tags:
                    a.note = "Has vegetarian dishes but isn't confirmed as an all-veg kitchen. " + a.note

        total_acts = sum(1 for d in days for a in d.activities if a.kind == "activity")
        emit(AGENT, "done", f"Built {n_days} day(s) with {total_acts} activities, clustered by neighborhood")
        return {"days": days, "sources": {"experiences": source}}
    except Exception as exc:
        emit(AGENT, "error", f"Itinerary building failed: {exc}")
        return {"errors": [f"experience: {exc}"]}
