"""Outbound HTTP clients.

httpx's ``trust_env=True`` turns ``NO_PROXY`` into URL patterns, and one malformed
entry (for example ``[::1]``, which real shells do produce) raises ``InvalidURL``
at client-construction time — a broken environment variable would take the whole
feature down before a single request is made. So skilldesk resolves the proxy
itself, passes it explicitly, and always bypasses it for loopback targets.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

PROXY_ENV_VARS = ("SKILLDESK_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0", ""}
# Bracket the IPv6 literal: "all://::1" is not a valid pattern and raises InvalidURL.
LOOPBACK_MOUNTS = {"all://127.0.0.1": None, "all://localhost": None, "all://[::1]": None}


def resolve_proxy() -> str | None:
    """First configured proxy, most specific variable first."""
    for name in PROXY_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def is_loopback(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in LOOPBACK_HOSTS


def proxy_for(url: str) -> str | None:
    """Loopback never needs a proxy; everything else uses the configured one."""
    if url and is_loopback(url):
        return None
    return resolve_proxy()


def http_client(
    *,
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
    url_hint: str = "",
) -> httpx.Client:
    """An httpx client that cannot be broken by the shell's proxy variables."""
    proxy = proxy_for(url_hint) if url_hint else resolve_proxy()
    options: dict = {
        "timeout": timeout,
        "trust_env": False,
        "mounts": dict(LOOPBACK_MOUNTS),
    }
    if headers:
        options["headers"] = headers
    if proxy:
        options["proxy"] = proxy
    try:
        return httpx.Client(**options)
    except (httpx.InvalidURL, ValueError):
        # A garbage proxy value (or an unusable mount pattern) must degrade to
        # "no proxy", not take the caller down.
        if "proxy" not in options:
            raise
        options.pop("proxy", None)
        return httpx.Client(**options)
