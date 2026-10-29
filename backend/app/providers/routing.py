"""Road routes for the map, from OSRM over OpenStreetMap roads (no API key).

Primary: the FOSSGIS servers at routing.openstreetmap.de (car and foot profiles).
Fallback for driving: the OSRM project's demo server. Both are free community
services, so results are cached and at most two requests run at once.
Durations assume free-flowing traffic.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from ..models import GeoPoint
from .osm_hotels import USER_AGENT

log = logging.getLogger(__name__)

SERVERS = {
    "driving": ["https://routing.openstreetmap.de/routed-car/route/v1/driving/", "https://router.project-osrm.org/route/v1/driving/"],
    "walking": ["https://routing.openstreetmap.de/routed-foot/route/v1/foot/"],
}
MAX_POINTS = 25
CACHE_TTL = 24 * 3600
_cache: dict[str, tuple[float, dict]] = {}
_semaphores: dict[int, asyncio.Semaphore] = {}  # one per event loop


def _semaphore() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _semaphores:
        _semaphores[loop_id] = asyncio.Semaphore(2)
    return _semaphores[loop_id]


async def road_route(client: httpx.AsyncClient, points: list[GeoPoint], profile: str) -> dict | None:
    """Route through `points` in order. None if no server could route it."""
    if len(points) < 2 or profile not in SERVERS:
        return None
    points = points[:MAX_POINTS]
    coords = ";".join(f"{p.lng:.6f},{p.lat:.6f}" for p in points)
    key = f"{profile}|{coords}"
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    for base in SERVERS[profile]:
        try:
            async with _semaphore():
                r = await client.get(base + coords, params={"overview": "full", "geometries": "geojson", "steps": "false"})
            r.raise_for_status()
            data = r.json()
            if data.get("code") != "Ok" or not data.get("routes"):
                continue
            route = data["routes"][0]
            out = {
                "distance_m": round(route["distance"]),
                "duration_s": round(route["duration"]),
                "legs": [{"distance_m": round(leg["distance"]), "duration_s": round(leg["duration"])} for leg in route["legs"]],
                # GeoJSON is [lng, lat]; Leaflet wants [lat, lng].
                "geometry": [[round(lat, 6), round(lng, 6)] for lng, lat in route["geometry"]["coordinates"]],
                "source": "OSRM / OpenStreetMap",
            }
            _cache[key] = (time.time(), out)
            return out
        except Exception as exc:  # noqa: BLE001 - try the next server
            log.info("routing via %s failed: %s", base, exc)
    return None


async def road_routes(routes: dict[str, list[GeoPoint]], profile: str) -> dict[str, dict | None]:
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
        results = await asyncio.gather(*(road_route(client, pts, profile) for pts in routes.values()))
    return dict(zip(routes.keys(), results))
