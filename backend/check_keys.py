"""Verify the API keys in backend/.env with the cheapest possible call to each
provider. Never prints key values.

Run from the backend folder:  .venv/Scripts/python check_keys.py
"""

from __future__ import annotations

import asyncio
import sys

import anthropic
import httpx

from app.config import Settings

OK, WARN, FAIL, SKIP = "OK  ", "WARN", "FAIL", "--  "


def line(status: str, name: str, detail: str) -> None:
    print(f"[{status}] {name:<22} {detail}")


async def check_openrouter(s: Settings, client: httpx.AsyncClient) -> bool:
    if not s.openrouter_api_key:
        line(SKIP, "OpenRouter (Claude)", "not set")
        return False
    # Key info endpoint: free, consumes no tokens.
    r = await client.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {s.openrouter_api_key}"})
    if r.status_code != 200:
        line(FAIL, "OpenRouter (Claude)", f"key rejected (HTTP {r.status_code}) - copy it again from openrouter.ai/settings/keys")
        return False
    data = r.json().get("data", {})
    limit, usage = data.get("limit"), data.get("usage", 0)
    remaining = "no credit limit set" if limit is None else f"${max(0.0, limit - usage):.2f} of ${limit:.2f} limit left"
    line(OK, "OpenRouter (Claude)", f"key valid, model {s.openrouter_model}; {remaining}")
    if limit is not None and limit - usage <= 0:
        line(WARN, "", "no credit left - add credits at openrouter.ai/settings/credits (Claude is not free)")
    return True


async def check_anthropic(s: Settings) -> bool:
    if not s.anthropic_api_key:
        line(SKIP, "Anthropic (Claude)", "not set" + (" (not needed - OpenRouter is used)" if s.openrouter_api_key else ""))
        return False
    client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key)
    try:
        model = await client.models.retrieve(s.anthropic_model)  # free metadata call
        line(OK, "Anthropic (Claude)", f"key valid, {model.display_name} available")
        if s.openrouter_api_key:
            line(WARN, "", "OpenRouter key is also set, so OpenRouter takes priority")
        return True
    except anthropic.AuthenticationError:
        line(FAIL, "Anthropic (Claude)", "key rejected - create a new one in the Claude Console")
    except anthropic.NotFoundError:
        line(FAIL, "Anthropic (Claude)", f"key valid but model '{s.anthropic_model}' not available to it")
    except anthropic.APIError as exc:
        line(FAIL, "Anthropic (Claude)", f"error: {exc}")
    return False


async def check_ignav(s: Settings, client: httpx.AsyncClient) -> bool:
    if not s.ignav_api_key:
        line(SKIP, "Ignav (flights)", "not set")
        return False
    # Airport lookup = 1 billed request (1,000 free, then ~$2 per 1,000).
    r = await client.get(f"{s.ignav_base_url}/api/airports", params={"q": "DEL", "limit": 1},
                         headers={"X-Api-Key": s.ignav_api_key})
    if r.status_code == 200:
        line(OK, "Ignav (flights)", f"key valid - live fares for market {s.ignav_market} (INR)")
        return True
    msg = {401: "key rejected", 402: "free requests used up - add a payment method at ignav.com",
           403: "key not allowed", 429: "too many requests"}.get(r.status_code, f"HTTP {r.status_code}")
    line(FAIL, "Ignav (flights)", msg)
    return False


async def check_amadeus(s: Settings, client: httpx.AsyncClient) -> bool:
    if not (s.amadeus_client_id and s.amadeus_client_secret):
        line(SKIP, "Amadeus (flights)", "not set - self-service keys were retired in July 2026; Skyscanner covers flights")
        return False
    r = await client.post(
        f"{s.amadeus_base_url}/v1/security/oauth2/token",
        data={"grant_type": "client_credentials", "client_id": s.amadeus_client_id, "client_secret": s.amadeus_client_secret},
    )
    if r.status_code == 200:
        line(OK, "Amadeus (flights)", f"credentials valid at {s.amadeus_base_url}")
        return True
    line(FAIL, "Amadeus (flights)", f"credentials rejected (HTTP {r.status_code}); self-service keys stopped working in July 2026")
    return False


