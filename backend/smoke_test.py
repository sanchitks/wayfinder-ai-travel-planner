"""End-to-end smoke test: plans an India-based trip for every persona (plus one
international trip), then runs surgical refinements, all through the real HTTP
API. Run: .venv/Scripts/python smoke_test.py"""

import json
import sys
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.india import format_inr
from app.main import app

client = TestClient(app)


def stream(path: str, body: dict) -> list[dict]:
    events = []
    with client.stream("POST", path, json=body) as r:
        assert r.status_code == 200, r.read()
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def itinerary(events: list[dict]) -> dict | None:
    return next((e["data"] for e in events if e["type"] == "itinerary"), None)


def check(ok: bool, label: str) -> int:
    print(f"[{'ok' if ok else 'FAIL'}] {label}")
    return 0 if ok else 1


def main() -> int:
    print("health:", client.get("/api/health").json())
    assert format_inr(1250000) == "₹12,50,000" and format_inr(999) == "₹999"
    start = date.today() + timedelta(days=45)
    failures = 0
    sessions: dict[str, tuple[str, dict]] = {}
    cases = [
        ("budget", "Delhi", "Goa", 2, 0, 40000, "pure veg food please", None),
        ("luxury", "Mumbai", "Udaipur", 2, 0, 400000, "", None),
        ("business", "Delhi", "Bengaluru", 1, 0, 100000, "", "Whitefield"),
        ("family", "Bengaluru", "Kochi", 2, 2, 150000, "Hotel with a pool. We are Jain.", None),
        ("family", "Mumbai", "Dubai", 2, 1, 300000, "", None),
    ]
    for persona, origin, dest, adults, children, budget, notes, work in cases:
        req = {
            "origin": origin, "destination": dest, "start_date": str(start), "end_date": str(start + timedelta(days=4)),
            "adults": adults, "children": children, "budget": budget, "persona": persona, "interests": ["Food", "Heritage"],
            "flexible_dates": persona == "budget", "work_location": work, "notes": notes,
        }
        events = stream("/api/plan", {"request": req})
        it = itinerary(events)
        errors = [e for e in events if e["type"] == "error" or e.get("status") == "error"]
        if not it or errors:
            failures += check(False, f"{persona} {origin}->{dest}: {errors or 'no itinerary'}")
            continue
        f, h = it["flight"], it["hotel"]
        modes = sorted({x["mode"] for x in [f, *it["flight_alternatives"]]})
        acts = sum(len(d["activities"]) for d in it["days"])
        print(
            f"[ok] {persona:8} {origin}->{dest:9} {f['mode']}: {f['carriers'][0]} {f['cabin']} {format_inr(f['price'])} "
            f"(modes offered {modes}) | {h['name']} {h['stars']}* {format_inr(h['price_per_night'])}/nt | "
            f"{acts} stops | total {format_inr(it['costs']['total'])} of {format_inr(budget)} [{it['costs']['currency']}]"
        )
        failures += check(it["costs"]["currency"] == "INR", "  priced in INR")
        sessions[f"{persona}-{dest}"] = (next(e["session_id"] for e in events if e["type"] == "session"), it)
        if dest == "Kochi":
            meals = [a["place"] for d in it["days"] for a in d["activities"] if a["kind"] == "meal"]
            failures += check(all({"jain", "jain-on-request"} & set(m["tags"]) for m in meals), f"  Jain diet respected in all {len(meals)} meals")
        if dest == "Dubai":
            failures += check(modes == ["flight"], "  international trip offers flights only")
        else:
            failures += check("train" in modes, "  domestic trip offers Indian Railways trains")
        for hl in it["highlights"]:
            print("     -", hl)

    # Surgical refinement: only accommodation should run. (Uses a trip without a "pool"
    # must-have: with real hotel data that requirement can legitimately leave one option.)
    sid, last = sessions["business-Bengaluru"]
    events = stream("/api/refine", {"session_id": sid, "message": "Find a cheaper hotel"})
    ran = {e["agent"] for e in events if e["type"] == "agent" and e["status"] == "working"}
    new = itinerary(events)
    failures += check(
        bool(new) and new["hotel"]["price_per_night"] < last["hotel"]["price_per_night"] and ran == {"orchestrator", "accommodation"},
        f"refine 'cheaper hotel': agents={sorted(ran)} {format_inr(last['hotel']['price_per_night'])} -> "
        f"{format_inr(new['hotel']['price_per_night']) if new else '?'}/nt",
    )

    # Switch transport mode by chat.
    sid, last = sessions["business-Bengaluru"]
    events = stream("/api/refine", {"session_id": sid, "message": "Let's go by train instead"})
    ran = {e["agent"] for e in events if e["type"] == "agent" and e["status"] == "working"}
    new = itinerary(events)
    failures += check(
        bool(new) and new["flight"]["mode"] == "train" and ran == {"orchestrator", "logistics"},
        f"refine 'go by train': agents={sorted(ran)} -> {new['flight']['carriers'][0] if new else '?'} {new['flight']['cabin'] if new else ''}",
    )

    # Picking an alternative in the UI swaps it in without re-searching.
    alt = new["flight_alternatives"][0]
    events = stream("/api/select", {"session_id": sid, "kind": "flight", "id": alt["id"]})
    ran = {e["agent"] for e in events if e["type"] == "agent"}
    picked = itinerary(events)
    failures += check(bool(picked) and picked["flight"]["id"] == alt["id"] and ran == {"orchestrator"},
                      f"select alternative: agents={sorted(ran)} v{picked and picked['version']}")
    print("FAILURES:", failures)
    return failures


if __name__ == "__main__":
    sys.exit(main())
