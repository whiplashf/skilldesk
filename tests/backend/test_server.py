"""HTTP API: read endpoints, detail rendering, path safety and size caps."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from helpers import lock_entry, write_lockfile, write_skill
from skilldesk import SCHEMA_VERSION
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
    assert payload["meta"]["schema"] == str(SCHEMA_VERSION)


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


def _token(client: TestClient) -> dict:
    return {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}


def _claim(client: TestClient, key: str, body: dict):
    revision = client.get("/api/library").json()["revision"]
    return client.patch(
        "/api/assets/" + quote(key, safe=""), headers={**_token(client), "If-Match": str(revision)}, json=body
    )


def test_claim_mine_accounts_for_an_unrecorded_skill(client: TestClient) -> None:
    before = client.get("/api/health").json()["counts"]
    assert before["unclaimed"] == 1 and before["issues"] == 2

    beta = key_of(client, "beta")
    assert _claim(client, beta, {"mine": True}).status_code == 200

    counts = client.get("/api/health").json()["counts"]
    assert counts["unclaimed"] == 0
    assert counts["issues"] == 1  # the dangling link is still a real problem

    issues = client.get("/api/issues").json()
    assert [item["kind"] for item in issues["items"]] == ["dangling_link"]
    assert issues["total"] == 1

    assert client.get("/api/index", params={"health": "unclaimed_source"}).json()["total"] == 0
    assert client.get("/api/index", params={"confidence": "none"}).json()["total"] == 0
    claimed = client.get("/api/index", params={"confidence": "claimed"}).json()
    assert claimed["total"] == 1 and claimed["items"][0]["identity_key"] == beta
    assert claimed["items"][0]["health"] == []

    detail = client.get("/api/skill/" + quote(beta, safe="")).json()
    assert detail["provenance"]["confidence"] == "claimed"
    assert detail["provenance"]["label"] == "本地自写"
    assert detail["confidenceLabel"] == "已认领"
    assert detail["issues"] == []

    facets = client.get("/api/facets").json()
    assert {entry["value"]: entry["count"] for entry in facets["confidence"]} == {"recorded": 1, "claimed": 1}
    assert all(entry["value"] != "unclaimed_source" for entry in facets["health"])
    assert facets["confidenceLabels"]["claimed"] == "已认领"


def test_claim_github_supplies_the_missing_upstream(client: TestClient) -> None:
    beta = key_of(client, "beta")
    response = _claim(client, beta, {"github": {"repo": "acme/pack", "path": "skills/beta/SKILL.md"}})
    assert response.status_code == 200
    assert response.json()["upstream"]["repo"] == "acme/pack"

    detail = client.get("/api/skill/" + quote(beta, safe="")).json()
    assert detail["provenance"]["label"] == "github.com/acme/pack"
    assert detail["provenance"]["path"] == "skills/beta/SKILL.md"
    assert detail["confidenceLabel"] == "已认领"
    assert detail["issues"] == []
    assert client.get("/api/health").json()["counts"]["unclaimed"] == 0


def test_claim_can_be_withdrawn(client: TestClient) -> None:
    beta = key_of(client, "beta")
    assert _claim(client, beta, {"mine": True}).status_code == 200
    assert _claim(client, beta, {"mine": False}).status_code == 200
    counts = client.get("/api/health").json()["counts"]
    assert counts["unclaimed"] == 1 and counts["issues"] == 2
    detail = client.get("/api/skill/" + quote(beta, safe="")).json()
    assert detail["provenance"]["confidence"] == "none"
    assert [issue["kind"] for issue in detail["issues"]] == ["unclaimed_source"]


def test_claim_does_not_override_a_machine_record(client: TestClient) -> None:
    alpha = key_of(client, "alpha")
    assert _claim(client, alpha, {"mine": True}).status_code == 200
    detail = client.get("/api/skill/" + quote(alpha, safe="")).json()
    assert detail["provenance"]["confidence"] == "recorded"
    assert detail["confidenceLabel"] == "已记录"
    counts = client.get("/api/health").json()["counts"]
    assert counts["unclaimed"] == 1  # beta is still unrecorded


def test_claim_survives_a_rescan(client: TestClient) -> None:
    beta = key_of(client, "beta")
    assert _claim(client, beta, {"mine": True}).status_code == 200
    assert client.post("/api/scan", headers=_token(client)).status_code == 200
    counts = client.get("/api/health").json()["counts"]
    assert counts["unclaimed"] == 0
    assert client.get("/api/index", params={"confidence": "claimed"}).json()["total"] == 1
