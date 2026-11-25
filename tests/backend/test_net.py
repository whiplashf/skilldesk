"""Outbound HTTP: proxy handling must never be able to crash the app."""

from __future__ import annotations

import pytest
from skilldesk.net import (
    LOOPBACK_MOUNTS,
    PROXY_ENV_VARS,
    http_client,
    is_loopback,
    proxy_for,
    resolve_proxy,
)


@pytest.fixture(autouse=True)
def clean_proxy_env(monkeypatch: pytest.MonkeyPatch):
    for name in PROXY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)


def test_client_survives_malformed_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shell with ``NO_PROXY=... ,[::1]`` used to break httpx at construction."""
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1,[::1]")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1,::1,[::1]")
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.1:3128")
    client = http_client(timeout=1)
    client.close()


def test_client_survives_malformed_proxy_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLDESK_PROXY", "not a url")
    client = http_client(timeout=1)
    client.close()


def test_loopback_never_uses_the_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLDESK_PROXY", "http://10.0.0.1:3128")
    for url in ("http://127.0.0.1:17899/api/health", "http://localhost:1234/v1", "http://[::1]:8000/"):
        assert proxy_for(url) is None, url
        assert is_loopback(url) is True, url
    assert proxy_for("https://api.github.com/repos/x/y") == "http://10.0.0.1:3128"
    assert is_loopback("https://api.github.com/repos/x/y") is False


def test_skilldesk_proxy_wins_over_generic_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://generic:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://generic:2")
    assert resolve_proxy() == "http://generic:2"
    monkeypatch.setenv("SKILLDESK_PROXY", "http://explicit:3")
    assert resolve_proxy() == "http://explicit:3"


def test_no_proxy_configured_means_direct() -> None:
    assert resolve_proxy() is None
    client = http_client(timeout=1)
    client.close()


def test_url_hint_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKILLDESK_PROXY", "http://10.0.0.1:3128")
    local = http_client(timeout=1, url_hint="http://127.0.0.1:17899/")
    remote = http_client(timeout=1, url_hint="https://api.github.com/")
    local.close()
    remote.close()


def test_loopback_mounts_are_valid_patterns() -> None:
    """``all://::1`` is not a valid mount pattern; the bracketed form is."""
    assert all("::" not in pattern or pattern.startswith("all://[") for pattern in LOOPBACK_MOUNTS)
    client = http_client(timeout=1, url_hint="http://127.0.0.1:17899/")
    client.close()
