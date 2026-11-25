"""Access guard: loopback-only by default, trusted local proxy when opted in."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import write_skill
from skilldesk import index as index_mod
from skilldesk.config import Config
from skilldesk.health import detect
from skilldesk.scan import scan
from skilldesk.server import create_app

# RFC 5737 documentation range: the tests only need a non-loopback address.
GATEWAY = "http://192.0.2.10:8786"


def build_index(fake_home: Path, tmp_path: Path) -> Path:
    write_skill(fake_home / ".agents" / "skills", "alpha")
    result = scan(Config())
    database = tmp_path / "index.db"
    index_mod.rebuild(result, detect(result.skills, result.dangling), database)
    return database


def test_loopback_request_is_allowed(fake_home: Path, tmp_path: Path) -> None:
    client = TestClient(create_app(build_index(fake_home, tmp_path)))
    assert client.get("/api/health").status_code == 200


def test_public_host_header_is_refused_by_default(fake_home: Path, tmp_path: Path) -> None:
    client = TestClient(create_app(build_index(fake_home, tmp_path)), base_url=GATEWAY)
    response = client.get("/api/health")
    assert response.status_code == 403
    assert response.json()["detail"] == "仅允许本机访问"


def test_trusted_proxy_allows_a_relayed_request(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SKILLDESK_TRUSTED_PROXY", "1")
    client = TestClient(
        create_app(build_index(fake_home, tmp_path)), base_url=GATEWAY, client=("127.0.0.1", 40100)
    )
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/index").status_code == 200


def test_trusted_proxy_still_refuses_a_remote_peer(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a loopback peer can be the proxy; a real remote client stays out."""
    monkeypatch.setenv("SKILLDESK_TRUSTED_PROXY", "true")
    client = TestClient(
        create_app(build_index(fake_home, tmp_path)), base_url=GATEWAY, client=("10.0.0.9", 40100)
    )
    assert client.get("/api/health").status_code == 403


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_env_switch_accepts_common_spellings(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    from skilldesk.server import trusted_proxy_enabled

    monkeypatch.setenv("SKILLDESK_TRUSTED_PROXY", value)
    assert trusted_proxy_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no"])
def test_env_switch_is_off_by_default(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    from skilldesk.server import trusted_proxy_enabled

    if value:
        monkeypatch.setenv("SKILLDESK_TRUSTED_PROXY", value)
    else:
        monkeypatch.delenv("SKILLDESK_TRUSTED_PROXY", raising=False)
    assert trusted_proxy_enabled() is False


def test_writes_still_need_the_session_token(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SKILLDESK_TRUSTED_PROXY", "1")
    client = TestClient(
        create_app(build_index(fake_home, tmp_path)), base_url=GATEWAY, client=("127.0.0.1", 40100)
    )
    key = client.get("/api/index", params={"limit": 1}).json()["items"][0]["identity_key"]
    denied = client.patch(f"/api/assets/{key}", json={"favorite": True})
    assert denied.status_code in (403, 422)
    token = client.get("/api/session").json()["token"]
    allowed = client.patch(
        f"/api/assets/{key}",
        json={"favorite": True},
        headers={"x-skilldesk-token": token, "if-match": "0"},
    )
    assert allowed.status_code == 200
