"""The visitor's real IP address, also when the site runs behind a proxy or load balancer.

Behind a proxy (Nginx, Render, Railway, Cloudflare...) every request seems to come from the
proxy, which passes the real address in the X-Forwarded-For header. That header is easy to fake,
so it is only believed when the request actually arrives from an address listed in
TRUSTED_PROXIES; we then take the right-most address that isn't one of our own proxies.
"""

from __future__ import annotations

import ipaddress
import re
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


def parse_agent(ua: str) -> tuple[str, str, str]:
    """(browser, OS, device) from a User-Agent string."""
    browser = ("Edge" if "Edg/" in ua else "Opera" if "OPR/" in ua or "Opera" in ua else "Samsung Internet" if "SamsungBrowser" in ua
               else "Firefox" if "Firefox/" in ua or "FxiOS" in ua else "Chrome" if "Chrome/" in ua or "CriOS" in ua
               else "Safari" if "Safari/" in ua else "Other")
    os = ("iOS" if re.search(r"iPhone|iPad|iPod", ua) else "Android" if "Android" in ua else "Windows" if "Windows" in ua
          else "macOS" if "Mac OS X" in ua or "Macintosh" in ua else "Linux" if "Linux" in ua else "Other")
    device = ("Tablet" if re.search(r"iPad|Tablet", ua) or ("Android" in ua and "Mobile" not in ua)
              else "Mobile" if re.search(r"Mobi|iPhone|iPod", ua) else "Desktop")
    return browser, os, device


def mask_ip(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if addr.version == 4:
        return ".".join(str(addr).split(".")[:3]) + ".x"
    return ":".join(addr.exploded.split(":")[:3]) + ":x"
