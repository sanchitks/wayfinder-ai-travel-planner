# Getting the API keys

Every key is optional. Whatever is missing falls back to sample data, so add keys in this order of impact. When you have them, run:

```powershell
powershell -ExecutionPolicy Bypass -File setup-keys.ps1
```

The script asks for each key with hidden input, saves it to `backend/.env` (which git ignores), and tests every key. To re-test later, run `cd backend; .venv\Scripts\python check_keys.py`. Restart the backend after changing keys.

| # | Key | Powers | Cost | Worth it? |
|---|---|---|---|---|
| 1 | `OPENROUTER_API_KEY` | Claude Opus 5.5, the AI behind every agent | Pay as you go, roughly ₹25–45 per trip plan (estimate) | **Yes, biggest upgrade** |
| ✓ | `IGNAV_API_KEY` | **Live flight fares in INR** and airline/agency booking links | 1,000 free requests, then ~$2 per 1,000 (≈3–6 per trip plan) | **Configured** |
| – | `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | **"Continue with Google"** on the log-in and sign-up pages | Free | Yes, if you want Google sign-in (steps below) |
| 2 | `GOOGLE_PLACES_API_KEY` | Real sights, temples, restaurants | Free monthly allowance, card required | **Yes** |
| – | *(no key)* | **Live hotel prices, photos & TripAdvisor ratings** via Xotelo for 43 popular destinations | Free | Built in, nothing to set up |
| 3 | `RAPIDAPI_KEY` | Live flights (Skyscanner) and Booking.com hotel listings for *any* city | Free Basic plans, small monthly quotas | Optional now: hotels already have live prices for popular cities |
| – | `YELP_API_KEY` | Extra restaurant reviews | 30-day trial, then paid (~$229/month) | Skip: thin coverage in India |
| – | `AMADEUS_*` | Flights | **No longer available** | See note below |

---

## 1. OpenRouter: Claude Opus 5.5 (the "brains")

1. Sign in at **https://openrouter.ai** (Google sign-in works).
2. **Add credits** at https://openrouter.ai/settings/credits. Claude models aren't free, and US$5–10 is plenty for testing. International cards and some Indian cards work; if yours is declined, try another card.
3. Create a key at **https://openrouter.ai/settings/keys**. **Set a credit limit on the key** (e.g. $5) so it can't overspend.
4. Paste it as `OPENROUTER_API_KEY`. The model is preset to `anthropic/claude-opus-5.5`, falling back to `anthropic/claude-sonnet-5.5`.

**Alternative:** use a Claude API key from **https://platform.claude.com/settings/keys** as `ANTHROPIC_API_KEY`. It's only used when the OpenRouter key is empty.

> Cost estimate: each new plan makes about 5 Claude calls (orchestrator, 3 workers, compile), and each refinement makes 2–3. That's roughly US$0.30–0.50 per plan at Opus 5.5 prices. This is an estimate; check actual usage on your OpenRouter activity page.

## Google sign-in ("Continue with Google")

Free, and no billing account is needed. It takes about 5 minutes.

1. Open **https://console.cloud.google.com** and create a project (e.g. "wayfinder"), or pick an existing one.
2. Go to **Google Auth Platform → Branding** (the old "OAuth consent screen"). Enter an app name ("Wayfinder"), a support email and a developer contact email, then save.
3. Go to **Audience** and choose **External**. While the app is in *Testing*, only the Gmail addresses you add under **Test users** can sign in, so add yours. To let anyone sign in, click **Publish app**. Wayfinder only asks for the basic `openid`, `email` and `profile` scopes, which don't need Google's verification review.
4. Go to **Clients → Create client** and set **Application type: Web application**:
   - **Authorized JavaScript origins:** `http://localhost:3000`
   - **Authorized redirect URIs:** `http://localhost:8000/api/auth/google/callback`. This must match exactly.
