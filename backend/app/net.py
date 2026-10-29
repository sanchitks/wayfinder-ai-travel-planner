"""The visitor's real IP address, also when the site runs behind a proxy or load balancer.

Behind a proxy (Nginx, Render, Railway, Cloudflare...) every request seems to come from the
proxy, which passes the real address in the X-Forwarded-For header. That header is easy to fake,
so it is only believed when the request actually arrives from an address listed in
TRUSTED_PROXIES; we then take the right-most address that isn't one of our own proxies.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from fastapi import Request

from .config import get_settings


@lru_cache
def _trusted(spec: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    nets = []
    for part in spec.split(","):
        part = part.strip()
        if part:
            try:
                nets.append(ipaddress.ip_network(part, strict=False))
            except ValueError:
                pass  # ignore typos rather than fail every request
    return tuple(nets)


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _in(ip: str, nets: tuple) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    nets = _trusted(get_settings().trusted_proxies)
    if not nets or not _in(peer, nets):
        return peer  # direct connection, or an untrusted sender: ignore forwarded headers
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):  # nearest hop first; skip our own proxies
        if not _in(hop, nets):
            return hop if _is_ip(hop) else peer
    return hops[0] if hops and _is_ip(hops[0]) else peer
