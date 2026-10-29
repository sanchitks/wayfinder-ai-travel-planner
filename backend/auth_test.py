"""Account tests: sign-up, log-in, profile, saved trips, privacy between users, password change,
rate limiting and account deletion. Uses a throwaway SQLite database, not your real one.

    cd backend && .venv/Scripts/python auth_test.py
"""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.as_posix()}"
os.environ["COOKIE_SECURE"] = "false"  # the test client talks plain http

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

failures = 0


def check(cond: bool, label: str) -> None:
    global failures
    print(("[ok]   " if cond else "[FAIL] ") + label)
    failures += 0 if cond else 1


PASSWORD = "Lotus-trip-2026"
TRIP = {
    "request": {"origin": "Delhi", "destination": "Jaipur", "start_date": "2026-11-28", "end_date": "2026-11-30",
                "adults": 2, "children": 0, "budget": 40000, "persona": "budget", "interests": [], "flexible_dates": False,
                "work_location": None, "notes": ""},
    "message": "",
}


def plan(client: TestClient) -> list[dict]:
    events = []
    with client.stream("POST", "/api/plan", json=TRIP) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


with TestClient(app) as a, TestClient(app) as b:
    # sign-up
    r = a.post("/api/auth/signup", json={"name": "  Asha   Rao ", "email": "Asha@Example.com", "password": PASSWORD})
    check(r.status_code == 201 and r.json()["email"] == "asha@example.com" and r.json()["name"] == "Asha Rao", "sign-up creates the account (email lower-cased, name tidied)")
    cookie = r.headers.get("set-cookie", "")
    check("wf_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie, "login cookie is HttpOnly and SameSite=Lax")
    check(a.get("/api/auth/me").status_code == 200, "signed in right after sign-up")
    check(a.post("/api/auth/signup", json={"name": "X", "email": "asha@example.com", "password": PASSWORD}).status_code == 409, "duplicate email refused")
    check(a.post("/api/auth/signup", json={"name": "X", "email": "x@example.com", "password": "short"}).status_code == 422, "weak password refused")
    check(a.post("/api/auth/signup", json={"name": "X", "email": "not-an-email", "password": PASSWORD}).status_code == 422, "invalid email refused")

    # what the database actually holds
    con = sqlite3.connect(TMP)
    stored_hash = con.execute("select password_hash from users").fetchone()[0]
    token_hash = con.execute("select token_hash from login_sessions").fetchone()[0]
    con.close()
    check(PASSWORD not in stored_hash and stored_hash.startswith("scrypt$"), "password stored only as a salted scrypt hash")
    check(a.cookies.get("wf_session") not in token_hash, "session token stored only as a hash")

    # log out / log in
    check(a.post("/api/auth/logout").status_code == 204 and a.get("/api/auth/me").status_code == 401, "log-out ends the session")
    check(a.post("/api/auth/login", json={"email": "asha@example.com", "password": "wrong-pass-1"}).status_code == 401, "wrong password refused")
    check(a.post("/api/auth/login", json={"email": "ASHA@example.com ", "password": PASSWORD}).status_code == 200, "log-in works (email case/space-insensitive)")

    # profile
    prof = {"name": "Asha Rao", "phone": "+91 98765 43210", "home_city": "Pune", "persona": "family", "budget": 120000,
            "diets": ["Pure veg"], "interests": ["Heritage", "Food"], "bio": "Weekend explorer"}
    r = a.put("/api/profile", json=prof)
    check(r.status_code == 200 and r.json()["home_city"] == "Pune" and r.json()["diets"] == ["Pure veg"], "profile saves")
    check(a.get("/api/auth/me").json()["persona"] == "family", "profile persists")
    check(a.put("/api/profile", json={**prof, "phone": "call me"}).status_code == 422, "bad phone refused")
    check(a.put("/api/profile", json={**prof, "diets": ["Non veg", "Jain"]}).status_code == 422, "Non veg + Jain refused")
    check(a.put("/api/profile", json={**prof, "budget": 100}).status_code == 422, "budget outside ₹5,000-₹10,00,000 refused")

    # trips are saved for signed-in users only
    events = plan(a)
    saved = [e for e in events if e.get("type") == "saved"]
    check(len(saved) == 1, "planning while signed in saves the trip")
    trips = a.get("/api/trips").json()
    check(len(trips) == 1 and trips[0]["title"] == "Delhi → Jaipur" and trips[0]["total"] > 0, "trip appears in the list")
    trip_id = trips[0]["id"]
    full = a.get(f"/api/trips/{trip_id}").json()
    check(full["itinerary"]["request"]["destination"] == "Jaipur", "full itinerary can be reopened")
    guest_events = plan(b)
    check(not any(e.get("type") == "saved" for e in guest_events), "planning while signed out saves nothing")
    guest_session = next(e["session_id"] for e in guest_events if e.get("type") == "session")
    check(b.post("/api/trips/save", json={"session_id": guest_session}).status_code == 401, "saving needs a login")

    # another user can't see it
    b.post("/api/auth/signup", json={"name": "Ravi", "email": "ravi@example.com", "password": PASSWORD})
    r = b.post("/api/trips/save", json={"session_id": guest_session})
    check(r.status_code == 200 and len(b.get("/api/trips").json()) == 1, "a trip planned before logging in can be saved after")
    check(b.post("/api/trips/save", json={"session_id": "no-such-session"}).status_code == 404, "unknown plan can't be saved")
    b.delete(f"/api/trips/{r.json()['trip_id']}")
    check(b.get(f"/api/trips/{trip_id}").status_code == 404, "other users get 404 for someone else's trip")
    check(b.delete(f"/api/trips/{trip_id}").status_code == 404, "other users can't delete it")
    check(b.get("/api/trips").json() == [], "other users' trip lists are separate")

    # password change signs out other browsers
    check(a.post("/api/profile/password", json={"current_password": "nope-123", "new_password": "New-pass-2026"}).status_code == 400, "wrong current password refused")
    other = TestClient(app)
    other.post("/api/auth/login", json={"email": "asha@example.com", "password": PASSWORD})
    check(a.post("/api/profile/password", json={"current_password": PASSWORD, "new_password": "New-pass-2026"}).status_code == 204, "password changed")
    check(a.get("/api/auth/me").status_code == 200, "this browser stays signed in")
    check(other.get("/api/auth/me").status_code == 401, "other browsers are signed out")
    check(other.post("/api/auth/login", json={"email": "asha@example.com", "password": PASSWORD}).status_code == 401, "old password no longer works")

    # delete trip, delete account
    check(a.delete(f"/api/trips/{trip_id}").status_code == 204 and a.get("/api/trips").json() == [], "trip deleted")
    plan(a)
    check(a.post("/api/profile/delete", json={"password": "wrong-pass-1"}).status_code == 400, "account deletion needs the password")
    check(a.post("/api/profile/delete", json={"password": "New-pass-2026"}).status_code == 204, "account deleted")
    con = sqlite3.connect(TMP)
    left = con.execute("select (select count(*) from users where email='asha@example.com'), (select count(*) from trips), (select count(*) from login_sessions where user_id not in (select id from users))").fetchone()
    con.close()
    check(left == (0, 0, 0), "account, trips and sessions removed from the database")

    # brute force
    codes = [b.post("/api/auth/login", json={"email": "ravi@example.com", "password": f"guess-{i}x"}).status_code for i in range(10)]
    check(429 in codes, f"repeated wrong passwords get rate-limited ({codes.count(401)} tries, then 429)")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
