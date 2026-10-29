"""Admin panel and visit-tracking tests (throwaway database).

    cd backend && .venv/Scripts/python admin_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp()) / "test.db"
os.environ.update({"DATABASE_URL": f"sqlite:///{TMP.as_posix()}", "COOKIE_SECURE": "false",
                   "ADMIN_EMAILS": "Boss@Example.com", "FRONTEND_URL": "http://localhost:3000",
                   "TRUSTED_PROXIES": "10.0.0.0/8", "PRIVACY_CONTACT_EMAIL": "privacy@example.com"})

from fastapi.testclient import TestClient  # noqa: E402

from app.google_auth import link_or_create  # noqa: E402
from app.main import app  # noqa: E402
from app.net import client_ip  # noqa: E402
from starlette.requests import Request  # noqa: E402

failures = 0


def check(cond: bool, label: str) -> None:
    global failures
    print(("[ok]   " if cond else "[FAIL] ") + label)
    failures += 0 if cond else 1


CHROME = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0 Safari/537.36"}
IPHONE = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"}

with TestClient(app) as guest, TestClient(app) as cust, TestClient(app) as boss, TestClient(app) as bot:
    # visits
    r = guest.post("/api/visits", json={"path": "/", "referrer": "https://www.google.com/search?q=trip"}, headers=CHROME)
    check(r.status_code == 204 and bool(guest.cookies.get("wf_vid")), "visit recorded; visitor gets a random ID cookie")
    guest.post("/api/visits", json={"path": "/"}, headers=CHROME)
    guest.post("/api/visits", json={"path": "/signup?next=/x", "referrer": "http://localhost:3000/"}, headers=CHROME)
    bot.post("/api/visits", json={"path": "/"}, headers={"User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"})
    bot.post("/api/visits", json={"path": "/"}, headers={"User-Agent": "Mozilla/5.0 HeadlessChrome/156.0"})

    cust.post("/api/auth/signup", json={"name": "Priya Sharma", "email": "priya@example.com", "password": "Priya-pass-2026"})
    cust.put("/api/profile", json={"name": "Priya Sharma", "phone": "+91 98765 43210", "home_city": "Pune", "persona": "family",
                                   "budget": 90000, "diets": ["Jain"], "interests": ["Heritage"], "bio": "Loves forts"})
    cust.post("/api/visits", json={"path": "/profile"}, headers=IPHONE)
    check(cust.get("/api/auth/me").json()["is_admin"] is False, "customers are not admins")

    # access control
    check(guest.get("/api/admin/summary").status_code == 401, "admin API needs a login")
    check(cust.get("/api/admin/customers").status_code == 403, "ordinary customers are refused (403)")
    boss.post("/api/auth/signup", json={"name": "Owner", "email": "boss@example.com", "password": "Boss-pass-2026"})
    check(boss.get("/api/auth/me").json()["is_admin"] is True, "ADMIN_EMAILS account is an admin (case-insensitive)")
    link_or_create({"sub": "g-1", "email": "google.user@gmail.com", "name": "Google User", "email_verified": True})

    # visits log
    v = boss.get("/api/admin/visits").json()
    paths = [row["path"] for row in v["rows"]]
    check(v["total"] == 3, f"bots and double counts skipped (3 real views, got {v['total']})")
    check("/signup" in paths, "query strings are not stored with the page")
    guest_row = next(row for row in v["rows"] if row["path"] == "/" )
    check(guest_row["referrer"] == "www.google.com/search" and guest_row["browser"] == "Chrome" and guest_row["device"] == "Desktop", "referrer, browser and device recorded")
    check(guest_row["ip"] in ("", "testclient") or guest_row["ip"].endswith(".x") or guest_row["ip"].endswith(":x"), "IP stored with last part hidden")
    own = next(row for row in v["rows"] if row["path"] == "/signup")
    check(own["referrer"] == "", "links from our own pages aren't counted as referrers")
    prof = next(row for row in v["rows"] if row["path"] == "/profile")
    check(prof["customer"]["email"] == "priya@example.com" and prof["device"] == "Mobile" and prof["os"] == "iOS", "signed-in visit linked to the customer")
    check(boss.get("/api/admin/visits", params={"q": "priya"}).json()["total"] == 1, "visits can be searched by customer")

    # customers: details visible, passwords never
    c = boss.get("/api/admin/customers")
    rows = {row["email"]: row for row in c.json()["rows"]}
    p = rows["priya@example.com"]
    check(p["phone"] == "+91 98765 43210" and p["home_city"] == "Pune" and p["diets"] == ["Jain"] and p["visits"] == 1, "customer details visible")
    check(p["password"] == "••••••••" and p["sign_in"] == ["email"], "password shown only as dots")
    check(rows["google.user@gmail.com"]["password"] == "" and rows["google.user@gmail.com"]["sign_in"] == ["google"], "Google-only customer has no password")
    check("scrypt$" not in c.text and "Priya-pass-2026" not in c.text and "password_hash" not in c.text, "no password or hash anywhere in the response")

    # summary
    s = boss.get("/api/admin/summary").json()
    k = s["kpis"]
    check(k["views_today"] == 3 and k["visitors_today"] == 2 and k["customers"] == 3 and k["google_customers"] == 1, "overview numbers add up")
    check(len(s["series"]) == 30 and s["series"][-1]["views"] == 3, "30-day chart data ends today")
    check(dict(s["devices"]) == {"Desktop": 2, "Mobile": 1}, "device split")

    # download my data: everything, but never the password or its hash
    r = cust.get("/api/profile/export")
    data = r.json()
    check(r.status_code == 200 and "attachment" in r.headers.get("content-disposition", ""), "customer can download their data as a file")
    check(data["account"]["phone"] == "+91 98765 43210" and len(data["page_visits"]) == 1 and data["sign_in"]["password_set"] is True, "export has profile, visits and sign-in methods")
    check("scrypt$" not in r.text and "Priya-pass-2026" not in r.text, "export never contains the password or hash")
    check(guest.get("/api/profile/export").status_code == 401, "export needs a login")
    check(guest.get("/api/site-info").json() == {"privacy_contact": "privacy@example.com", "visit_retention_days": 365}, "privacy page facts available")

    # deleting an account keeps its visits, anonymously
    cust.post("/api/profile/delete", json={"password": "Priya-pass-2026"})
    v = boss.get("/api/admin/visits").json()
    check(v["total"] == 3 and all(row["customer"] is None for row in v["rows"] if row["path"] == "/profile"), "deleted customer's visits stay, unlinked from them")


# real visitor IP behind a proxy
def req(peer: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "client": (peer, 1234), "headers": headers, "method": "GET", "path": "/"})

check(client_ip(req("49.36.1.2")) == "49.36.1.2", "direct visitor: their own address")
check(client_ip(req("49.36.1.2", "1.2.3.4")) == "49.36.1.2", "forwarded header from an untrusted sender is ignored (can't be faked)")
check(client_ip(req("10.0.0.5", "49.36.7.8")) == "49.36.7.8", "behind a trusted proxy: the visitor's real address")
check(client_ip(req("10.0.0.5", "6.6.6.6, 49.36.7.8, 10.0.0.9")) == "49.36.7.8", "spoofed left-most entry and inner proxies are skipped")

print("FAILURES:", failures)
sys.exit(1 if failures else 0)
