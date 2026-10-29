"""Geography helpers: geocoding, distances, and the clustering the Experience
agent uses to group activities into walkable days."""

from __future__ import annotations

import logging
import math
import random

import httpx

from .india import indian_city, venue_point
from .models import GeoPoint

log = logging.getLogger(__name__)

# name -> (lat, lng, primary IATA city/airport code, country)
CITIES: dict[str, tuple[float, float, str, str]] = {
    "amsterdam": (52.3676, 4.9041, "AMS", "Netherlands"),
    "athens": (37.9838, 23.7275, "ATH", "Greece"),
    "atlanta": (33.7490, -84.3880, "ATL", "United States"),
    "bangkok": (13.7563, 100.5018, "BKK", "Thailand"),
    "barcelona": (41.3874, 2.1686, "BCN", "Spain"),
    "bengaluru": (12.9716, 77.5946, "BLR", "India"),
    "bangalore": (12.9716, 77.5946, "BLR", "India"),
    "berlin": (52.5200, 13.4050, "BER", "Germany"),
    "boston": (42.3601, -71.0589, "BOS", "United States"),
    "buenos aires": (-34.6037, -58.3816, "EZE", "Argentina"),
    "cape town": (-33.9249, 18.4241, "CPT", "South Africa"),
    "chicago": (41.8781, -87.6298, "CHI", "United States"),
    "copenhagen": (55.6761, 12.5683, "CPH", "Denmark"),
    "delhi": (28.6139, 77.2090, "DEL", "India"),
    "new delhi": (28.6139, 77.2090, "DEL", "India"),
    "dubai": (25.2048, 55.2708, "DXB", "United Arab Emirates"),
    "dublin": (53.3498, -6.2603, "DUB", "Ireland"),
    "goa": (15.2993, 74.1240, "GOI", "India"),
    "hong kong": (22.3193, 114.1694, "HKG", "Hong Kong"),
    "istanbul": (41.0082, 28.9784, "IST", "Turkey"),
    "jaipur": (26.9124, 75.7873, "JAI", "India"),
    "kyoto": (35.0116, 135.7681, "KIX", "Japan"),
    "lisbon": (38.7223, -9.1393, "LIS", "Portugal"),
    "london": (51.5074, -0.1278, "LON", "United Kingdom"),
    "los angeles": (34.0522, -118.2437, "LAX", "United States"),
    "madrid": (40.4168, -3.7038, "MAD", "Spain"),
    "mexico city": (19.4326, -99.1332, "MEX", "Mexico"),
    "miami": (25.7617, -80.1918, "MIA", "United States"),
    "milan": (45.4642, 9.1900, "MIL", "Italy"),
    "mumbai": (19.0760, 72.8777, "BOM", "India"),
    "new york": (40.7128, -74.0060, "NYC", "United States"),
    "orlando": (28.5384, -81.3789, "ORL", "United States"),
    "paris": (48.8566, 2.3522, "PAR", "France"),
    "prague": (50.0755, 14.4378, "PRG", "Czechia"),
    "reykjavik": (64.1466, -21.9426, "REK", "Iceland"),
    "rome": (41.9028, 12.4964, "ROM", "Italy"),
    "san francisco": (37.7749, -122.4194, "SFO", "United States"),
    "seattle": (47.6062, -122.3321, "SEA", "United States"),
    "seoul": (37.5665, 126.9780, "SEL", "South Korea"),
    "singapore": (1.3521, 103.8198, "SIN", "Singapore"),
    "sydney": (-33.8688, 151.2093, "SYD", "Australia"),
    "tokyo": (35.6762, 139.6503, "TYO", "Japan"),
    "toronto": (43.6532, -79.3832, "YTO", "Canada"),
    "vancouver": (49.2827, -123.1207, "YVR", "Canada"),
    "vienna": (48.2082, 16.3738, "VIE", "Austria"),
    "zurich": (47.3769, 8.5417, "ZRH", "Switzerland"),
}


def _norm(name: str) -> str:
    return name.split(",")[0].strip().lower()


