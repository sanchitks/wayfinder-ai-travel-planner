"""Google sign-in tests. Google's token endpoint is replaced by a stand-in that returns ID-token
claims; everything else (state cookie, PKCE, claim checks, account linking, database) is real.
Uses a throwaway database.

    cd backend && .venv/Scripts/python google_auth_test.py
"""

import base64
import hashlib
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TMP = Path(tempfile.mkdtemp()) / "test.db"
os.environ.update({
    "DATABASE_URL": f"sqlite:///{TMP.as_posix()}",
    "COOKIE_SECURE": "false",  # the test client talks plain http
    "GOOGLE_CLIENT_ID": "test-client.apps.googleusercontent.com",
    "GOOGLE_CLIENT_SECRET": "test-secret",
    "FRONTEND_URL": "http://localhost:3000",
})

from fastapi.testclient import TestClient  # noqa: E402

import app.google_auth as g  # noqa: E402
from app.main import app  # noqa: E402

failures = 0


def check(cond: bool, label: str) -> None:
    global failures
    print(("[ok]   " if cond else "[FAIL] ") + label)
    failures += 0 if cond else 1


GOOGLE_USER = {"sub": "1098765432101234567890", "email": "Meera.Iyer@gmail.com", "email_verified": True,
               "name": "Meera Iyer", "picture": "https://lh3.googleusercontent.com/a/photo"}
fake = {"claims": {}, "verifier": None}


async def fake_exchange(code: str, verifier: str) -> dict:
    fake["verifier"] = verifier
    return dict(fake["claims"])


g.exchange_code = fake_exchange


def start(client: TestClient, next_path: str | None = None) -> dict:
    r = client.get("/api/auth/google/start", params={"next": next_path} if next_path else None, follow_redirects=False)
    loc = urlparse(r.headers["location"])
    return {"status": r.status_code, "host": loc.netloc, "q": {k: v[0] for k, v in parse_qs(loc.query).items()}}


def claims_for(q: dict, **over) -> dict:
    return {"iss": "https://accounts.google.com", "aud": os.environ["GOOGLE_CLIENT_ID"], "exp": int(time.time()) + 3600,
            "nonce": q["nonce"], **GOOGLE_USER, **over}


def callback(client: TestClient, state: str, code: str = "auth-code") -> str:
    r = client.get("/api/auth/google/callback", params={"code": code, "state": state}, follow_redirects=False)
    return r.headers.get("location", "")


def sign_in(client: TestClient, next_path: str | None = None, **over) -> str:
    s = start(client, next_path)
    fake["claims"] = claims_for(s["q"], **over)
    return callback(client, s["q"]["state"])


with TestClient(app) as a, TestClient(app) as b, TestClient(app) as c:
    check(a.get("/api/auth/providers").json() == {"google": True}, "providers endpoint reports Google as set up")

    s = start(a, "/profile")
    q = s["q"]
    check(s["status"] == 302 and s["host"] == "accounts.google.com", "start redirects to Google")
    check(q["client_id"] == os.environ["GOOGLE_CLIENT_ID"] and q["redirect_uri"].endswith("/api/auth/google/callback")
          and q["scope"] == "openid email profile" and q["code_challenge_method"] == "S256", "request asks for openid/email/profile with PKCE (S256)")
    check(bool(a.cookies.get("wf_oauth_state")), "one-time state is bound to the browser with a cookie")

    # login CSRF / replay protection
    check(callback(b, q["state"]).endswith("/login?error=google_state"), "callback from a different browser is refused")
    check(callback(a, "forged-state").endswith("/login?error=google_state"), "unknown state is refused")
    loc = a.get("/api/auth/google/callback", params={"error": "access_denied"}, follow_redirects=False).headers["location"]
    check(loc.endswith("/login?error=google_cancelled"), "pressing Cancel at Google returns a friendly error")

    # first sign-in creates the account
    s = start(a, "/profile")
    fake["claims"] = claims_for(s["q"])
    loc = callback(a, s["q"]["state"])
    check(loc == "http://localhost:3000/profile", "successful sign-in returns to the requested page")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(fake["verifier"].encode()).digest()).rstrip(b"=").decode()
    check(challenge == s["q"]["code_challenge"], "PKCE verifier sent to Google matches the challenge")
    me = a.get("/api/auth/me").json()
    check(me.get("email") == "meera.iyer@gmail.com" and me["name"] == "Meera Iyer", "account created from the Google profile")
    check(me["linked_providers"] == ["google"] and me["has_password"] is False and me["avatar_url"].startswith("https://lh3"), "Google identity linked, photo saved, no password")
    check(callback(a, s["q"]["state"]).endswith("/login?error=google_state"), "a used state can't be replayed")
    check(c.post("/api/auth/login", json={"email": "meera.iyer@gmail.com", "password": "anything-1"}).status_code == 401, "Google-only account can't be entered with a password")

    # returning user: same account, no duplicate
    first_id = me["id"]
    loc = sign_in(b)
    check(loc == "http://localhost:3000/" and b.get("/api/auth/me").json()["id"] == first_id, "signing in again reuses the same account")

    # claim checks
    check(sign_in(c, email_verified=False).endswith("error=google_unverified"), "unverified Google email refused")
    check(sign_in(c, aud="someone-elses-client").endswith("error=google_failed"), "token for another app refused")
    check(sign_in(c, nonce="wrong").endswith("error=google_failed"), "nonce mismatch refused")
    check(sign_in(c, exp=int(time.time()) - 3600).endswith("error=google_failed"), "expired token refused")
    check(sign_in(c, iss="https://evil.example").endswith("error=google_failed"), "wrong issuer refused")

    # existing email/password account gets linked, not duplicated
    c.post("/api/auth/signup", json={"name": "Ravi", "email": "ravi@gmail.com", "password": "Ravi-pass-2026"})
    ravi_id = c.get("/api/auth/me").json()["id"]
    c.post("/api/auth/logout")
    loc = sign_in(c, sub="2222", email="ravi@gmail.com", name="Ravi K")
    me_c = c.get("/api/auth/me").json()
    check(me_c["id"] == ravi_id and me_c["linked_providers"] == ["google"] and me_c["has_password"], "Google links to the existing account with that email")
    check(loc == "http://localhost:3000/", "existing users go to the planner, new users to their profile")

    # Google-only user can set a password, and delete with typed confirmation
    check(a.post("/api/profile/password", json={"new_password": "Meera-pass-2026"}).status_code == 204, "Google-only user can set a password without a current one")
    check(c.post("/api/auth/login", json={"email": "meera.iyer@gmail.com", "password": "Meera-pass-2026"}).status_code == 200, "...and then log in with it")
    d = TestClient(app)
    sign_in(d, sub="3333", email="new.person@gmail.com", name="New Person")
    check(d.post("/api/profile/delete", json={"confirm": "nope"}).status_code == 400, "Google-only deletion needs typed DELETE")
    check(d.post("/api/profile/delete", json={"confirm": "DELETE"}).status_code == 204, "Google-only account deleted")

    con = sqlite3.connect(TMP)
    rows = con.execute("select provider, subject, email from oauth_accounts order by id").fetchall()
    users = con.execute("select email, password_hash = '' from users order by id").fetchall()
    con.close()
    check(rows == [("google", "1098765432101234567890", "meera.iyer@gmail.com"), ("google", "2222", "ravi@gmail.com")],
          "oauth_accounts table holds one row per linked Google identity (deleted one removed)")
    check(("new.person@gmail.com", 1) not in users and len(users) == 2, "users table has no duplicates")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
