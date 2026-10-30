"""Security hardening tests (throwaway database).

    cd backend && .venv/Scripts/python security_test.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp()) / "test.db"
os.environ.update({"DATABASE_URL": f"sqlite:///{TMP.as_posix()}", "COOKIE_SECURE": "true",
                   "CORS_ORIGINS": "https://site.example", "ADMIN_EMAILS": "", "CHECK_BREACHED_PASSWORDS": "false"})

from fastapi.testclient import TestClient  # noqa: E402

import app.auth as auth  # noqa: E402
from app.main import app  # noqa: E402
from app.security import PLAN_LIMIT, RateLimiter  # noqa: E402

failures = 0


def check(cond: bool, label: str) -> None:
    global failures
    print(("[ok]   " if cond else "[FAIL] ") + label)
    failures += 0 if cond else 1


SITE = {"Origin": "https://site.example"}
EVIL = {"Origin": "https://evil.example"}
CHROME = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0 Safari/537.36"}
PHONE = {"User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0 Mobile Safari/537.36"}

# https so the Secure session cookie is kept by the test client
with TestClient(app, base_url="https://testserver") as c, TestClient(app, base_url="https://testserver") as other:
    # --- headers ---
    h = c.get("/api/health").headers
    check(h.get("x-content-type-options") == "nosniff" and h.get("x-frame-options") == "DENY", "nosniff + no framing on every response")
    check("default-src 'none'" in h.get("content-security-policy", "") and h.get("referrer-policy") == "no-referrer", "strict CSP and no referrer")
    check(h.get("strict-transport-security", "").startswith("max-age=31536000"), "HSTS when served over HTTPS")
    check("no-store" in c.get("/api/auth/me").headers.get("cache-control", ""), "account responses are never cached")

    # --- cross-site requests (CSRF) ---
    r = c.post("/api/auth/signup", json={"name": "Asha", "email": "asha@example.com", "password": "Asha-pass-2026"}, headers=EVIL)
    check(r.status_code == 403, "POST from another website is refused (403)")
    r = c.post("/api/auth/signup", json={"name": "Asha", "email": "asha@example.com", "password": "Asha-pass-2026"}, headers={**SITE, **CHROME})
    check(r.status_code == 201, "POST from the website itself works")
    check(c.put("/api/profile", json={"name": "Hacked"}, headers=EVIL).status_code == 403, "PUT from another website is refused")
    check(c.get("/api/auth/me").json()["name"] == "Asha", "...and changed nothing")

    # --- size cap ---
    r = c.post("/api/plan", content=b"{" + b" " * 300_000 + b"}", headers={**SITE, "Content-Type": "application/json"})
    check(r.status_code == 413, "oversized request refused (413)")
    big = c.post("/api/plan", json={"request": {}, "message": "x" * 3000}, headers=SITE)
    check(big.status_code == 422, "over-long planner message refused by validation")

    # --- sessions list / sign out other devices ---
    other.post("/api/auth/login", json={"email": "asha@example.com", "password": "Asha-pass-2026"}, headers={**SITE, **PHONE})
    sessions = c.get("/api/profile/sessions").json()
    check(len(sessions) == 2 and sessions[0]["current"] and not sessions[1]["current"], "both signed-in browsers listed, this one first")
    check(sessions[0]["device"] == "Chrome on Windows (Desktop)" and sessions[1]["device"] == "Chrome on Android (Mobile)", "device names shown")
    check(all(len(s["id"]) == 16 for s in sessions), "sessions named by a short id, never the token")
    check(other.get("/api/auth/me").status_code == 200, "the phone is signed in")
    check(c.delete(f"/api/profile/sessions/{sessions[1]['id']}", headers=SITE).status_code == 204, "end the phone's session")
    check(other.get("/api/auth/me").status_code == 401, "the phone is signed out")
    other.post("/api/auth/login", json={"email": "asha@example.com", "password": "Asha-pass-2026"}, headers=SITE)
    r = c.post("/api/profile/sessions/sign-out-others", headers=SITE).json()
    check(r["signed_out"] == 1 and other.get("/api/auth/me").status_code == 401 and c.get("/api/auth/me").status_code == 200,
          "'sign out everywhere else' keeps only this browser")
    with TestClient(app, base_url="https://testserver") as stranger:
        stranger.post("/api/auth/signup", json={"name": "Eve", "email": "eve@example.com", "password": "Eve-pass-2026"}, headers=SITE)
        check(stranger.delete(f"/api/profile/sessions/{sessions[0]['id']}", headers=SITE).status_code == 404,
              "nobody can end someone else's session")
    check(c.get("/api/auth/me").status_code == 200, "...Asha is still signed in")

    # --- one account guessed at from many addresses ---
    codes = []
    for _ in range(12):
        auth._FAILS.hits.clear()  # as if every attempt came from a different address
        codes.append(other.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong-guess-1"}, headers=SITE).status_code)
    check(codes.count(401) == 10 and codes[-1] == 429, f"per-account lock after 10 wrong passwords from any address ({codes.count(401)} tries)")
    auth._ACCOUNT_FAILS.hits.clear()

    # --- leaked passwords ---
    original = auth.password_breached

    async def always_breached(_pw: str) -> bool:
        return True

    auth.password_breached = always_breached
    r = c.post("/api/auth/signup", json={"name": "Bo", "email": "bo@example.com", "password": "Password-123"}, headers=SITE)
    check(r.status_code == 422 and "breach" in r.json()["detail"], "leaked password refused at sign-up")
    r = c.post("/api/profile/password", json={"current_password": "Asha-pass-2026", "new_password": "Password-123"}, headers=SITE)
    check(r.status_code == 422, "leaked password refused when changing password")
    auth.password_breached = original

    # --- planning is rate-limited (it spends the paid flight API quota) ---
    saved = PLAN_LIMIT.count
    PLAN_LIMIT.count, PLAN_LIMIT.hits = 2, {}
    codes = [c.post("/api/plan", json={"request": {}}, headers=SITE).status_code for _ in range(3)]
    check(codes[:2] == [422, 422] and codes[2] == 429, f"planning limited per visitor ({codes})")
    PLAN_LIMIT.count, PLAN_LIMIT.hits = saved, {}

# --- limiter memory stays bounded ---
rl = RateLimiter(3, 60, max_keys=100)
for i in range(1000):
    rl.hit(f"k{i}")
check(len(rl.hits) <= 100, f"rate limiter memory bounded ({len(rl.hits)} keys)")

# --- live breach check (skipped when offline) ---
os.environ["CHECK_BREACHED_PASSWORDS"] = "true"
auth.get_settings.cache_clear()
try:
    import httpx
    httpx.get("https://api.pwnedpasswords.com/range/00000", timeout=5)
    check(asyncio.run(auth.password_breached("password123")), "live check: 'password123' is known to be leaked")
    check(not asyncio.run(auth.password_breached("Wf-" + os.urandom(12).hex())), "live check: a random password is not")
except httpx.HTTPError:
    print("[skip] breach service unreachable")

print(f"\nFAILURES: {failures}")
sys.exit(1 if failures else 0)
