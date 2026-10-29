"""FastAPI entrypoint. Planning and refinement stream Server-Sent Events so the
UI can show live agent activity ("Logistics Agent is analyzing flight paths...")."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agents.graph import planner
from .auth import optional_user_id, require_user_id, save_trip
from .auth import router as auth_router
from .config import get_settings
from .db import init_db
from .google_auth import router as google_router
from .admin import prune_old_visits
from .admin import router as admin_router
from .llm import get_llm
from .models import PlanRequest, RefineRequest, RouteRequest, SelectRequest
from .personas import persona_catalog
from .providers.routing import road_routes

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wayfinder")

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()  # create the accounts/trips tables if they don't exist yet
    prune_old_visits()  # keep visit records for VISIT_RETENTION_DAYS only
    yield


app = FastAPI(title="Wayfinder - AI Travel Planning Multi-Agent System", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,  # explicit list: required when credentials (the login cookie) are allowed
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Accept"],
)
app.include_router(auth_router)
app.include_router(google_router)
app.include_router(admin_router)

_session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


async def _run(inputs: dict, session_id: str, user_id: int | None = None) -> AsyncIterator[str]:
    config = {"configurable": {"thread_id": session_id}}
    yield _sse({"type": "session", "session_id": session_id})
    async with _session_locks[session_id]:
        try:
            async for event in planner.astream(inputs, config, stream_mode="custom"):
                yield _sse(event)
            snapshot = await planner.aget_state(config)
            itinerary = snapshot.values.get("itinerary")
            if itinerary is not None:
                data = itinerary.model_dump(mode="json")
                yield _sse({"type": "itinerary", "data": data})
                if user_id is not None:  # signed in: keep the latest version of this trip in their account
                    try:
                        trip_id = await asyncio.to_thread(save_trip, user_id, session_id, data)
                        yield _sse({"type": "saved", "trip_id": trip_id})
                    except Exception:
                        log.exception("saving trip failed")
        except Exception as exc:
            log.exception("planning run failed")
            yield _sse({"type": "error", "message": str(exc)})
    yield _sse({"type": "done"})


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


@app.get("/api/health")
async def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "llm": get_llm().label,
        "providers": {
            "ignav": "live" if s.ignav_api_key else "demo",
            "amadeus":"live" if s.amadeus_client_id and s.amadeus_client_secret else "demo",
            "skyscanner": "live" if s.rapidapi_key else "demo",
            "booking": "live" if s.rapidapi_key else "demo",
            "google_places": "live" if s.google_places_api_key else "demo",
            "yelp": "live" if s.yelp_api_key else "demo",
        },
    }


@app.get("/api/personas")
async def personas() -> list[dict]:
    return persona_catalog()


@app.post("/api/plan")
async def plan(body: PlanRequest, user_id: int | None = Depends(optional_user_id)) -> StreamingResponse:
    session_id = uuid.uuid4().hex
    inputs = {
        "request": body.request,
        "user_message": body.message,
        "is_refinement": False,
        "itinerary": None,
        "flights": [],
        "hotels": [],
        "days": [],
        "flight_tip": "",
    }
    return StreamingResponse(_run(inputs, session_id, user_id), media_type="text/event-stream", headers=_SSE_HEADERS)


async def _require_session(session_id: str) -> None:
    snapshot = await planner.aget_state({"configurable": {"thread_id": session_id}})
    if "request" not in snapshot.values:
        raise HTTPException(status_code=404, detail="Session expired - please plan the trip again.")


@app.post("/api/refine")
async def refine(body: RefineRequest, user_id: int | None = Depends(optional_user_id)) -> StreamingResponse:
    await _require_session(body.session_id)
    inputs = {"user_message": body.message, "is_refinement": True}
    return StreamingResponse(_run(inputs, body.session_id, user_id), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/api/select")
async def select(body: SelectRequest, user_id: int | None = Depends(optional_user_id)) -> StreamingResponse:
    """Swap in an alternative flight/hotel shown in the UI, then recompile."""
    await _require_session(body.session_id)
    inputs = {"user_message": "", "is_refinement": True, "selection": {"kind": body.kind, "id": body.id}}
    return StreamingResponse(_run(inputs, body.session_id, user_id), media_type="text/event-stream", headers=_SSE_HEADERS)


@app.post("/api/routes")
async def routes(body: RouteRequest) -> dict:
    """Road routes (geometry, distance, time per leg) for the map. A null route means the
    routing servers couldn't route it; the map then draws straight lines."""
    return {"profile": body.profile, "routes": await road_routes(body.routes, body.profile)}


class SaveSessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)


@app.post("/api/trips/save")
async def save_session_trip(body: SaveSessionRequest, user_id: int = Depends(require_user_id)) -> dict:
    """Save a trip that was planned before logging in. The itinerary comes from the planner's own
    session state, not from the browser, so nothing can be injected into someone's account."""
    snapshot = await planner.aget_state({"configurable": {"thread_id": body.session_id}})
    itinerary = snapshot.values.get("itinerary")
    if itinerary is None:
        raise HTTPException(status_code=404, detail="That plan is no longer in memory - plan the trip again to save it.")
    trip_id = await asyncio.to_thread(save_trip, user_id, body.session_id, itinerary.model_dump(mode="json"))
    return {"trip_id": trip_id}
