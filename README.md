# Wayfinder: AI Travel Planning Multi-Agent System

An implementation of the *AI Travel Planning Multi-Agent System* PRD (v1.0). An Orchestrator agent talks to the traveler and sends work to three worker agents (Logistics, Accommodation, Experience). They search travel inventory in parallel. The Orchestrator then combines their results into one bookable itinerary, tailored to the traveler's persona and budget.

![Wayfinder landing page](docs/screenshots/landing.jpg)

**Built with:** Next.js 16 + React 19 + TypeScript (frontend) · Python FastAPI + LangGraph (backend) · Claude via OpenRouter (agents) · SQLAlchemy + SQLite (accounts) · Leaflet + OSRM (maps).

**Highlights**
- **Four AI agents working in parallel:** an Orchestrator plans the trip, and Logistics, Accommodation and Experience agents work on it at the same time. Progress shows live, and a chat request such as "find a cheaper hotel" re-runs only the agent it concerns.
- **Real data:**
  - live flight fares in rupees (Ignav) and Indian Railways train options;
  - real hotels with live prices from Agoda, Booking.com and more (Xotelo / TripAdvisor);
  - real sights (Wikipedia) and restaurants (OpenStreetMap), with pure-veg, Jain and non-veg diets;
  - road routes on a Google-Maps-style map.
- **Accounts:** email or Google sign-in, an editable profile that pre-fills new trips, trips saved automatically, and "Download my data".
- **Admin panel:** visitor analytics, customer records (passwords never shown) and CSV export.
- **Responsive:** phones, tablets and desktops, with light and dark themes.

| Agents at work | Itinerary |
|---|---|
| ![Agents planning in parallel](docs/screenshots/agents-working.jpg) | ![Compiled itinerary](docs/screenshots/itinerary.jpg) |
| **Hotels with live prices** | **Map with real road routes** |
| ![Hotel options with live seller prices](docs/screenshots/hotels.jpg) | ![Map tab](docs/screenshots/map.jpg) |
| **Day by day** | **Popular destinations** |
| ![Day-by-day plan](docs/screenshots/day-by-day.jpg) | ![Destination picker](docs/screenshots/destinations.jpg) |

<p align="center"><img src="docs/screenshots/phone.jpg" alt="Wayfinder on a phone" width="260"></p>

## Localized for India

Wayfinder is built for travelers based in India:

- **Rupees everywhere.** Prices are in INR with Indian digit grouping (₹1,50,000) and en-IN dates. The budget slider runs on a log scale from ₹5,000 to ₹10 lakh.
- **Trains as well as flights.** On domestic routes the Logistics agent compares Indian Railways trains with flights: Vande Bharat, Shatabdi, Rajdhani, Duronto, Superfast and Mail, in classes SL, 3A, 2A, 1A, CC and EC. It ranks them on door-to-door time, so an overnight AC train can beat a flight. Each persona has its preferred classes. In chat, "go by train" or "take Vande Bharat" switches modes.
- **Indian destinations and venues.** About 60 Indian cities are built in, each with its airport, railway station, price level and region (beach, desert, hills, Himalaya, heritage, metro). Business travelers can stay near venues such as Bharat Mandapam, BKC, Whitefield and HITEC City.
- **Indian stays and food.** Hotel types include hostels, homestays, heritage havelis and resorts. Places include forts, ghats, aarti, gurdwara langar and thali houses. Vegetarian, pure-veg and Jain options are supported, and a Jain or pure-veg preference restricts every planned meal.
- **Seasonal advice.** Plans include warnings for the monsoon (Jun–Sep) on beaches, summer heat in Rajasthan, winter in the hills, and altitude acclimatisation for Leh. They also include IRCTC booking-window tips.
- **Indian market settings for live APIs.** Amadeus, Skyscanner and Booking.com are queried in INR for the Indian market, and Google Places with region IN. Google always supplies restaurants because Yelp's coverage in India is thin.
- **International trips from India** (Dubai, Bangkok, Singapore…) still work, priced in INR, with flights only.

**Live hotel prices without a key.** For 43 popular destinations (34 in India, plus Dubai, Bangkok, Singapore, London, Paris and others), hotels come from **Xotelo** (`backend/app/providers/xotelo.py`), a free, keyless API over TripAdvisor data. It provides real hotels with photos, TripAdvisor ratings and review counts. The agent then fetches **live nightly prices from Booking.com, Agoda, Trip.com, Vio.com and hotel-direct sites** for its top 10 candidates and ranks on those prices; hotels without availability for your dates are dropped. Each destination's TripAdvisor location key was checked by confirming its hotels sit near the city. To be light on the free service, usage is one list call per city (cached 6 h) plus about 10 rate calls per plan (cached 30 min, max 4 in parallel). If Xotelo is down or a city isn't covered, the agent falls back to the OpenStreetMap hotels below.