5. Copy the **Client ID** and **Client secret** into `backend/.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, or run `setup-keys.ps1`. Then restart the backend. The Google button switches on by itself.

Each Google sign-in creates a Wayfinder account, or links to the existing one with the same verified email. The link is stored in the `oauth_accounts` table, and the user's name and photo are kept on their profile.

**When you put the site online:**
- Add your real address in step 4, e.g. `https://yourdomain.com/api/auth/google/callback`.
- In `backend/.env`, set `GOOGLE_REDIRECT_URI` and `FRONTEND_URL` to the real addresses.
- Add your domain to `CORS_ORIGINS`.
- Keep `COOKIE_SECURE=true`.

## 2. Google Places API (New): real places in India

1. Go to **https://console.cloud.google.com** and create a project (e.g. "wayfinder").
2. **Billing → Link a billing account.** Google requires a card even for free usage. Google offers India-specific pricing; see the "India" price list on the Maps pricing page.
3. **APIs & Services → Library → "Places API (New)" → Enable.** Make sure it's the *(New)* one.
4. **APIs & Services → Credentials → Create credentials → API key.** Then click the key and:
   - *API restrictions* → restrict it to **Places API (New)** only.
   - *Application restrictions*: leave as none for local development; restrict by IP if you deploy.
5. **Protect yourself from surprise bills:** in *APIs & Services → Places API (New) → Quotas*, cap requests per day (e.g. 500). Also add a budget alert under *Billing → Budgets & alerts*.

> Free usage (since March 2025) is counted per SKU each month. Wayfinder requests ratings and price levels, which bill at the **Text Search Enterprise** tier. That tier has **1,000 free requests per month**, and each new trip plan uses about 15. So roughly 60 plans a month are free; beyond that you pay per 1,000 requests (see Google's price list).

## 3. RapidAPI: live flights and hotels

1. Sign up at **https://rapidapi.com**.
2. Open each API and subscribe to its **free Basic plan**:
   - Flights: **Sky Scrapper** (Skyscanner data): https://rapidapi.com/apiheya/api/sky-scrapper
   - Hotels: **Booking COM** (booking-com15): https://rapidapi.com/DataCrawler/api/booking-com15
3. Copy your key from either API's *Code snippets* panel (the `x-rapidapi-key` header). It's one key for all RapidAPI APIs.
4. Paste it as `RAPIDAPI_KEY`.

> RapidAPI listings are run by third parties and their names, hosts and quotas change. If `check_keys.py` reports a failure on a listing you are subscribed to, the host may have moved. Copy the new `x-rapidapi-host` value into `SKYSCANNER_RAPIDAPI_HOST` / `BOOKING_RAPIDAPI_HOST` in `backend/.env`. Free quotas are small, and the flexible-dates option uses 3 flight searches per plan.

## Ignav: live flight fares (configured)

Ignav (https://ignav.com) replaces Amadeus for flights. Searches use market `IN`, so fares come back in rupees as the **total for all travellers**. Each fare is marked verified or unverified. For the flight the agent picks, Wayfinder also fetches **booking links** to the airline's own site (e.g. IndiGo, Air India Express) and to agencies (e.g. Travomint), with each seller's price. Bookings and payments happen on the seller's site; neither Ignav nor Wayfinder issues tickets.

Usage: 1–3 fare searches per plan (3 with flexible dates), plus 1 booking-link lookup, plus 1 airport lookup for cities abroad. Only successful responses are billed: 1,000 free, then about $2 per 1,000.

**Ignav does not provide hotels.** Hotel prices and ratings need the Booking.com key (see RapidAPI below).

## Not available: Amadeus

Amadeus **shut down its free Self-Service developer portal on 17 July 2026**, and new registrations had already been paused. Self-service keys no longer work. The Amadeus adapter is kept only for teams with an **Amadeus Enterprise** contract: set `AMADEUS_BASE_URL=https://api.amadeus.com` plus Enterprise credentials. Everyone else gets live flights from Skyscanner via RapidAPI instead.

## Not available: IRCTC (trains)

IRCTC has no public API, so train options always use realistic sample data and link to IRCTC for live seats and booking.
