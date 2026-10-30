"""Accounts: sign-up, log-in, profile editing and saved trips.

Two ways to carry the login: an HttpOnly cookie (default, used when the website and API share a
site, e.g. localhost) or, when the website is hosted on another site (GitHub Pages calling the API
on Render, where browsers block cross-site cookies), a bearer token the page keeps and sends in the
Authorization header. The page asks for a token with the header "X-Auth-Mode: token".

Passwords are hashed with scrypt (Python standard library), each with its own
random salt; plain passwords are never stored or logged. A successful log-in
sets an HttpOnly, SameSite=Lax cookie holding a random token; the database only
keeps a SHA-256 of that token, so a leaked database can't be used to sign in.
Repeated failed log-ins from the same address are slowed down (429).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select

from .config import get_settings
from .db import LoginSession, Trip, User, Visit, db_session, utcnow
from .net import client_ip, mask_ip, parse_agent
from .security import RateLimiter, caller

router = APIRouter(prefix="/api")

COOKIE = "wf_session"
PERSONAS = ("budget", "luxury", "business", "family")
DIETS = ("Vegetarian", "Pure veg", "Jain", "Vegan", "Non veg")
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
_PHONE = re.compile(r"^\+?[0-9 ()-]{7,20}$")

# ---------- passwords ----------
_N, _R, _P = 2**14, 8, 1  # scrypt cost: ~16 MB, ~50 ms per hash


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        expected = base64.b64decode(dk)
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(got, expected)
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(8))  # same work for unknown emails, so timing doesn't reveal accounts

# ---------- rate limiting (in memory) ----------
# Wrong passwords per address, and per account so one account can't be guessed at from many addresses.
_FAILS = RateLimiter(8, 15 * 60)
_ACCOUNT_FAILS = RateLimiter(10, 15 * 60)
# New accounts per address, so nobody can fill the database with throwaway accounts.
_SIGNUPS = RateLimiter(10, 60 * 60)
_TOO_MANY = "Too many attempts. Please wait a few minutes and try again."


def _check_rate(key: str, limiter: RateLimiter = _FAILS) -> None:
    if limiter.blocked(key):
        raise HTTPException(429, _TOO_MANY)


async def password_breached(password: str) -> bool:
    """True if the password is in Have I Been Pwned's list of leaked passwords. Uses the k-anonymity
    range API: only the first 5 hex characters of its SHA-1 are sent. If the service can't be reached
    the check is skipped (sign-up must not depend on it)."""
    if not get_settings().check_breached_passwords:
        return False
    digest = hashlib.sha1(password.encode()).hexdigest().upper()
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"https://api.pwnedpasswords.com/range/{digest[:5]}", headers={"Add-Padding": "true"})
        if r.status_code != 200:
            return False
    except httpx.HTTPError:
        return False
    for line in r.text.splitlines():
        suffix, _, count = line.partition(":")
        if suffix == digest[5:] and count.strip() not in ("", "0"):  # padding rows have a count of 0
            return True
    return False


BREACHED = "This password has appeared in a data breach, so attackers try it first. Please choose a different one."


def _device_label(request: Request | None) -> str:
    if request is None:
        return ""
    browser, os, device = parse_agent(request.headers.get("user-agent", "")[:300])
    return f"{browser} on {os} ({device})"[:80]


# ---------- schemas ----------
class UserOut(BaseModel):
    id: int
    email: str
    name: str
    phone: str
    home_city: str
    persona: str
    budget: int | None
    diets: list[str]
    interests: list[str]
    bio: str
    created_at: datetime
    trip_count: int = 0
    avatar_url: str = ""
    # False for accounts created with Google that haven't set a password yet.
    has_password: bool = True
    linked_providers: list[str] = []
    email_verified: bool = False
    is_admin: bool = False

    @classmethod
    def of(cls, u: User, trip_count: int = 0) -> UserOut:
        return cls(id=u.id, email=u.email, name=u.name, phone=u.phone, home_city=u.home_city, persona=u.persona,
                   budget=u.budget, diets=u.diets or [], interests=u.interests or [], bio=u.bio,
                   created_at=u.created_at, trip_count=trip_count, avatar_url=u.avatar_url or "",
                   has_password=bool(u.password_hash), linked_providers=sorted({a.provider for a in u.oauth_accounts}),
                   email_verified=bool(u.email_verified),
                   # Same rule as the admin API (admin.is_admin): listed in ADMIN_EMAILS and email proved.
                   is_admin=u.email.lower() in get_settings().admin_email_list and bool(u.email_verified))


def _email(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL.match(v) or len(v) > 254:
        raise ValueError("Enter a valid email address.")
    return v


def _new_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Use at least 8 characters.")
    if len(v) > 128:
        raise ValueError("Use at most 128 characters.")
    if v.isdigit() or v.isalpha():
        raise ValueError("Mix letters with numbers or symbols.")
    return v


class AuthOut(UserOut):
    """A user plus, in token mode only, the session token the page must store."""

    session_token: str | None = None


class SignupIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str
    password: str

    _e = field_validator("email")(_email)
    _p = field_validator("password")(_new_password)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Tell us your name.")
        return v


class LoginIn(BaseModel):
    email: str
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def _e(cls, v: str) -> str:
        return v.strip().lower()


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phone: str = Field(default="", max_length=20)
    home_city: str = Field(default="", max_length=80)
    persona: Literal["budget", "luxury", "business", "family"] = "budget"
    budget: int | None = Field(default=None, ge=5000, le=1_000_000)
    diets: list[str] = Field(default_factory=list, max_length=5)
    interests: list[str] = Field(default_factory=list, max_length=20)
    bio: str = Field(default="", max_length=500)

    @field_validator("name", "home_city", "bio")
    @classmethod
    def _trim(cls, v: str) -> str:
        return v.strip()

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        if v and not _PHONE.match(v):
            raise ValueError("Enter a valid phone number, e.g. +91 98765 43210.")
        return v

    @field_validator("diets")
    @classmethod
    def _diets(cls, v: list[str]) -> list[str]:
        v = [d for d in dict.fromkeys(v) if d in DIETS]
        if "Non veg" in v and len(v) > 1:
            raise ValueError("Non veg can't be combined with vegetarian diets.")
        return v

    @field_validator("interests")
    @classmethod
    def _interests(cls, v: list[str]) -> list[str]:
        return [i.strip()[:30] for i in dict.fromkeys(v) if i.strip()]


class PasswordIn(BaseModel):
    # Not needed when the account has no password yet (created with Google).
    current_password: str = Field(default="", max_length=128)
    new_password: str

    _p = field_validator("new_password")(_new_password)


class DeleteIn(BaseModel):
    password: str = Field(default="", max_length=128)
    # Accounts without a password (Google sign-in) confirm by typing DELETE instead.
    confirm: str = Field(default="", max_length=20)


class TripSummary(BaseModel):
    id: str
    title: str
    destination: str
    start_date: str
    end_date: str
    persona: str
    total: int
    version: int
    image: str
    created_at: datetime
    updated_at: datetime


# ---------- sessions ----------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _start_session(response: Response, user_id: int, request: Request | None = None) -> str:
    """Create a login session; sets the cookie and returns the token (for token mode)."""
    s = get_settings()
    token = secrets.token_urlsafe(32)
    now = utcnow()
    with db_session() as db:
        db.add(LoginSession(token_hash=_hash_token(token), user_id=user_id, expires_at=now + timedelta(days=s.session_days),
                            last_used_at=now, device=_device_label(request),
                            ip_masked=mask_ip(client_ip(request)) if request else ""))
    response.set_cookie(COOKIE, token, max_age=s.session_days * 86400, httponly=True, samesite="lax", secure=s.cookie_secure, path="/")
    return token


def session_token(request: Request) -> str | None:
    """The login token from the Authorization header (token mode) or the cookie."""
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip() or None
    return request.cookies.get(COOKIE)


def token_mode(request: Request) -> bool:
    return request.headers.get("x-auth-mode", "").lower() == "token"


def _end_session(response: Response, token: str | None) -> None:
    if token:
        with db_session() as db:
            row = db.get(LoginSession, _hash_token(token))
            if row:
                db.delete(row)
    response.delete_cookie(COOKIE, path="/", samesite="lax", secure=get_settings().cookie_secure, httponly=True)


def user_id_from_token(token: str | None) -> int | None:
    """The signed-in user's id for a cookie token, or None (missing, unknown or expired)."""
    if not token or len(token) > 200:
        return None
    with db_session() as db:
        row = db.get(LoginSession, _hash_token(token))
        if not row:
            return None
        now = utcnow()
        if _aware(row.expires_at) < now:
            db.delete(row)
            return None
        if row.last_used_at is None or now - _aware(row.last_used_at) > timedelta(minutes=5):  # don't write on every request
            row.last_used_at = now
        return row.user_id


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def prune_expired_sessions() -> None:
    with db_session() as db:
        db.execute(delete(LoginSession).where(LoginSession.expires_at < utcnow()))


