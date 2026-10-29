"""Visit tracking and the admin panel API.

POST /api/visits records one page view (the website calls it on every page). Each browser gets a
random `wf_vid` cookie so returning visitors can be counted; signed-in customers are also linked
to their account. The IP is stored with its last part hidden. Bots and automated browsers are
skipped.

/api/admin/* is only for accounts whose email is in ADMIN_EMAILS. Customer passwords are never
sent: a stored password shows as a row of dots, a Google-only account as "Google sign-in".
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import secrets
import time
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select

from .auth import optional_user_id, require_user_id
from .config import get_settings
from .db import OAuthAccount, Trip, User, Visit, db_session, utcnow
from .net import client_ip

router = APIRouter(prefix="/api")

VISITOR_COOKIE = "wf_vid"
IST = timezone(timedelta(hours=5, minutes=30), "IST")  # day boundaries for the charts
PASSWORD_MASK = "••••••••"
_BOT = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|preview|facebookexternalhit|curl|wget|python-requests|httpx", re.I)
_RECENT: dict[tuple[str, str], float] = {}  # (visitor, path) -> last recorded, to ignore double counts


# ---------- recording visits ----------
class VisitIn(BaseModel):
    path: str = Field(min_length=1, max_length=300)
    referrer: str = Field(default="", max_length=1000)


def parse_agent(ua: str) -> tuple[str, str, str]:
    """(browser, OS, device) from a User-Agent string."""
    browser = ("Edge" if "Edg/" in ua else "Opera" if "OPR/" in ua or "Opera" in ua else "Samsung Internet" if "SamsungBrowser" in ua
               else "Firefox" if "Firefox/" in ua or "FxiOS" in ua else "Chrome" if "Chrome/" in ua or "CriOS" in ua
               else "Safari" if "Safari/" in ua else "Other")
    os = ("iOS" if re.search(r"iPhone|iPad|iPod", ua) else "Android" if "Android" in ua else "Windows" if "Windows" in ua
          else "macOS" if "Mac OS X" in ua or "Macintosh" in ua else "Linux" if "Linux" in ua else "Other")
    device = ("Tablet" if re.search(r"iPad|Tablet", ua) or ("Android" in ua and "Mobile" not in ua)
              else "Mobile" if re.search(r"Mobi|iPhone|iPod", ua) else "Desktop")
    return browser, os, device


def mask_ip(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if addr.version == 4:
        return ".".join(str(addr).split(".")[:3]) + ".x"
    return ":".join(addr.exploded.split(":")[:3]) + ":x"


def _external_referrer(ref: str) -> str:
    """Only referrers from other sites are interesting (Google, Instagram...), not our own pages."""
    try:
        u = urlparse(ref)
    except ValueError:
        return ""
    own = urlparse(get_settings().frontend_url).hostname
    if u.scheme not in ("http", "https") or not u.hostname or u.hostname in (own, "localhost", "127.0.0.1"):
        return ""
    return f"{u.hostname}{u.path}"[:300]


@router.post("/visits", status_code=204)
async def record_visit(body: VisitIn, request: Request, response: Response,
                       user_id: int | None = Depends(optional_user_id)) -> None:
    ua = request.headers.get("user-agent", "")[:300]
    if not ua or _BOT.search(ua):
        return
    path = body.path.split("?")[0].split("#")[0][:300]
    if not path.startswith("/"):
        return
    vid = request.cookies.get(VISITOR_COOKIE, "")
    if not re.fullmatch(r"[0-9a-f]{32}", vid):
        vid = secrets.token_hex(16)
        response.set_cookie(VISITOR_COOKIE, vid, max_age=365 * 86400, httponly=True, samesite="lax",
                            secure=get_settings().cookie_secure, path="/")
    now = time.monotonic()
    if now - _RECENT.get((vid, path), 0) < 3:  # same page twice within 3 s: one visit
        return
    _RECENT[(vid, path)] = now
    if len(_RECENT) > 20000:
        _RECENT.clear()
    browser, os, device = parse_agent(ua)
    visit = Visit(visitor_id=vid, user_id=user_id, path=path, referrer=_external_referrer(body.referrer),
                  browser=browser, os=os, device=device, ip_masked=mask_ip(client_ip(request)),
                  user_agent=ua)

    def save() -> None:
        with db_session() as db:
            db.add(visit)

    await asyncio.to_thread(save)


def prune_old_visits() -> None:
    cutoff = utcnow() - timedelta(days=get_settings().visit_retention_days)
    with db_session() as db:
        db.execute(delete(Visit).where(Visit.created_at < cutoff))


# ---------- admin access ----------
def is_admin_email(email: str) -> bool:
    return email.lower() in get_settings().admin_email_list


async def require_admin(user_id: int = Depends(require_user_id)) -> int:
    def check() -> bool:
        with db_session() as db:
            u = db.get(User, user_id)
            return bool(u and is_admin_email(u.email))

    if not await asyncio.to_thread(check):
        raise HTTPException(403, "This page is only for Wayfinder admins.")
    return user_id


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _user_ref(u: User | None) -> dict | None:
    return {"id": u.id, "name": u.name, "email": u.email} if u else None


# ---------- admin API ----------
@router.get("/admin/summary")
async def admin_summary(days: int = 30, _: int = Depends(require_admin)) -> dict:
    days = max(7, min(days, 180))

    def build() -> dict:
        now = utcnow()
        today_ist = now.astimezone(IST).date()
        since = now - timedelta(days=days)
        with db_session() as db:
            rows = db.execute(select(Visit.created_at, Visit.visitor_id, Visit.user_id, Visit.path, Visit.device,
                                     Visit.browser, Visit.referrer).where(Visit.created_at >= since)).all()
            customers = db.scalar(select(func.count(User.id))) or 0
            new_7d = db.scalar(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=7))) or 0
            google = db.scalar(select(func.count(func.distinct(OAuthAccount.user_id))).where(OAuthAccount.provider == "google")) or 0
            trips_total = db.scalar(select(func.count(Trip.id))) or 0
            trips_7d = db.scalar(select(func.count(Trip.id)).where(Trip.created_at >= now - timedelta(days=7))) or 0
            destinations = db.execute(select(Trip.destination, func.count(Trip.id)).group_by(Trip.destination)
                                      .order_by(func.count(Trip.id).desc()).limit(8)).all()

        def window(d: int):
            cut = now - timedelta(days=d)
            return [r for r in rows if _aware(r.created_at) >= cut]

        today = [r for r in rows if _aware(r.created_at).astimezone(IST).date() == today_ist]
        week = window(7)
        series = []
        for i in range(days - 1, -1, -1):
            day = today_ist - timedelta(days=i)
            day_rows = [r for r in rows if _aware(r.created_at).astimezone(IST).date() == day]
            series.append({"date": day.isoformat(), "views": len(day_rows), "visitors": len({r.visitor_id for r in day_rows})})
        return {
            "days": days,
            "kpis": {
                "visitors_today": len({r.visitor_id for r in today}),
                "views_today": len(today),
                "visitors_7d": len({r.visitor_id for r in week}),
                "views_7d": len(week),
                "signed_in_visitors_7d": len({r.user_id for r in week if r.user_id}),
                "customers": customers,
                "new_customers_7d": new_7d,
                "google_customers": google,
                "trips": trips_total,
                "trips_7d": trips_7d,
            },
            "series": series,
            "top_pages": Counter(r.path for r in rows).most_common(8),
            "devices": Counter(r.device for r in rows).most_common(),
            "browsers": Counter(r.browser for r in rows).most_common(6),
            "referrers": Counter(r.referrer.split("/")[0] for r in rows if r.referrer).most_common(6),
            "destinations": [(d, n) for d, n in destinations],
        }

    return await asyncio.to_thread(build)


@router.get("/admin/visits")
async def admin_visits(q: str = "", limit: int = 50, offset: int = 0, _: int = Depends(require_admin)) -> dict:
    limit, offset = max(1, min(limit, 200)), max(0, offset)

    def load() -> dict:
        with db_session() as db:
            query = select(Visit, User).outerjoin(User, Visit.user_id == User.id)
            if q.strip():
                like = f"%{q.strip()}%"
                query = query.where(or_(Visit.path.ilike(like), Visit.browser.ilike(like), Visit.os.ilike(like), Visit.device.ilike(like),
                                        Visit.referrer.ilike(like), Visit.visitor_id.ilike(like), User.name.ilike(like), User.email.ilike(like)))
            total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = db.execute(query.order_by(Visit.created_at.desc()).limit(limit).offset(offset)).all()
            return {"total": total, "rows": [{
                "id": v.id, "time": _aware(v.created_at).isoformat(), "visitor": v.visitor_id[:8], "customer": _user_ref(u),
                "path": v.path, "referrer": v.referrer, "browser": v.browser, "os": v.os, "device": v.device, "ip": v.ip_masked,
            } for v, u in rows]}

    return await asyncio.to_thread(load)


@router.get("/admin/customers")
async def admin_customers(q: str = "", _: int = Depends(require_admin)) -> dict:
    def load() -> dict:
        with db_session() as db:
            query = select(User)
            if q.strip():
                like = f"%{q.strip()}%"
                query = query.where(or_(User.name.ilike(like), User.email.ilike(like), User.phone.ilike(like), User.home_city.ilike(like)))
            users = db.scalars(query.order_by(User.created_at.desc())).all()
            visit_stats = dict((uid, (n, last)) for uid, n, last in db.execute(
                select(Visit.user_id, func.count(Visit.id), func.max(Visit.created_at)).where(Visit.user_id.is_not(None)).group_by(Visit.user_id)).all())
            trip_counts = dict(db.execute(select(Trip.user_id, func.count(Trip.id)).group_by(Trip.user_id)).all())
            rows = []
            for u in users:
                n_visits, last_seen = visit_stats.get(u.id, (0, None))
                rows.append({
                    "id": u.id, "name": u.name, "email": u.email, "phone": u.phone, "home_city": u.home_city,
                    "persona": u.persona, "budget": u.budget, "diets": u.diets or [], "interests": u.interests or [],
                    "bio": u.bio,
                    # Never the hash: dots when a password exists, otherwise how they sign in.
                    "password": PASSWORD_MASK if u.password_hash else "",
                    "sign_in": sorted({"email"} if u.password_hash else set()) + sorted({a.provider for a in u.oauth_accounts}),
                    "is_admin": is_admin_email(u.email),
                    "trips": trip_counts.get(u.id, 0), "visits": n_visits,
                    "last_seen": _aware(last_seen).isoformat() if last_seen else None,
                    "created_at": _aware(u.created_at).isoformat(),
                })
            return {"total": len(rows), "rows": rows}

    return await asyncio.to_thread(load)


@router.get("/admin/trips")
async def admin_trips(q: str = "", _: int = Depends(require_admin)) -> dict:
    def load() -> dict:
        with db_session() as db:
            query = select(Trip, User).join(User, Trip.user_id == User.id)
            if q.strip():
                like = f"%{q.strip()}%"
                query = query.where(or_(Trip.title.ilike(like), Trip.destination.ilike(like), User.name.ilike(like), User.email.ilike(like)))
            rows = db.execute(query.order_by(Trip.updated_at.desc()).limit(500)).all()
            return {"total": len(rows), "rows": [{
                "id": t.id, "customer": _user_ref(u), "title": t.title, "destination": t.destination,
                "start_date": t.start_date, "end_date": t.end_date, "persona": t.persona, "total": t.total, "version": t.version,
                "created_at": _aware(t.created_at).isoformat(), "updated_at": _aware(t.updated_at).isoformat(),
            } for t, u in rows]}

    return await asyncio.to_thread(load)
