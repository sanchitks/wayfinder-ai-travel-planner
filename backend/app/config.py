from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables or backend/.env.

    Every external integration is optional: when a key is missing, the matching
    agent falls back to deterministic demo data so the app runs end-to-end
    with zero credentials.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Core intelligence -------------------------------------------------
    # Preferred route (per PRD): Claude via OpenRouter's Anthropic-compatible endpoint.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api"
    openrouter_model: str = "anthropic/claude-opus-5.5"
    # Tried in order when the primary model errors (rate limit, outage, unknown model).
    openrouter_fallback_models: str = "anthropic/claude-sonnet-5.5"

    # Alternative route: the Claude API directly.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"

    # --- Third-party travel inventory -------------------------------------
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""
    amadeus_base_url: str = "https://test.api.amadeus.com"

    # Live flight fares (India market, INR) and airline booking links. https://ignav.com
    ignav_api_key: str = ""
    ignav_base_url: str = "https://ignav.com"
    ignav_market: str = "IN"

    rapidapi_key: str = ""
    skyscanner_rapidapi_host: str = "sky-scrapper.p.rapidapi.com"
    booking_rapidapi_host: str = "booking-com15.p.rapidapi.com"

    google_places_api_key: str = ""
    yelp_api_key: str = ""

    # --- App ---------------------------------------------------------------
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # The interactive API docs at /docs. Turn off in production so the API isn't advertised.
    api_docs: bool = True
    # Reject new passwords that appear in known data breaches (Have I Been Pwned, k-anonymity:
    # only the first 5 characters of the password's SHA-1 ever leave the server).
    check_breached_passwords: bool = True

    # --- Accounts ------------------------------------------------------------
    # SQLite file by default (git-ignored). For PostgreSQL: postgresql+psycopg://user:pass@host/db
    database_url: str = "sqlite:///./data/wayfinder.db"
    session_days: int = 30
    # Set true when the site is served over HTTPS so the login cookie is never sent in clear text.
    cookie_secure: bool = False

    # Google sign-in (OAuth 2.0 / OpenID Connect). Web client from https://console.cloud.google.com/auth/clients
    google_client_id: str = ""
    google_client_secret: str = ""
    # Must be listed exactly under "Authorized redirect URIs" in the Google client.
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"
    # Where to send the browser after Google sign-in.
    frontend_url: str = "http://localhost:3000"

    # --- Admin panel ---------------------------------------------------------
    # Comma-separated emails whose accounts can open /admin.
    admin_emails: str = ""
    # Page-visit records older than this are deleted on startup.
    visit_retention_days: int = 365

    # Behind a proxy/load balancer: its address(es) or ranges, comma-separated (e.g. "10.0.0.0/8").
    # Only then is X-Forwarded-For used for the visitor's IP. Leave empty when not behind a proxy.
    trusted_proxies: str = ""

    # Shown on the Privacy Policy page as the contact for privacy questions and data requests.
    privacy_contact_email: str = ""

    @property
    def admin_email_list(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)
    currency: str = "INR"
    http_timeout_seconds: float = 20.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_mode(self) -> str:
        if self.openrouter_api_key:
            return "openrouter"
        if self.anthropic_api_key:
            return "anthropic"
        return "offline"


@lru_cache
def get_settings() -> Settings:
    return Settings()