def city_info(name: str) -> tuple[float, float, str, str] | None:
    ic = indian_city(name)
    if ic:
        return (ic.lat, ic.lng, ic.airport, "India")
    return CITIES.get(_norm(name))


def guess_iata(name: str) -> str:
    raw = name.strip()
    info = city_info(name)  # first: "Goa" is a city (GOI), not airport code GOA (Genova)
    if info:
        return info[2]
    if len(raw) == 3 and raw.isalpha():
        return raw.upper()
    letters = "".join(ch for ch in _norm(name) if ch.isalpha())
    return (letters[:3] or "XXX").upper()


_geocode_cache: dict[str, GeoPoint | None] = {}


async def geocode(query: str, timeout: float = 8.0) -> GeoPoint | None:
    """Known-city table first, then OpenStreetMap Nominatim (free, no key)."""
    venue = venue_point(query)
    if venue:
        return GeoPoint(lat=venue[0], lng=venue[1])
    info = city_info(query)
    if info:
        return GeoPoint(lat=info[0], lng=info[1])
    key = query.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]
    point: GeoPoint | None = None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1},
                headers={"User-Agent": "Wayfinder-Travel-Planner/1.0 (demo)"},
            )
            r.raise_for_status()
            rows = r.json()
            if rows:
                point = GeoPoint(lat=float(rows[0]["lat"]), lng=float(rows[0]["lon"]))
    except Exception as exc:  # network is optional
        log.info("geocode failed for %s: %s", query, exc)
    _geocode_cache[key] = point
    return point


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    r = 6371.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def offset(center: GeoPoint, km_north: float, km_east: float) -> GeoPoint:
    lat = center.lat + km_north / 110.574
    lng = center.lng + km_east / (111.320 * max(0.2, math.cos(math.radians(center.lat))))
    return GeoPoint(lat=round(lat, 6), lng=round(lng, 6))


def centroid(points: list[GeoPoint]) -> GeoPoint:
    return GeoPoint(lat=sum(p.lat for p in points) / len(points), lng=sum(p.lng for p in points) / len(points))


def kmeans(points: list[GeoPoint], k: int, seed: int = 7, iterations: int = 25) -> list[GeoPoint]:
    """Plain k-means on lat/lng (fine at city scale). Returns k centroids."""
    if not points:
        return []
    k = max(1, min(k, len(points)))
    rng = random.Random(seed)
    # k-means++ initialization for stable, spread-out clusters
    centers = [rng.choice(points)]
    while len(centers) < k:
        d2 = [min(haversine_km(p, c) ** 2 for c in centers) for p in points]
        total = sum(d2) or 1.0
        pick, acc = rng.random() * total, 0.0
        for p, d in zip(points, d2):
            acc += d
            if acc >= pick:
                centers.append(p)
                break
        else:
            centers.append(points[-1])
    for _ in range(iterations):
        groups: list[list[GeoPoint]] = [[] for _ in centers]
        for p in points:
            idx = min(range(len(centers)), key=lambda i: haversine_km(p, centers[i]))
            groups[idx].append(p)
        new_centers = [centroid(g) if g else centers[i] for i, g in enumerate(groups)]
        if all(haversine_km(a, b) < 0.01 for a, b in zip(centers, new_centers)):
            break
        centers = new_centers
    return centers


def nearest_neighbor_order(start: GeoPoint, items: list, key=lambda x: x) -> list:
    """Greedy route through items starting nearest to `start`."""
    remaining = list(items)
    ordered = []
    cur = start
    while remaining:
        nxt = min(remaining, key=lambda it: haversine_km(cur, key(it)))
        ordered.append(nxt)
        remaining.remove(nxt)
        cur = key(nxt)
    return ordered


def compass_label(center: GeoPoint, point: GeoPoint) -> str:
    dist = haversine_km(center, point)
    if dist < 1.2:
        return "City Center"
    angle = math.degrees(math.atan2(point.lat - center.lat, (point.lng - center.lng) * math.cos(math.radians(center.lat))))
    dirs = ["East", "Northeast", "North", "Northwest", "West", "Southwest", "South", "Southeast"]
    return f"{dirs[int(((angle + 360 + 22.5) % 360) // 45)]} Side"