async def optional_user_id(request: Request) -> int | None:
    return await asyncio.to_thread(user_id_from_token, session_token(request))


async def require_user_id(user_id: int | None = Depends(optional_user_id)) -> int:
    if user_id is None:
        raise HTTPException(401, "Please log in.")
    return user_id


def _load_user(user_id: int) -> UserOut:
    with db_session() as db:
        u = db.get(User, user_id)
        if not u:
            raise HTTPException(401, "Please log in.")
        return UserOut.of(u, trip_count=len(u.trips))


# ---------- trips ----------
def _trip_image(itinerary: dict) -> str:
    sights = [a["place"] for d in itinerary.get("days", []) for a in d.get("activities", [])
              if a.get("kind") == "activity" and a.get("place", {}).get("image_url")]
    sights.sort(key=lambda p: p.get("popularity", 0), reverse=True)
    if sights:
        return sights[0]["image_url"]
    return (itinerary.get("hotel") or {}).get("photo_url", "")


def save_trip(user_id: int, session_id: str, itinerary: dict) -> str:
    """Create or update the trip for this planning session; returns its id."""
    req = itinerary["request"]
    fields = dict(
        title=f"{req['origin']} → {req['destination']}", destination=req["destination"],
        start_date=str(req["start_date"]), end_date=str(req["end_date"]), persona=req["persona"],
        total=int(itinerary.get("costs", {}).get("total", 0)), version=int(itinerary.get("version", 1)), itinerary=itinerary,
    )
    with db_session() as db:
        trip = db.scalar(select(Trip).where(Trip.user_id == user_id, Trip.session_id == session_id))
        if trip:
            for k, v in fields.items():
                setattr(trip, k, v)
        else:
            trip = Trip(id=uuid.uuid4().hex, user_id=user_id, session_id=session_id, **fields)
            db.add(trip)
        return trip.id