async def check_rapidapi(s: Settings, client: httpx.AsyncClient, name: str, host: str, path: str, params: dict) -> bool:
    if not s.rapidapi_key:
        line(SKIP, name, "not set (needs RAPIDAPI_KEY)")
        return False
    r = await client.get(f"https://{host}{path}", params=params,
                         headers={"x-rapidapi-key": s.rapidapi_key, "x-rapidapi-host": host})
    if r.status_code == 200:
        line(OK, name, f"subscribed and responding ({host})")
        return True
    msg = ""
    try:
        msg = r.json().get("message", "")
    except ValueError:
        pass
    if r.status_code == 403 and "not subscribed" in msg.lower():
        line(FAIL, name, f"key valid but not subscribed - open the API on rapidapi.com and subscribe to the free Basic plan")
    elif r.status_code == 401:
        line(FAIL, name, "RapidAPI key rejected - copy it again from any API's 'Code snippets' panel")
    elif r.status_code == 429:
        line(WARN, name, "monthly free quota used up (HTTP 429)")
    else:
        line(FAIL, name, f"HTTP {r.status_code} {msg[:80]} - the listing may have moved; check *_RAPIDAPI_HOST")
    return False


async def check_google(s: Settings, client: httpx.AsyncClient) -> bool:
    if not s.google_places_api_key:
        line(SKIP, "Google Places", "not set")
        return False
    # Field mask 'places.id' bills at the cheapest Text Search tier.
    r = await client.post(
        "https://places.googleapis.com/v1/places:searchText",
        json={"textQuery": "Gateway of India, Mumbai", "maxResultCount": 1},
        headers={"X-Goog-Api-Key": s.google_places_api_key, "X-Goog-FieldMask": "places.id"},
    )
    if r.status_code == 200:
        line(OK, "Google Places", "key valid and Places API (New) enabled")
        return True
    err = r.json().get("error", {}) if r.headers.get("content-type", "").startswith("application/json") else {}
    reason = err.get("message", "")[:120]
    if "billing" in reason.lower():
        line(FAIL, "Google Places", "billing not enabled on the Cloud project - add a billing account (free monthly usage still applies)")
    elif "not been used" in reason or "disabled" in reason:
        line(FAIL, "Google Places", "enable 'Places API (New)' for this project in the Cloud console")
    else:
        line(FAIL, "Google Places", f"HTTP {r.status_code}: {reason}")
    return False


async def check_yelp(s: Settings, client: httpx.AsyncClient) -> bool:
    if not s.yelp_api_key:
        line(SKIP, "Yelp", "not set (optional - thin India coverage, paid after a 30-day trial)")
        return False
    r = await client.get("https://api.yelp.com/v3/businesses/search", params={"location": "Mumbai", "limit": 1},
                         headers={"Authorization": f"Bearer {s.yelp_api_key}"})
    if r.status_code == 200:
        line(OK, "Yelp", f"key valid ({r.json().get('total', 0)} Mumbai results)")
        return True
    line(FAIL, "Yelp", f"HTTP {r.status_code} - trial may have ended or key is invalid")
    return False


async def main() -> int:
    s = Settings()
    print("Checking keys from backend/.env (values are never printed)\n")
    async with httpx.AsyncClient(timeout=20) as client:
        results = {
            "llm": await check_openrouter(s, client) | await check_anthropic(s),
            "ignav": await check_ignav(s, client),
            "amadeus": await check_amadeus(s, client),
            "skyscanner": await check_rapidapi(s, client, "Skyscanner (flights)", s.skyscanner_rapidapi_host,
                                               "/api/v1/flights/searchAirport", {"query": "Delhi", "locale": "en-IN"}),
            "booking": await check_rapidapi(s, client, "Booking.com (hotels)", s.booking_rapidapi_host,
                                            "/api/v1/hotels/searchDestination", {"query": "Goa"}),
            "google": await check_google(s, client),
            "yelp": await check_yelp(s, client),
        }
    print("\nWhat the app will use:")
    print("  Brains:       " + ("Claude" if results["llm"] else "built-in heuristics (no working Claude key)"))
    live_flights = [n for n in ("ignav", "skyscanner", "amadeus") if results[n]]
    print("  Flights:      " + (f"live ({', '.join(live_flights)})" if live_flights else "sample data")
          + "; trains: sample data (IRCTC has no public API)")
    print("  Hotels:       " + ("live prices (Booking.com)" if results["booking"]
                                else "real properties from OpenStreetMap, estimated prices (no key needed)"))
    print("  Sights/food:  " + ("live (Google Places)" if results["google"] else "sample data"))
    print("\nRestart the backend after changing backend/.env.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except httpx.HTTPError as exc:
        print(f"Network error: {exc}")
        sys.exit(1)
