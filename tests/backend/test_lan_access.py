"""Access through the explicitly bound LAN address using the real CLI options and ASGI app."""
from __future__ import annotations

import asyncio

import httpx
import pytest
import uvicorn
from skilldesk import cli
from skilldesk.server import create_app


@pytest.mark.parametrize(("host", "peer"), [("192.168.1.10", "192.168.1.24"), ("fd00::10", "fd00::24")])
def test_passwordless_lan_browser(fake_home, monkeypatch, host, peer):
    launched = {}
    monkeypatch.setenv("SKILLDESK_REMOTE_TOKEN", "previous-mode-token")
    monkeypatch.setattr(uvicorn, "run", lambda app, **options: launched.update(app=app, **options))
    assert cli.main(["serve", "--host", host, "--allow-lan"]) == 0
    assert launched["host"] == host and launched["proxy_headers"] is False
    origin = f"http://[{host}]:17888" if ":" in host else f"http://{host}:17888"

    async def browse():
        transport = httpx.ASGITransport(app=launched["app"], client=(peer, 2345))
        async with httpx.AsyncClient(transport=transport, base_url=origin) as browser:
            health = await browser.get("/api/health")
            assert health.status_code == 200 and "www-authenticate" not in health.headers
            token = (await browser.get("/api/session")).json()["token"]
            assert (await browser.post("/api/scan")).status_code == 403
            saved = await browser.post("/api/scan", headers={"origin": origin, "x-skilldesk-token": token})
            assert saved.status_code == 200

    asyncio.run(browse())


@pytest.mark.parametrize(("host", "peer"), [("other.example", "192.168.1.24"), ("192.168.1.10", "203.0.113.5")])
def test_lan_access_is_scoped_to_the_bound_host_and_local_peers(fake_home, host, peer):
    async def read():
        transport = httpx.ASGITransport(app=create_app(lan_host="192.168.1.10"), client=(peer, 2345))
        async with httpx.AsyncClient(transport=transport, base_url="http://" + host) as browser:
            response = await browser.get("/api/health")
            assert response.status_code == 403 and "www-authenticate" not in response.headers

    asyncio.run(read())


def test_other_listeners_still_require_explicit_configuration(fake_home, monkeypatch):
    monkeypatch.delenv("SKILLDESK_REMOTE_TOKEN", raising=False)
    assert cli.main(["serve", "--host", "0.0.0.0", "--allow-lan"]) == cli.EXIT_ERROR
    assert cli.main(["serve", "--host", "192.168.1.10"]) == cli.EXIT_ERROR
    assert cli.main(["serve", "--host", "0.0.0.0", "--allow-remote"]) == cli.EXIT_ERROR
    with pytest.raises(ValueError):
        create_app(lan_host="0.0.0.0")


def test_token_configured_listener_keeps_its_challenge(fake_home):
    async def read():
        transport = httpx.ASGITransport(app=create_app(remote_token="example"))
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as browser:
            protected = await browser.get("/api/health")
            assert protected.status_code == 401 and "Basic" in protected.headers["www-authenticate"]
            assert (await browser.get("/api/health", auth=("skilldesk", "example"))).status_code == 200

    asyncio.run(read())