def _summary(t: Trip) -> TripSummary:
    return TripSummary(id=t.id, title=t.title, destination=t.destination, start_date=t.start_date, end_date=t.end_date,
                       persona=t.persona, total=t.total, version=t.version, image=_trip_image(t.itinerary),
                       created_at=t.created_at, updated_at=t.updated_at)


# ---------- routes ----------
@router.post("/auth/signup", status_code=201)
async def signup(body: SignupIn, response: Response, request: Request) -> AuthOut:
    ip = caller(request)
    if not _SIGNUPS.check_and_hit(ip):
        raise HTTPException(429, _TOO_MANY)
    if await password_breached(body.password):
        raise HTTPException(422, BREACHED)

    def create() -> int:
        with db_session() as db:
            if db.scalar(select(User.id).where(User.email == body.email)) is not None:
                raise HTTPException(409, "An account with this email already exists. Try logging in.")
            u = User(email=body.email, password_hash=hash_password(body.password), name=body.name, diets=[], interests=[])
            db.add(u)
            db.flush()
            return u.id

    user_id = await asyncio.to_thread(create)
    token = await asyncio.to_thread(_start_session, response, user_id, request)
    user = await asyncio.to_thread(_load_user, user_id)
    return AuthOut(**user.model_dump(), session_token=token if token_mode(request) else None)


@router.post("/auth/login")
async def login(body: LoginIn, response: Response, request: Request) -> AuthOut:
    key, account = f"login:{caller(request)}", f"login:{body.email}"
    _check_rate(key)
    _check_rate(account, _ACCOUNT_FAILS)

    def check() -> int | None:
        with db_session() as db:
            u = db.scalar(select(User).where(User.email == body.email))
            ok = verify_password(body.password, (u.password_hash if u else "") or _DUMMY_HASH) and bool(u and u.password_hash)
            return u.id if (u and ok) else None

    user_id = await asyncio.to_thread(check)
    if user_id is None:
        _FAILS.hit(key)
        _ACCOUNT_FAILS.hit(account)
        raise HTTPException(401, "Email or password is incorrect.")
    _FAILS.reset(key)
    _ACCOUNT_FAILS.reset(account)
    token = await asyncio.to_thread(_start_session, response, user_id, request)
    user = await asyncio.to_thread(_load_user, user_id)
    return AuthOut(**user.model_dump(), session_token=token if token_mode(request) else None)


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    await asyncio.to_thread(_end_session, response, session_token(request))


