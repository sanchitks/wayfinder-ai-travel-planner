"""Sign in with Google (OAuth 2.0 authorization-code flow with PKCE, OpenID Connect).

1. /api/auth/google/start  - makes a one-time `state`, a PKCE verifier and a `nonce`, binds the
   state to this browser with a short-lived cookie, and redirects to Google.
2. /api/auth/google/callback - checks the state against that cookie, swaps the code for tokens
   (server to server, with the client secret and PKCE verifier), checks the ID token's issuer,
   audience, expiry, nonce and verified email, then finds or creates the Wayfinder user, links
   the Google identity in `oauth_accounts`, starts a normal login session and returns to the site.

The ID token comes straight from Google's token endpoint over TLS, so per OpenID Connect Core
3.1.3.7 the TLS connection authenticates it; its claims are still checked below.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from .auth import _start_session
from .config import get_settings
from .db import OAuthAccount, User, db_session, utcnow
from .security import RateLimiter, caller

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
STATE_COOKIE = "wf_oauth_state"
STATE_TTL = 600  # seconds to finish signing in at Google

# state -> (PKCE verifier, nonce, next path, token mode, created at). In memory: fine for one server process.
_PENDING: dict[str, tuple[str, str, str, bool, float]] = {}
MAX_PENDING = 10_000
_STARTS = RateLimiter(30, 10 * 60)  # sign-in attempts per address


class GoogleSignInError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _safe_next(path: str | None) -> str:
    return path if path and path.startswith("/") and not path.startswith("//") and not path.startswith("/\\") else ""


def _to_site(path: str) -> RedirectResponse:
    return RedirectResponse(get_settings().frontend_url.rstrip("/") + path, status_code=303)


def _fail(code: str) -> RedirectResponse:
    resp = _to_site(f"/login?error={code}")
    resp.delete_cookie(STATE_COOKIE, path="/api/auth/google")
    return resp


def decode_id_token(id_token: str) -> dict:
    try:
        payload = id_token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError) as exc:
        raise GoogleSignInError("google_failed") from exc


def check_claims(claims: dict, nonce: str) -> dict:
    s = get_settings()
    if claims.get("iss") not in ISSUERS or claims.get("aud") != s.google_client_id:
        raise GoogleSignInError("google_failed")
    if int(claims.get("exp", 0)) < time.time() - 60 or claims.get("nonce") != nonce:
        raise GoogleSignInError("google_failed")
    if not claims.get("sub") or not claims.get("email"):
        raise GoogleSignInError("google_failed")
    if claims.get("email_verified") not in (True, "true"):
        raise GoogleSignInError("google_unverified")
    return claims


async def exchange_code(code: str, verifier: str) -> dict:
    """Swap the authorization code for Google's ID token claims."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(TOKEN_URL, data={
            "code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
            "redirect_uri": s.google_redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
        })
    if r.status_code != 200:
        log.warning("google token exchange failed: %s %s", r.status_code, r.text[:200])
        raise GoogleSignInError("google_failed")
    return decode_id_token(r.json().get("id_token", ""))


