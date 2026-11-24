"""HTTP API: read endpoints, detail rendering, path safety and size caps."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from helpers import lock_entry, write_lockfile, write_skill
from skilldesk import index as index_mod
from skilldesk.config import Config
from skilldesk.health import detect
from skilldesk.scan import scan
from skilldesk.server import FILE_SIZE_LIMIT, create_app


@pytest.fixture
def client(fake_home: Path, tmp_path: Path) -> TestClient:
    store = fake_home / ".agents" / "skills"
    claude = fake_home / ".claude" / "skills"
    alpha = write_skill(store, "alpha", description="alpha does frontend things", body="# Alpha\n\nSee [refs](references/one.md).\n")
    write_skill(store, "beta", description="beta is unclaimed")
    os.symlink(store / "alpha", claude / "alpha")
    write_lockfile(fake_home, {"alpha": lock_entry("acme/pack", "skills/alpha/SKILL.md")})
    (alpha / "references").mkdir()
    (alpha / "references" / "one.md").write_text("# One\n\nnested doc\n", encoding="utf-8")
    (alpha / "notes.txt").write_text("plain notes\n", encoding="utf-8")
    (alpha / "pixel.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    (alpha / "huge.bin").write_bytes(b"0" * (FILE_SIZE_LIMIT + 1))
    os.symlink("/nonexistent/gone", claude / "gone")

    result = scan(Config())
    db = tmp_path / "index.db"
    index_mod.rebuild(result, detect(result.skills, result.dangling), db)
    return TestClient(create_app(db))


def key_of(client: TestClient, name: str) -> str:
    items = client.get("/api/index", params={"q": name}).json()["items"]
    return items[0]["identity_key"]


def test_health(client: TestClient) -> None:
    payload = client.get("/api/health").json()
    assert payload["ok"] is True
    assert payload["counts"]["skills"] == 2
    assert payload["counts"]["dangling"] == 1
    assert payload["meta"]["schema"] == "1"


def test_index_and_filters(client: TestClient) -> None:
    assert client.get("/api/index").json()["total"] == 2
    assert client.get("/api/index", params={"q": "frontend"}).json()["total"] == 1
    assert client.get("/api/index", params={"host": "claude"}).json()["total"] == 1
    assert client.get("/api/index", params={"confidence": "none"}).json()["total"] == 1
    assert client.get("/api/index", params={"health": "unclaimed_source"}).json()["total"] == 1
    assert client.get("/api/index", params={"limit": 1, "offset": 1}).json()["total"] == 2


def test_facets_and_labels(client: TestClient) -> None:
    payload = client.get("/api/facets").json()
    assert {entry["value"] for entry in payload["hosts"]} == {"agents", "claude"}
    assert payload["confidenceLabels"]["none"] == "待认领"
    assert payload["healthLabels"]["dangling_link"] == "悬空软链"


def test_roots(client: TestClient) -> None:
    roots = client.get("/api/roots").json()["items"]
    assert roots[0]["kind"] == "agents"


def test_issues(client: TestClient) -> None:
    payload = client.get("/api/issues", params={"kind": "dangling_link"}).json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["detail"].startswith("claude 根里")


def test_skill_detail_renders_markdown(client: TestClient) -> None:
    key = key_of(client, "alpha")
    payload = client.get(f"/api/skill/{quote(key, safe='')}").json()
    assert "<h1>Alpha</h1>" in payload["html"]
    assert 'href="references/one.md"' in payload["html"]
    assert payload["confidenceLabel"] == "已记录"
    assert payload["frontmatter"]["name"] == "alpha"
    assert len(payload["placements"]) == 2


def test_skill_detail_unknown(client: TestClient) -> None:
    assert client.get("/api/skill/src:nope/nope@x").status_code == 404


def test_files_listing_and_content(client: TestClient) -> None:
    key = quote(key_of(client, "alpha"), safe="")
    files = client.get(f"/api/skill/{key}/files").json()["items"]
    rels = {item["rel"] for item in files}
    assert {"references/one.md", "notes.txt", "pixel.png", "huge.bin"} <= rels

    markdown = client.get(f"/api/skill/{key}/file", params={"rel": "references/one.md"}).json()
    assert markdown["kind"] == "markdown"
    assert "<h1>One</h1>" in markdown["html"]

    text = client.get(f"/api/skill/{key}/file", params={"rel": "notes.txt"}).json()
    assert text["kind"] == "text" and text["text"].strip() == "plain notes"

    image = client.get(f"/api/skill/{key}/file", params={"rel": "pixel.png"}).json()
    assert image["kind"] == "image"
    assert image["url"].startswith("/api/skill/")

    asset = client.get(f"/api/skill/{key}/asset", params={"rel": "pixel.png"})
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith("image/png")


def test_file_path_escape_is_refused(client: TestClient) -> None:
    key = quote(key_of(client, "alpha"), safe="")
    response = client.get(f"/api/skill/{key}/file", params={"rel": "../../../../etc/passwd"})
    assert response.status_code in (400, 404)
    response = client.get(f"/api/skill/{key}/asset", params={"rel": "../../../../etc/passwd"})
    assert response.status_code in (400, 404)


def test_file_size_cap(client: TestClient) -> None:
    key = quote(key_of(client, "alpha"), safe="")
    assert client.get(f"/api/skill/{key}/file", params={"rel": "huge.bin"}).status_code == 413
    assert client.get(f"/api/skill/{key}/asset", params={"rel": "huge.bin"}).status_code == 413


def test_unknown_file(client: TestClient) -> None:
    key = quote(key_of(client, "alpha"), safe="")
    assert client.get(f"/api/skill/{key}/file", params={"rel": "missing.md"}).status_code == 404


def test_missing_body_reports_gone(client: TestClient, fake_home: Path) -> None:
    key = quote(key_of(client, "alpha"), safe="")
    (fake_home / ".agents" / "skills" / "alpha" / "SKILL.md").unlink()
    assert client.get(f"/api/skill/{key}").status_code == 410


def test_health_auto_rescans_when_the_filesystem_changes(
    client: TestClient, fake_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    import skilldesk.server as server_module

    monkeypatch.setattr(server_module, "_last_rescan", 0.0)
    before = client.get("/api/health").json()["counts"]["skills"]

    store = fake_home / ".agents" / "skills"
    write_skill(store, "newcomer")
    future = time.time() + 5
    os.utime(store, (future, future))

    payload = client.get("/api/health").json()
    assert payload["rescanned"] is True
    assert payload["counts"]["skills"] == before + 1
    # nothing changed since: no rescan, same counts
    payload = client.get("/api/health").json()
    assert payload["rescanned"] is False
    assert payload["counts"]["skills"] == before + 1
