"""Request-level protection for the whole API.

- Security headers on every response (no MIME sniffing, no framing, no referrer, HSTS on HTTPS,
  no caching of account data).
- CSRF guard: a browser always sends Origin on a cross-site POST/PUT/DELETE, so those are refused
  unless they come from the website itself (CORS_ORIGINS). Requests without Origin (curl, servers)
  carry no browser cookies of the victim, so they are let through.
- A cap on request body size.
- `limit(...)`: a small in-memory sliding-window rate limiter used by the routes.

Written as plain ASGI middleware so streamed planning responses (Server-Sent Events) still stream.
"""

from __future__ import annotations

import json
import time
from collections import deque

from fastapi import HTTPException, Request

from .config import get_settings
from .net import client_ip

MAX_BODY = 256 * 1024  # bytes; the largest real request (a trip with notes) is a few KB
_UNSAFE = {b"POST", b"PUT", b"PATCH", b"DELETE"}
_PRIVATE_PREFIXES = ("/api/auth", "/api/profile", "/api/admin", "/api/trips")
_DOCS = ("/docs", "/redoc", "/openapi.json")


def _headers_for(path: str) -> list[tuple[bytes, bytes]]:
    s = get_settings()
    h = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-opener-policy", b"same-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=()"),
    ]
    if not path.startswith(_DOCS):  # the docs page loads its own scripts; everything else is plain data
        h.append((b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"))
    if s.cookie_secure:
        h.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
    if path.startswith(_PRIVATE_PREFIXES):
        h.append((b"cache-control", b"no-store"))
    return h


async def _reject(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path: str = scope.get("path", "")
        headers = dict(scope.get("headers") or [])
        extra = _headers_for(path)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                have = {k.lower() for k, _ in message.get("headers", [])}
                message["headers"] = list(message.get("headers", [])) + [(k, v) for k, v in extra if k not in have]
            await send(message)

        if scope.get("method", "").encode() in _UNSAFE:
            origin = headers.get(b"origin", b"").decode("latin-1")
            if origin and origin not in get_settings().cors_origin_list:
                return await _reject(send_with_headers, 403, "Requests from other websites are not allowed.")
            length = headers.get(b"content-length", b"")
            if length.isdigit() and int(length) > MAX_BODY:
                return await _reject(send_with_headers, 413, "Request is too large.")

        received = 0

        async def capped_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY:  # chunked upload without Content-Length
                    raise HTTPException(413, "Request is too large.")
            return message

        await self.app(scope, capped_receive, send_with_headers)


# ---------- rate limiting ----------
class RateLimiter:
    """At most `count` hits per `window` seconds per key. Memory is bounded: idle keys are dropped."""

    def __init__(self, count: int, window: float, max_keys: int = 50_000):
        self.count, self.window, self.max_keys = count, window, max_keys
        self.hits: dict[str, deque[float]] = {}

    def _recent(self, key: str, now: float) -> deque[float]:
        q = self.hits.get(key)
        if q is None:
            if len(self.hits) >= self.max_keys:
                self._sweep(now)
            q = self.hits[key] = deque()
        while q and now - q[0] >= self.window:
            q.popleft()
        return q

    def _sweep(self, now: float) -> None:
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] >= self.window]:
            del self.hits[k]
        if len(self.hits) >= self.max_keys:  # still full (a flood of distinct keys): start over
            self.hits.clear()

    def blocked(self, key: str) -> bool:
        return len(self._recent(key, time.monotonic())) >= self.count

    def hit(self, key: str) -> None:
        now = time.monotonic()
        self._recent(key, now).append(now)

    def check_and_hit(self, key: str) -> bool:
        """Count this request; False if the limit was already reached."""
        if self.blocked(key):
            return False
        self.hit(key)
        return True

    def reset(self, key: str) -> None:
        self.hits.pop(key, None)


def caller(request: Request) -> str:
    return client_ip(request) or "unknown"


def too_many(message: str = "Too many requests. Please wait a few minutes and try again.") -> HTTPException:
    return HTTPException(429, message)


def limit(limiter: RateLimiter, message: str | None = None):
    """FastAPI dependency: count the request against `limiter` per client address."""

    async def dep(request: Request) -> None:
        if not limiter.check_and_hit(caller(request)):
            raise too_many(message) if message else too_many()

    return dep


# Planning calls paid flight/hotel APIs: keep one visitor from burning the quota.
PLAN_LIMIT = RateLimiter(12, 10 * 60)
REFINE_LIMIT = RateLimiter(60, 10 * 60)
ROUTES_LIMIT = RateLimiter(120, 10 * 60)
VISIT_LIMIT = RateLimiter(240, 10 * 60)