**Real hotels for any other city.** When neither a Booking.com key nor a Xotelo city key is available, the Accommodation agent loads real properties from OpenStreetMap through Nominatim (`backend/app/providers/osm_hotels.py`). The name, type, address, map location and any phone or website listed are real. The nightly price and, unless OSM records it, the star class are estimates; the UI marks them with "≈"/"~" and "est.". Guest ratings are never invented. Searches are bounded to the destination, sent at most once per second to follow Nominatim's usage policy, and cached for 6 hours per city.

**Real sights and restaurants without a key.** Without a Google Places key, the Experience agent uses real places (`backend/app/providers/open_places.py`):
- **Sights come from Wikipedia geosearch.** Each has exact coordinates, a photo and a one-line description. Popularity is how many Wikipedia language editions cover the place (Wikidata sitelinks).
- **Restaurants and cafes come from OpenStreetMap.** Diet tags and names identify pure-veg and Jain kitchens. If too few are confirmed, the plan says so in the stop's note.
- **Not everything is real data.** Ticket prices and restaurant price levels are estimates. Neither source has ratings, so none are shown.

**Map.** The Map tab works like Google Maps:
- **Base maps:** street, satellite (with road and place labels) and terrain, all Esri tiles with no key.
- **Real road routes:** drive or walk, routed by OSRM over OpenStreetMap roads through the `POST /api/routes` endpoint. Results are cached, and no more than 2 requests to the routing servers run at once. Times exclude live traffic.
- **Route list:** each day's stops with the travel time between them.
- **Google Maps links:** popups have "Directions" and "Google Maps" buttons, and each day's full route opens in Google Maps through its free, keyless URL scheme.

**Theme.** The design uses a "Lotus" palette (lotus pink with leaf green), with Cormorant Garamond headings and Titillium Web body text. It has a light and a dark version; light is the default, and a Light / Dark / Match-device switch sits in the header. Colours are CSS variables at the top of `frontend/app/globals.css`. Destination and hero photos in `frontend/public/photos` come from Wikimedia Commons under CC BY / CC BY-SA licences. Their credits, which those licences require, are in `frontend/lib/photos.ts` and appear in the site footer and on each photo.

IRCTC has no public API, so train options use sample data modelled on distance and typical class fares. They are labelled "Sample" and link to IRCTC for live seats and booking.

```
frontend/   Next.js 16 (App Router, React 19, TypeScript, Leaflet)
backend/    Python FastAPI + LangGraph + Anthropic SDK (Claude Opus 5.5)
```

## Accounts and saved trips

Visitors can sign up and log in, at `/signup` and `/login`, and edit their profile at `/profile`. Profile details include name, phone, home city, usual travel style, budget, diet and interests. Those preferences pre-fill the trip form. While you're logged in, every trip you plan is saved automatically and updated as you refine it. Saved trips can be reopened from the profile; `/?trip=<id>` links open a single trip. A plan made while logged out can be saved by logging in from the "Log in to save this trip" link.

- **Database.** SQLAlchemy with SQLite by default: `backend/data/wayfinder.db`, created on first start and git-ignored. For PostgreSQL, set `DATABASE_URL=postgresql+psycopg://user:pass@host/db` in `backend/.env` and `pip install psycopg`. Tables: `users`, `login_sessions`, `trips` (`backend/app/db.py`).
- **Security** (`backend/app/auth.py`).
  - **Passwords** are salted scrypt hashes; plain passwords are never stored.
  - **Logins** use an HttpOnly, SameSite=Lax cookie holding a random token. Only its SHA-256 is stored.
  - **Repeated failed logins** are rate-limited.
  - **Changing your password** signs out your other devices.
  - **Saved trips** are private to their owner.
  - **Account deletion** removes the user's trips and sessions too.
  - **HTTPS:** when you serve the site over HTTPS, set `COOKIE_SECURE=true`.