class SessionOut(BaseModel):
    id: str  # first 16 characters of the token's hash: names the session, can't be used to sign in
    device: str
    ip: str
    created_at: datetime
    last_used_at: datetime | None
    current: bool


@router.get("/profile/sessions")
async def list_sessions(request: Request, user_id: int = Depends(require_user_id)) -> list[SessionOut]:
    """Every browser signed in to this account, so the customer can spot one they don't recognise."""
    mine = _hash_token(session_token(request) or "")

    def load() -> list[SessionOut]:
        with db_session() as db:
            rows = db.scalars(select(LoginSession).where(LoginSession.user_id == user_id, LoginSession.expires_at >= utcnow())
                              .order_by(LoginSession.created_at.desc())).all()
            out = [SessionOut(id=r.token_hash[:16], device=r.device or "Unknown device", ip=r.ip_masked,
                              created_at=_aware(r.created_at), last_used_at=_aware(r.last_used_at) if r.last_used_at else None,
                              current=r.token_hash == mine) for r in rows]
            return sorted(out, key=lambda s: not s.current)  # this browser first

    return await asyncio.to_thread(load)


@router.delete("/profile/sessions/{session_id}", status_code=204)
async def end_session(session_id: str, user_id: int = Depends(require_user_id)) -> None:
    if not re.fullmatch(r"[0-9a-f]{16}", session_id):
        raise HTTPException(404, "Session not found.")

    def remove() -> bool:
        with db_session() as db:
            rows = db.scalars(select(LoginSession).where(LoginSession.user_id == user_id,
                                                         LoginSession.token_hash.startswith(session_id))).all()
            for r in rows:
                db.delete(r)
            return bool(rows)

    if not await asyncio.to_thread(remove):
        raise HTTPException(404, "Session not found.")


@router.post("/profile/sessions/sign-out-others")
async def end_other_sessions(request: Request, user_id: int = Depends(require_user_id)) -> dict:
    mine = _hash_token(session_token(request) or "")

    def remove() -> int:
        with db_session() as db:
            res = db.execute(delete(LoginSession).where(LoginSession.user_id == user_id, LoginSession.token_hash != mine))
            return res.rowcount or 0

    return {"signed_out": await asyncio.to_thread(remove)}


@router.get("/auth/me")
async def me(user_id: int = Depends(require_user_id)) -> UserOut:
    return await asyncio.to_thread(_load_user, user_id)


@router.put("/profile")
async def update_profile(body: ProfileIn, user_id: int = Depends(require_user_id)) -> UserOut:
    def save() -> None:
        with db_session() as db:
            u = db.get(User, user_id)
            for k, v in body.model_dump().items():
                setattr(u, k, v)

    await asyncio.to_thread(save)
    return await asyncio.to_thread(_load_user, user_id)


@router.post("/profile/password", status_code=204, response_model=None)
async def change_password(body: PasswordIn, request: Request, response: Response,
                          user_id: int = Depends(require_user_id)) -> Response | None:
    key = f"password:{caller(request)}"
    _check_rate(key)
    if await password_breached(body.new_password):
        raise HTTPException(422, BREACHED)

    def change() -> bool:
        with db_session() as db:
            u = db.get(User, user_id)
            if u.password_hash and not verify_password(body.current_password, u.password_hash):
                return False
            u.password_hash = hash_password(body.new_password)
            # Sign out every other browser: their sessions are dropped, this one gets a fresh token below.
            for s in list(u.sessions):
                db.delete(s)
            return True

    if not await asyncio.to_thread(change):
        _FAILS.hit(key)
        raise HTTPException(400, "Your current password is incorrect.")
    token = await asyncio.to_thread(_start_session, response, user_id, request)
    if token_mode(request):  # the old token was just revoked: hand the page its new one
        return JSONResponse({"session_token": token})
    return None