def link_or_create(claims: dict) -> tuple[int, bool, bool]:
    """The Wayfinder user for this Google identity; returns (user id, newly created, old password removed)."""
    sub, email = str(claims["sub"]), str(claims["email"]).strip().lower()
    name = " ".join(str(claims.get("name") or email.split("@")[0]).split())[:80]
    picture = str(claims.get("picture") or "")[:500]
    with db_session() as db:
        acct = db.scalar(select(OAuthAccount).where(OAuthAccount.provider == "google", OAuthAccount.subject == sub))
        if acct:  # returning Google user
            acct.email, acct.name, acct.picture, acct.last_login_at = email, name, picture, utcnow()
            if picture and not acct.user.avatar_url:
                acct.user.avatar_url = picture
            if acct.user.email == email:
                acct.user.email_verified = True
            return acct.user_id, False, False
        # Google has verified this email, so it is safe to link an existing account that uses it.
        user = db.scalar(select(User).where(User.email == email))
        created, reset = user is None, False
        if created:
            user = User(email=email, password_hash="", name=name or "Traveller", avatar_url=picture, diets=[], interests=[])
            db.add(user)
            db.flush()
        else:
            if picture and not user.avatar_url:
                user.avatar_url = picture
            if not user.email_verified and user.password_hash:
                # Nobody ever proved they own this address, so whoever set that password may not be its owner
                # (someone can sign up with another person's email and wait). The Google owner takes the account
                # over cleanly: the old password and every signed-in browser stop working.
                user.password_hash, reset = "", True
                for s in list(user.sessions):
                    db.delete(s)
                log.info("google sign-in took over unverified account %s: password and sessions cleared", user.id)
        user.email_verified = True
        db.add(OAuthAccount(user_id=user.id, provider="google", subject=sub, email=email, name=name, picture=picture))
        return user.id, created, reset


@router.get("/providers")
async def providers() -> dict:
    """Which sign-in options are set up (the Google button is disabled until it is)."""
    return {"google": get_settings().google_enabled}


@router.get("/google/start")
async def google_start(request: Request, next: str | None = None, mode: str | None = None) -> RedirectResponse:
    s = get_settings()
    if not s.google_enabled:
        return _fail("google_not_configured")
    if not _STARTS.check_and_hit(caller(request)):
        return _fail("google_busy")
    now = time.time()
    for k in [k for k, v in _PENDING.items() if now - v[4] > STATE_TTL]:
        _PENDING.pop(k, None)
    if len(_PENDING) >= MAX_PENDING:  # a flood of unfinished sign-ins: drop the oldest half
        for k in sorted(_PENDING, key=lambda k: _PENDING[k][4])[: MAX_PENDING // 2]:
            _PENDING.pop(k, None)
    state, verifier, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(64), secrets.token_urlsafe(16)
    _PENDING[state] = (verifier, nonce, _safe_next(next), mode == "token", now)
    query = urlencode({
        "client_id": s.google_client_id, "redirect_uri": s.google_redirect_uri, "response_type": "code",
        "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account",
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
    })
    resp = RedirectResponse(f"{AUTH_URL}?{query}", status_code=302)
    resp.set_cookie(STATE_COOKIE, state, max_age=STATE_TTL, httponly=True, samesite="lax", secure=s.cookie_secure, path="/api/auth/google")
    return resp


@router.get("/google/callback")
async def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:  # e.g. the user pressed Cancel on Google's screen
        return _fail("google_cancelled")
    cookie_state = request.cookies.get(STATE_COOKIE)
    pending = _PENDING.pop(state or "", None)
    if not code or not state or not pending or not cookie_state or not secrets.compare_digest(cookie_state, state):
        return _fail("google_state")
    verifier, nonce, next_path, wants_token, created_at = pending
    if time.time() - created_at > STATE_TTL:
        return _fail("google_state")
    try:
        claims = check_claims(await exchange_code(code, verifier), nonce)
        user_id, created, reset = await asyncio.to_thread(link_or_create, claims)
    except GoogleSignInError as exc:
        return _fail(exc.code)
    except Exception:
        log.exception("google sign-in failed")
        return _fail("google_failed")
    if reset:  # tell them why their old password no longer works
        target = "/profile?tab=security&password_reset=1"
    else:
        target = next_path or ("/profile?welcome=1" if created else "/")
    resp = _to_site(target)
    resp.delete_cookie(STATE_COOKIE, path="/api/auth/google")
    token = await asyncio.to_thread(_start_session, resp, user_id, request)
    if wants_token:
        # Website on another site: hand the token over in the URL fragment, which browsers never
        # send to any server; the page stores it and removes it from the address bar at once.
        resp.headers["location"] += f"#wf_token={token}"
    return resp