- **Google sign-in** (`backend/app/google_auth.py`). "Continue with Google" uses the OAuth 2.0 authorization-code flow with PKCE, a browser-bound `state` and a `nonce`.
  - **Token checks:** the ID token's issuer, audience, expiry and verified email are checked before anyone is signed in.
  - **Accounts:** a Google identity creates a user, or links to the existing user with the same email. The link is stored in the `oauth_accounts` table.
  - **Setup:** enter credentials as described in [KEYS.md](KEYS.md#google-sign-in-continue-with-google). Until then the button shows as not set up.
  - **No password needed:** Google-only users can add a password later in Security, and they delete their account by typing DELETE.
- **Tests.** Both run against a throwaway database:
  - `cd backend && .venv/Scripts/python auth_test.py` covers the account API.
  - `google_auth_test.py` covers the Google flow, with Google's token response simulated.

## Admin panel

`/admin` is for accounts whose email is listed in `ADMIN_EMAILS` in `backend/.env`. Separate several emails with commas. Admins see an "Admin panel" link in the avatar menu.

- **Overview.** Visitors and page views today and over the last 7 days, customer and trip counts, and a daily trend chart (7, 30 or 90 days) with a hover tooltip and a table view. It also lists top pages, popular destinations, devices, browsers, and the websites visitors came from.
- **Visits.** Every page view: time (IST), the customer if signed in (otherwise an anonymous visitor ID), page, device, browser and OS, referring site, and IP address with its last part hidden. It's searchable and pages through 50 at a time.
- **Customers.** Name, email, phone, home city, travel style, budget, diet and interests, sign-in methods, trips, visits, last seen and joined date.
- **Passwords are never shown or sent.** Customers with a password show `••••••••`; Google-only customers show "None (Google)".
- **Trips.** Every saved trip with its customer.
- **CSV export.** Each table can be exported to CSV for Excel or Google Sheets.

**How visits are recorded.** The website records page views through `POST /api/visits` (`backend/app/admin.py`), into the `visits` table.
- Each browser gets a random visitor ID cookie (`wf_vid`).
- Bots and automated browsers are skipped.
- Admin pages aren't counted.
- Records older than `VISIT_RETENTION_DAYS` (default 365) are deleted when the server starts.
- If a customer deletes their account, their visits stay but are no longer linked to them.
- The landing-page footer tells visitors what's recorded.
- Tests: `backend/admin_test.py`.

## Privacy

- **Privacy Policy** at `/privacy`, linked from the site footer and the sign-up page.
  - It explains, in plain language, what's collected, every cookie, which outside services receive what, how long data is kept, and how to see, correct, download or delete it.
  - Its contact email comes from `PRIVACY_CONTACT_EMAIL` in `backend/.env`.
  - It's a starting point written for India's Digital Personal Data Protection Act, 2023. Have it reviewed before a public launch.
- **Download my data** (Profile → Security, or `GET /api/profile/export`). A JSON file with the customer's profile, saved trips including full itineraries, sign-in methods and recorded visits. It never includes the password or its hash.
- **Real visitor IPs behind a proxy.** When hosted behind Nginx, Render, Railway, Cloudflare and similar, list the proxy addresses or ranges in `TRUSTED_PROXIES`. Then `X-Forwarded-For` is used for the visit log and login rate limiting (`backend/app/net.py`). It's ignored from anyone else, so visitors can't fake it.

## Quick start

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

Or run each piece by hand:

```bash
# backend
cd backend
uv venv --python 3.14 .venv && uv pip install --python .venv -r requirements.txt
cp .env.example .env            # optional - add keys for live data / Claude
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000   # (bin/ on macOS/Linux)

# frontend
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

**API keys:** see [KEYS.md](KEYS.md) for step-by-step sign-up, then run `powershell -ExecutionPolicy Bypass -File setup-keys.ps1` to enter and verify them.

**No keys are required.** Each integration falls back on its own. If no LLM key is set, the agents decide with persona-weighted heuristics and a keyword intent parser. If a travel API key is missing or a call fails, that agent uses deterministic sample inventory, which the UI labels as "Sample". Adding a key switches on that integration only.

## How it maps to the PRD

| PRD requirement | Where |
|---|---|
| Four personas that adapt search, ranking and tone | `backend/app/personas.py`: cabin, stop/layover limits, star range, amenities, budget split, pace, meal times, tone |
| Next.js frontend | `frontend/app`, `frontend/components` |
| FastAPI async backend | `backend/app/main.py`, which streams Server-Sent Events |
| LangGraph orchestration | `backend/app/agents/graph.py` |
| Claude Opus 5.5 via OpenRouter with fallback routing | `backend/app/llm.py`: Anthropic SDK pointed at OpenRouter's Anthropic-compatible endpoint, with an ordered model fallback chain. A direct Claude API mode is also included. |
| Amadeus (test) + Skyscanner via RapidAPI | `backend/app/providers/flights.py`: both queried in parallel and merged |
| Indian Railways (India localization) | `backend/app/providers/trains.py`; India data in `backend/app/india.py` |
| Booking.com via RapidAPI | `backend/app/providers/hotels.py` |
| Google Places + Yelp Fusion | `backend/app/providers/places.py` |
| Orchestrator: gather constraints, delegate, compile | `agents/orchestrator.py`: `orchestrator_node`, `compile_node` |
| Logistics agent | `agents/logistics.py`: filters by persona, scores, Claude picks from the shortlist, ±1-day savings for flexible dates |
| Accommodation agent | `agents/accommodation.py`: star/kind/amenity filters (e.g. family-friendly pools, business centers), distance to a venue |
| Experience agent | `agents/experience.py`: scoring, **k-means geographic clustering into one cluster per day**, nearest-neighbor routing, meals placed near each day's cluster |
| Hybrid onboarding (chat + calendar pickers + budget slider) | `components/Onboarding.tsx` |
| Real-time agent loading states | `components/ChatPanel.tsx` (`AgentBoard`) and the planning view in `ItineraryPanel.tsx` |
| Split-screen chat + interactive itinerary | `app/page.tsx`: overview, day-by-day timeline, flights, stays, Leaflet map, budget meter |
| Surgical refinement | The Orchestrator re-runs **only** the agents a request affects. Example: "Find a cheaper hotel" re-runs only Accommodation, because state is checkpointed per session. |

### The graph

```
START → orchestrator ─┬─▶ logistics ─────┐
                      ├─▶ accommodation ─┼─▶ compile → END
                      ├─▶ experience ────┘
                      └─▶ (no workers: question / selection) ─▶ compile
```

The Orchestrator turns each message into structured updates (trip-brief changes plus flight, hotel and experience preferences) and a set of target agents. With Claude this uses structured outputs. It falls back to plain JSON prompting if the gateway rejects structured outputs, and to keyword heuristics if there is no LLM at all. `compile` lines the day plan up with the real flight times (it re-times the arrival day and trims the departure day), totals the costs against the budget, lists what changed since the previous version, and writes the reply in the persona's tone.

### API

| Endpoint | Purpose |
|---|---|
| `POST /api/plan` | `{request: TripRequest, message?}`. SSE stream of `session`, `agent`, `message`, `itinerary`, `done` events |
| `POST /api/refine` | `{session_id, message}`. Surgical change, same stream |
| `POST /api/select` | `{session_id, kind: "flight"\|"hotel", id}`. Swap in an alternative, no new search |
| `GET /api/health` | LLM mode and which sources are live or using sample data |
| `GET /api/personas` | Persona catalog |

Interactive docs are at http://localhost:8000/docs.

## Testing

```bash
cd backend && .venv/Scripts/python smoke_test.py
```

This plans a trip for each persona through the real HTTP API. It then checks that "Find a cheaper hotel" re-runs only the Accommodation agent and returns a cheaper hotel, and that selecting an alternative flight swaps it in without starting a new search.

Accounts, Google sign-in and the admin panel have their own tests, each using a throwaway database:

```bash
cd backend
.venv/Scripts/python auth_test.py          # sign-up, login, profile, saved trips, privacy between users
.venv/Scripts/python google_auth_test.py   # Google sign-in flow (Google's token reply simulated)
.venv/Scripts/python admin_test.py         # visit tracking, admin access, data export, proxy IPs
```

## License

The code is under the [MIT License](LICENSE). The destination photos in `frontend/public/photos` are from Wikimedia Commons under their own Creative Commons licences. Their credits are in `frontend/lib/photos.ts` and on the site.

## Notes and limits

- **Sessions are in memory** (LangGraph `InMemorySaver`), so a backend restart loses them. The UI then re-plans automatically. For production, swap in a persistent checkpointer such as Postgres or SQLite.
- **RapidAPI providers change response shapes often.** The Skyscanner and Booking.com adapters parse defensively and fall back to sample data on any error. Check your provider's current docs and set `*_RAPIDAPI_HOST` if you use a different listing.
- **Amadeus test environment** returns cached, partial inventory, and some routes return nothing. Booking links go to Google Flights and Booking.com searches, because the free tiers don't support booking.
- **Sample flight times ignore time zones.** This matters for trips abroad only, since India has a single time zone. Live Amadeus and Skyscanner data carries real local times.
- **Sample airline and train data.** Sample flights use real Indian and international airline names, and sample trains use real Indian Railways service names, but times, fares and train numbers are generated. Both are always labelled "Sample". Check live fares through the booking links.
- Geocoding uses a built-in city table, then OpenStreetMap Nominatim (free, no key).