@router.post("/profile/delete", status_code=204)
async def delete_account(body: DeleteIn, request: Request, response: Response, user_id: int = Depends(require_user_id)) -> None:
    key = f"delete:{caller(request)}"
    _check_rate(key)

    def remove() -> bool:
        with db_session() as db:
            u = db.get(User, user_id)
            confirmed = verify_password(body.password, u.password_hash) if u.password_hash else body.confirm == "DELETE"
            if not confirmed:
                return False
            db.delete(u)  # sessions, trips and linked Google identities go with it (cascade)
            return True

    if not await asyncio.to_thread(remove):
        _FAILS.hit(key)
        raise HTTPException(400, "Password is incorrect." if body.password else "Type DELETE to confirm.")
    response.delete_cookie(COOKIE, path="/", samesite="lax", secure=get_settings().cookie_secure, httponly=True)


@router.get("/trips")
async def list_trips(user_id: int = Depends(require_user_id)) -> list[TripSummary]:
    def load() -> list[TripSummary]:
        with db_session() as db:
            rows = db.scalars(select(Trip).where(Trip.user_id == user_id).order_by(Trip.updated_at.desc()))
            return [_summary(t) for t in rows]

    return await asyncio.to_thread(load)


@router.get("/trips/{trip_id}")
async def get_trip(trip_id: str, user_id: int = Depends(require_user_id)) -> dict:
    def load() -> dict | None:
        with db_session() as db:
            t = db.get(Trip, trip_id)
            if not t or t.user_id != user_id:  # never reveal whether someone else's trip exists
                return None
            return {"id": t.id, "session_id": t.session_id, "itinerary": t.itinerary}

    trip = await asyncio.to_thread(load)
    if trip is None:
        raise HTTPException(404, "Trip not found.")
    return trip


@router.delete("/trips/{trip_id}", status_code=204)
async def delete_trip(trip_id: str, user_id: int = Depends(require_user_id)) -> None:
    def remove() -> bool:
        with db_session() as db:
            t = db.get(Trip, trip_id)
            if not t or t.user_id != user_id:
                return False
            db.delete(t)
            return True

    if not await asyncio.to_thread(remove):
        raise HTTPException(404, "Trip not found.")


@router.get("/profile/export")
async def export_my_data(user_id: int = Depends(require_user_id)) -> Response:
    """Everything stored about the signed-in customer, as a JSON download (never the password hash)."""
    def build() -> dict:
        with db_session() as db:
            u = db.get(User, user_id)
            trips = db.scalars(select(Trip).where(Trip.user_id == user_id).order_by(Trip.created_at)).all()
            visits = db.scalars(select(Visit).where(Visit.user_id == user_id).order_by(Visit.created_at)).all()
            return {
                "exported_at": utcnow().isoformat(),
                "account": {
                    "name": u.name, "email": u.email, "phone": u.phone, "home_city": u.home_city, "bio": u.bio,
                    "travel_style": u.persona, "usual_budget_inr": u.budget, "diets": u.diets or [], "interests": u.interests or [],
                    "profile_photo": u.avatar_url, "created_at": u.created_at.isoformat(), "updated_at": u.updated_at.isoformat(),
                },
                "sign_in": {
                    "password_set": bool(u.password_hash),  # passwords are stored only as one-way hashes; the hash isn't exported
                    "linked_accounts": [{"provider": a.provider, "email": a.email, "linked_at": a.created_at.isoformat(),
                                         "last_sign_in": a.last_login_at.isoformat()} for a in u.oauth_accounts],
                },
                "saved_trips": [{"title": t.title, "destination": t.destination, "start_date": t.start_date, "end_date": t.end_date,
                                 "travel_style": t.persona, "estimated_total_inr": t.total, "version": t.version,
                                 "saved_at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat(), "itinerary": t.itinerary}
                                for t in trips],
                "page_visits": [{"time": v.created_at.isoformat(), "page": v.path, "came_from": v.referrer, "device": v.device,
                                 "browser": v.browser, "os": v.os, "ip_partly_hidden": v.ip_masked} for v in visits],
            }

    data = await asyncio.to_thread(build)
    name = f"wayfinder-my-data-{utcnow().date().isoformat()}.json"
    return Response(json.dumps(data, ensure_ascii=False, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/site-info")
async def site_info() -> dict:
    """Public facts for the Privacy Policy page."""
    s = get_settings()
    return {"privacy_contact": s.privacy_contact_email, "visit_retention_days": s.visit_retention_days}
