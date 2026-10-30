"""Token-mode tests: the setup used when the website is on GitHub Pages and the API on another
site, where browsers block cross-site cookies. Every request here goes without cookies.
Uses a throwaway database.

    cd backend && .venv/Scripts/python token_mode_test.py
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TMP = Path(tempfile.mkdtemp()) / "test.db"
SITE = "https://sanchitks.github.io"
os.environ.update({
    "DATABASE_URL": f"sqlite:///{TMP.as_posix()}", "COOKIE_SECURE": "false", "CORS_ORIGINS": SITE,
    "FRONTEND_URL": f"{SITE}/wayfinder-ai-travel-planner", "GOOGLE_CLIENT_ID": "test.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "test-secret", "ADMIN_EMAILS": "boss@example.com",
})

os.environ["CHECK_BREACHED_PASSWORDS"] = "false"  # no network calls in tests

from fastapi.testclient import TestClient  # noqa: E402

import app.google_auth as g  # noqa: E402
from app.db import User, db_session, normalize_db_url  # noqa: E402
from sqlalchemy import select  # noqa: E402
from app.main import app  # noqa: E402

failures = 0


def check(cond: bool, label: str) -> None:
    global failures
    print(("[ok]   " if cond else "[FAIL] ") + label)
    failures += 0 if cond else 1


TOKEN_MODE = {"X-Auth-Mode": "token", "Origin": SITE}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/156.0 Safari/537.36"}


def bearer(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", **TOKEN_MODE}


class NoCookies(TestClient):
    """A client that never keeps cookies, like a page on another site."""

    def request(self, *a, **kw):
        self.cookies.clear()
        return super().request(*a, **kw)


with NoCookies(app) as c:
    # browser permission check (CORS preflight) from the GitHub Pages site
    r = c.options("/api/auth/me", headers={"Origin": SITE, "Access-Control-Request-Method": "GET",
                                          "Access-Control-Request-Headers": "authorization,x-auth-mode,x-visitor-id"})
    allowed = r.headers.get("access-control-allow-headers", "").lower()
    check(r.status_code == 200 and r.headers.get("access-control-allow-origin") == SITE
          and all(h in allowed for h in ("authorization", "x-auth-mode", "x-visitor-id")), "GitHub Pages site may call the API with the token headers")
    r = c.options("/api/auth/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    check(r.headers.get("access-control-allow-origin") != "https://evil.example", "other websites are not allowed")

    # sign-up / login hand out a token only when asked
    r = c.post("/api/auth/signup", json={"name": "Asha", "email": "asha@example.com", "password": "Asha-pass-2026"}, headers=TOKEN_MODE)
    tok = r.json().get("session_token")
    check(r.status_code == 201 and bool(tok), "token-mode sign-up returns a session token")
    r = c.post("/api/auth/login", json={"email": "asha@example.com", "password": "Asha-pass-2026"})
    check(r.status_code == 200 and r.json().get("session_token") is None, "normal (cookie) login never puts the token in the response")
    check(c.get("/api/auth/me").status_code == 401, "without the token there is no login (no cookies here)")
    me = c.get("/api/auth/me", headers=bearer(tok))
    check(me.status_code == 200 and me.json()["email"] == "asha@example.com", "the token in the Authorization header signs you in")
    check(c.get("/api/auth/me", headers=bearer("not-a-real-token")).status_code == 401, "a made-up token is refused")

    # profile, trips and planning with the token
    prof = {"name": "Asha", "phone": "", "home_city": "Pune", "persona": "budget", "budget": None, "diets": [], "interests": [], "bio": ""}
    check(c.put("/api/profile", json=prof, headers=bearer(tok)).json()["home_city"] == "Pune", "profile saves with the token")
    trip = {"request": {"origin": "Delhi", "destination": "Jaipur", "start_date": "2026-12-04", "end_date": "2026-12-06", "adults": 2,
                        "children": 0, "budget": 40000, "persona": "budget", "interests": [], "flexible_dates": False,
                        "work_location": None, "notes": ""}, "message": ""}
    events = []
    with c.stream("POST", "/api/plan", json=trip, headers=bearer(tok)) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    check(any(e.get("type") == "saved" for e in events), "a trip planned with the token is saved to the account")
    check(len(c.get("/api/trips", headers=bearer(tok)).json()) == 1, "saved trips listed with the token")
    exp = c.get("/api/profile/export", headers=bearer(tok))
    check(exp.status_code == 200 and "scrypt$" not in exp.text, "data download works with the token")

    # visitor ID from the page instead of a cookie
    vid = "ab" * 16
    c.post("/api/visits", json={"path": "/"}, headers={**UA, "X-Visitor-Id": vid})
    c.post("/api/auth/signup", json={"name": "Boss", "email": "boss@example.com", "password": "Boss-pass-2026"}, headers=TOKEN_MODE)
    with db_session() as db:  # the owner has proved the address (signed in with Google before)
        db.scalar(select(User).where(User.email == "boss@example.com")).email_verified = True
    boss = c.post("/api/auth/login", json={"email": "boss@example.com", "password": "Boss-pass-2026"}, headers=TOKEN_MODE).json()["session_token"]
    rows = c.get("/api/admin/visits", headers=bearer(boss)).json()["rows"]
    check(any(r["visitor"] == vid[:8] for r in rows), "the page's own visitor ID is used when cookies can't cross sites")
    check(c.get("/api/admin/summary", headers=bearer(tok)).status_code == 403, "admin panel still refuses non-admins")

    # password change hands over a new token and revokes the old one
    r = c.post("/api/profile/password", json={"current_password": "Asha-pass-2026", "new_password": "Asha-pass-2027"}, headers=bearer(tok))
    new = r.json().get("session_token") if r.status_code == 200 else None
    check(bool(new) and new != tok, "password change returns a fresh token")
    check(c.get("/api/auth/me", headers=bearer(tok)).status_code == 401 and c.get("/api/auth/me", headers=bearer(new)).status_code == 200,
          "old token stops working, new one works")
    check(c.post("/api/auth/logout", headers=bearer(new)).status_code == 204 and c.get("/api/auth/me", headers=bearer(new)).status_code == 401,
          "log-out revokes the token")

    # Google sign-in in token mode: token arrives in the URL fragment of the return address
    async def fake_exchange(code: str, verifier: str) -> dict:
        return fake_exchange.claims

    g.exchange_code = fake_exchange
    with TestClient(app) as browser:  # top-level navigation to the API does keep its own cookies
        r = browser.get("/api/auth/google/start", params={"next": "/profile", "mode": "token"}, follow_redirects=False)
        q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
        fake_exchange.claims = {"iss": "https://accounts.google.com", "aud": "test.apps.googleusercontent.com", "exp": int(time.time()) + 600,
                                "nonce": q["nonce"], "sub": "g-42", "email": "meera@gmail.com", "email_verified": True, "name": "Meera"}
        loc = browser.get("/api/auth/google/callback", params={"code": "x", "state": q["state"]}, follow_redirects=False).headers["location"]
    base, _, frag = loc.partition("#")
    gtok = frag.removeprefix("wf_token=")
    check(base == f"{SITE}/wayfinder-ai-travel-planner/profile" and bool(gtok), "Google sign-in returns to the GitHub Pages site with the token in the fragment")
    check(c.get("/api/auth/me", headers=bearer(gtok)).json().get("email") == "meera@gmail.com", "that token signs the Google user in")

# hosted Postgres addresses
check(normalize_db_url("postgresql://u:p@ep-x.neon.tech/db?sslmode=require") == "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require",
      "Neon's postgresql:// address uses the psycopg driver")
check(normalize_db_url("postgres://u:p@h/db").startswith("postgresql+psycopg://"), "old-style postgres:// address too")
check(normalize_db_url("sqlite:///./data/wayfinder.db") == "sqlite:///./data/wayfinder.db", "SQLite address unchanged")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
