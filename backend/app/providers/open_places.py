"""Real sights and restaurants without an API key.

Sights come from Wikipedia's geosearch: notable places with an article, exact
coordinates, a photo and a one-line description. A few searches around the
city centre (each limited to 10 km by the API) cover places on the outskirts,
such as Amber Fort outside Jaipur. Articles are kept only when their title or
description names something a visitor goes to (a fort, temple, museum, lake,
bazaar...). Popularity is how many Wikipedia language editions cover the place
(Wikidata sitelinks), blended with article length.

Restaurants and cafes come from OpenStreetMap through Nominatim. They share the
osm_hotels rate lock, so the 1 request/second policy holds across both.

What is real: names, coordinates, descriptions, photos and OSM diet tags.
What is estimated: ticket prices and restaurant price levels. Neither source has
guest ratings, so `rating` stays None and is never invented.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from urllib.parse import quote, quote_plus

import httpx

from ..geo import haversine_km, offset
from ..india import indian_city, is_indian
from ..models import GeoPoint, Place
from .demo import local_scale
from .osm_hotels import USER_AGENT, _address, _search

log = logging.getLogger(__name__)

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
CACHE_TTL = 6 * 3600
_cache: dict[str, tuple[float, list[Place]]] = {}

# Never a visitor attraction, whatever else the text says.
_EXCLUDE = re.compile(
    r"constituen|college|universit|school|institut|hospital|medical|railway station|metro station|bus (stand|station|terminal)|"
    r"airport|district|village|\btown\b|city in|capital of|suburb|neighbou?rhood|locality|\bward\b|tehsil|bombing|attack|riot|"
    r"organi[sz]ation|foundation|company|government|authority|department|police|court|election|princely state|kingdom|"
    r"dynasty|region|\briver\b|\broad\b|highway|hotel|\bclub\b|\bfilm\b|newspaper|residence|seat of|legislat|headquarters|"
    r"\boffice\b|\bbank\b|cricket ground|stadium|cemetery|census|team|association|hostel|prison|jail|power station|factory|"
    r"township|residential|\bship\b|vessel|housing|apartment|real estate|business park|tech park|\bit park|"
    r"software|campus|island off|building complex|commercial",
    re.I,
)

# (pattern, category, tags, minutes, price level, ticket in INR per person)
_RULES: list[tuple[re.Pattern, str, tuple[str, ...], int, int, float]] = [
    (re.compile(r"\b(zoo|aquarium|amusement|water ?park|theme park|planetarium|science (centre|center|city|museum))\b", re.I),
     "kids", ("kid-friendly", "interactive"), 150, 1, 150),
    (re.compile(r"\b(national park|wildlife|sanctuary|tiger reserve|safari)\b", re.I),
     "activity", ("wildlife", "nature", "kid-friendly"), 240, 2, 1500),
    (re.compile(r"\b(fort|fortress|citadel|garh|qila|killa)\b", re.I),
     "sight", ("heritage", "kid-friendly"), 150, 1, 200),
    (re.compile(r"\b(palace|mahal|haveli|vilas|niwas)\b", re.I),
     "sight", ("heritage", "kid-friendly"), 120, 1, 250),
    (re.compile(r"\b(museum|gallery|kala kendra|arts? cent(re|er)|cultural cent(re|er))\b", re.I),
     "culture", ("kid-friendly", "accessible"), 120, 1, 100),
    (re.compile(r"\bghats?\b", re.I),
     "sight", ("spiritual", "free", "evening"), 75, 0, 0),
    (re.compile(r"\b(temple|mandir|mosque|masjid|church|cathedral|basilica|gurd?u?wara|dargah|monastery|gompa|stupa|shrine|"
                r"synagogue|ashram|pagoda|derasar)\b", re.I),
     "culture", ("spiritual", "free"), 60, 0, 0),
    (re.compile(r"\b(observatory|jantar mantar|unesco|world heritage|monument|memorial|tomb|mausoleum|maqbara|gate|darwaza|"
                r"stepwell|baori|baoli|ruins|archaeolog|minar|chhatri|cenotaph|caves?|heritage|historic)\b", re.I),
     "sight", ("heritage",), 75, 1, 100),
    (re.compile(r"\b(garden|gardens|bagh|park|lake|sagar|talab|beach|waterfall|falls|hill|peak|viewpoint|botanical|valley|"
                r"island|dam|reservoir|forest|promenade|marine drive)\b", re.I),
     "nature", ("free", "kid-friendly", "walking"), 90, 0, 0),
    (re.compile(r"\b(skyscraper|landmark|observation deck|tower|arch|statue)\b", re.I),
     "sight", ("photography",), 60, 1, 0),
    (re.compile(r"\b(market|bazaar|bazar|haat|chowk|chaupar|square|street|mall)\b", re.I),
     "shopping", ("local", "free"), 90, 0, 0),
    (re.compile(r"\b(cinema|theatre|theater|auditorium|opera)\b", re.I),
     "culture", ("evening",), 150, 1, 300),
]

_INTL_CHAINS = ("mcdonald", "kfc", "domino", "pizza hut", "subway", "starbucks", "burger king", "dunkin", "costa coffee", "taco bell")
_PURE_VEG_NAMES = re.compile(
    r"\b(pure veg|vegetarian|veg|bhojanalaya|bhojnalaya|thali|udupi|udipi|saravana|bhavan|bhawan|haldiram|annapoorna|"
    r"rajdhani|mishthan|sweets|jain)\b", re.I,
)
_MEATY = re.compile(r"chicken|kebab|kabab|biryani|mughlai|mutton|meat|fish|seafood|prawn|grill|barbecue|bbq|tandoor|"
                    r"shawarma|steak|burger|sushi|momo|non[- ]?veg", re.I)
_CHEAP_NAMES = re.compile(r"\b(dhaba|chaat|chat|sweets|mishthan|tiffin|canteen|corner|stall|juice|lassi|tea|chai|kachori|bhojanalaya|bhojnalaya)\b", re.I)
_UPSCALE_NAMES = re.compile(r"\b(fine din(e|ing)|lounge|bistro|brasserie|grill|rooftop|terrace|kitchen & bar|bar & kitchen|steakhouse)\b", re.I)

_MEAL_COST = {1: 300, 2: 700, 3: 1600, 4: 4000}  # INR per person at an Indian-metro price level


def _wiki_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))


def _classify(title: str, desc: str) -> tuple[str, tuple[str, ...], int, int, float] | None:
    if _EXCLUDE.search(desc) or _EXCLUDE.search(title):
        return None
    if re.search(r"train station|terminal", desc, re.I) and not re.search(r"historic|heritage|unesco", desc, re.I):
        return None  # keep CSMT ("Historic terminal train station"), skip ordinary stations
    if re.search(r"shopping|\bmall\b", desc, re.I):  # "World Trade Park": a mall, not a park
        return "shopping", ("local", "kid-friendly"), 90, 1, 0
    for text in (title, desc):  # the title is the stronger signal ("City Palace" / "Building in Jaipur")
        for pattern, cat, tags, minutes, level, ticket in _RULES:
            if pattern.search(text):
                return cat, tags, minutes, level, ticket
    return None


async def _wiki_get(client: httpx.AsyncClient, params: dict) -> dict:
    r = await client.get(WIKI_API, params={"action": "query", "format": "json", "formatversion": 2, **params})
    r.raise_for_status()
    return r.json()


async def _sitelinks(client: httpx.AsyncClient, qids: list[str]) -> dict[str, int]:
    """How many Wikipedia language editions cover each Wikidata item: a good proxy for fame."""
    out: dict[str, int] = {}
    for res in await asyncio.gather(*(
        client.get(WIKIDATA_API, params={"action": "wbgetentities", "format": "json", "props": "sitelinks", "ids": "|".join(qids[i:i + 50])})
        for i in range(0, len(qids), 50)
    ), return_exceptions=True):
        if isinstance(res, BaseException) or res.status_code != 200:
            log.info("wikidata sitelinks failed: %s", res)
            continue
        for q, ent in res.json().get("entities", {}).items():
            out[q] = sum(1 for site in ent.get("sitelinks", {}) if site.endswith("wiki") and site not in ("commonswiki", "specieswiki"))
    return out


async def _wiki_sights(client: httpx.AsyncClient, city: str, center: GeoPoint) -> list[Place]:
    # The centre plus four points ~9 km out: 10 km circles covering ~38 km across. Metros sprawl
    # further (South Mumbai's sights are ~17 km from the city centroid), so add a second ring.
    ring = [(9, 0), (-9, 0), (0, 9), (0, -9)]
    ic = indian_city(city)
    if ic and ic.region == "metro":
        ring += [(18, 0), (-18, 0), (0, 18), (0, -18)]
    probes = [center] + [offset(center, n, e) for n, e in ring]
    found: dict[int, dict] = {}
    for res in await asyncio.gather(*(
        _wiki_get(client, {"list": "geosearch", "gscoord": f"{p.lat}|{p.lng}", "gsradius": 10000, "gslimit": 120, "gsnamespace": 0})
        for p in probes
    ), return_exceptions=True):
        if isinstance(res, BaseException):
            log.info("wikipedia geosearch failed: %s", res)
            continue
        for g in res.get("query", {}).get("geosearch", []):
            found.setdefault(g["pageid"], g)
    if not found:
        return []

    ids = list(found)
    details: dict[int, dict] = {}
    for res in await asyncio.gather(*(
        _wiki_get(client, {"pageids": "|".join(map(str, ids[i:i + 50])), "prop": "description|pageimages|info|pageprops", "ppprop": "wikibase_item",
                           "piprop": "thumbnail", "pithumbsize": 960, "pilimit": 50})
        for i in range(0, len(ids), 50)
    ), return_exceptions=True):
        if isinstance(res, BaseException):
            log.info("wikipedia details failed: %s", res)
            continue
        for p in res.get("query", {}).get("pages", []):
            details[p["pageid"]] = p

    kinds = {pid: k for pid, g in found.items() if (k := _classify(g["title"], details.get(pid, {}).get("description", "")))}
    qid = {pid: (details.get(pid, {}).get("pageprops") or {}).get("wikibase_item", "") for pid in kinds}
    sitelinks = await _sitelinks(client, [q for q in qid.values() if q])

    scale = 1.0 if is_indian(city) else local_scale(city)
    places: list[Place] = []
    for pid, (cat, tags, minutes, level, ticket) in kinds.items():
        g, d = found[pid], details.get(pid, {})
        title, desc = g["title"], d.get("description", "")
        length = min(1.0, max(0.0, (math.log10(max(d.get("length", 0), 1)) - 3) / 2))  # 1k chars -> 0, 100k -> 1
        reach = min(1.0, math.log1p(sitelinks.get(qid[pid], 0)) / math.log1p(40))  # in ~40 languages -> 1
        popularity = round(0.75 * reach + 0.25 * length if sitelinks else length, 3)
        name = re.sub(r",\s*[^,]+$", "", title) if "," in title else title  # "City Palace, Jaipur" -> "City Palace"
        name = re.sub(r"\s*\([^)]*\)$", "", name)
        places.append(Place(
            id=f"wiki-{pid}", name=name, category=cat, location=GeoPoint(lat=g["lat"], lng=g["lon"]),
            rating=None, popularity=popularity, price_level=level, est_cost_per_person=round(ticket * scale, -1),
            duration_min=minutes, description=desc, url=_wiki_url(title),
            image_url=(d.get("thumbnail") or {}).get("source", ""), source="wikipedia", tags=list(tags),
        ))

    # Drop near-duplicates ("Jantar Mantar" vs "Jantar Mantar, Jaipur"): keep the more popular one.
    places.sort(key=lambda p: p.popularity, reverse=True)
    kept: list[Place] = []
    for p in places:
        # Same name, or practically the same spot (City Palace and Jantar Mantar are 140 m apart, both kept).
        if any(haversine_km(p.location, k.location) < 0.04 or p.name.lower() == k.name.lower() for k in kept):
            continue
        kept.append(p)
    return kept


def _restaurant(item: dict, city: str, scale: float, india: bool) -> Place | None:
    name = (item.get("namedetails") or {}).get("name:en") or item.get("name") or ""
    kind = item.get("type", "")
    if not name or kind not in ("restaurant", "cafe", "fast_food", "food_court", "ice_cream"):
        return None
    low = name.lower()
    if low in ("restaurant", "cafe", "dhaba", "hotel") or any(c in low for c in _INTL_CHAINS):
        return None
    extra = item.get("extratags") or {}
    cuisine = (extra.get("cuisine") or "").lower()
    tags: list[str] = []
    veg = extra.get("diet:vegetarian", "")
    non_veg = re.search(r"non[ -]?veg", low) or veg == "no"
    if not non_veg and (veg == "only" or extra.get("diet:vegan") == "only" or _PURE_VEG_NAMES.search(name) or "vegetarian" in cuisine):
        tags += ["pure-veg", "vegetarian"]
    elif veg in ("yes", "only") or kind == "cafe" or (india and (not cuisine or re.search(r"indian|regional|rajasthani|gujarati|punjabi|thali|chaat", cuisine))):
        tags.append("vegetarian")  # Indian kitchens always have vegetarian dishes
    if extra.get("diet:jain") in ("yes", "only") or "jain" in low:
        tags.append("jain")
    if "pure-veg" not in tags and (non_veg or _MEATY.search(cuisine) or _MEATY.search(name)):
        tags.append("non-veg")
    if kind in ("cafe", "ice_cream"):
        tags += ["daytime", "quick", "kid-friendly"]
    if kind == "fast_food":
        tags += ["quick", "local"]
    if "rooftop" in low or "terrace" in low:
        tags.append("rooftop")
    if india and re.search(r"rajasthani|regional|gujarati|bengali|kerala|goan|chettinad|thali|chaat|south_indian", cuisine):
        tags.append("local")

    if "fine_dining" in cuisine:
        level = 4
    elif _UPSCALE_NAMES.search(name):
        level = 3
    elif kind in ("fast_food", "ice_cream") or _CHEAP_NAMES.search(name):
        level = 1
    elif kind == "cafe":
        level = 2 if not india else 1
    else:
        level = 2
    lat, lng = float(item["lat"]), float(item["lon"])
    website = extra.get("website") or extra.get("contact:website") or ""
    return Place(
        id=f"osm-{item.get('osm_type', 'x')[:1]}{item.get('osm_id')}", name=name, category="food",
        location=GeoPoint(lat=lat, lng=lng), rating=None, price_level=level,
        est_cost_per_person=round(_MEAL_COST[level] * scale, -1), duration_min=45 if "quick" in tags else 75,
        address=_address(item.get("address") or {}) or city,
        description=(cuisine.replace("_", " ").replace(";", ", ").capitalize() + " cuisine") if cuisine else "",
        url=website or f"https://www.google.com/maps/search/?api=1&query={quote_plus(f'{name} {lat},{lng}')}",
        source="openstreetmap", tags=list(dict.fromkeys(tags)),
    )


async def _osm_restaurants(client: httpx.AsyncClient, city: str, center: GeoPoint) -> list[Place]:
    india = is_indian(city)
    scale = local_scale(city)
    out: dict[str, Place] = {}
    # The diet-specific searches surface pure-veg kitchens that the generic ones miss.
    phrases = ("restaurant", "cafe", "fast food", "vegetarian restaurant") + (("bhojnalaya",) if india else ())
    for phrase in phrases:
        try:
            items = await _search(client, phrase, center)
        except Exception as exc:  # noqa: BLE001 - one failed phrase shouldn't lose the rest
            log.info("nominatim %r failed: %s", phrase, exc)
            continue
        for item in items:
            p = _restaurant(item, city, scale, india)
            if p and p.name.lower() not in out:
                out[p.name.lower()] = p
    return list(out.values())


async def search_open_places(city: str, center: GeoPoint, timeout: float = 25) -> list[Place]:
    """Real sights (Wikipedia) and restaurants (OpenStreetMap) around `center`, cached per city."""
    key = f"{city.lower()}|{center.lat:.3f},{center.lng:.3f}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return [p.model_copy(deep=True) for p in hit[1]]
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        sights, foods = await asyncio.gather(
            _wiki_sights(client, city, center), _osm_restaurants(client, city, center), return_exceptions=True,
        )
    places: list[Place] = []
    for name, res in (("wikipedia", sights), ("openstreetmap", foods)):
        if isinstance(res, BaseException):
            log.warning("%s places failed: %s", name, res)
        else:
            places += res
    if places:
        _cache[key] = (time.time(), places)
    return [p.model_copy(deep=True) for p in places]
