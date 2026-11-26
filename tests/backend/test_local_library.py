"""Acceptance cases for the installed library, without third-party accounts or network."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from helpers import lock_entry, write_lockfile, write_skill
from skilldesk import translation, upstream
from skilldesk.config import Config
from skilldesk.markdown import render
from skilldesk.scan import scan
from skilldesk.server import create_app


def test_nested_and_project_identity(fake_home, tmp_path):
    store = fake_home / ".agents/skills"
    global_skill = write_skill(store, "alpha")
    write_lockfile(fake_home, {"alpha": lock_entry("example/one", "skills/alpha/SKILL.md")})
    project = tmp_path / "client"
    write_skill(
        project / ".claude/skills",
        "alpha",
        extra_frontmatter="repository: https://github.com/example/another\n",
    )
    write_skill(fake_home / ".codex/skills/.system", "bundled")
    write_skill(project / ".opencode/skills/group", "nested")
    os.symlink(global_skill, fake_home / ".claude/skills/alias")
    result = scan(Config(projects=[str(project)]))
    assert sorted(s.name for s in result.skills) == ["alpha", "alpha", "bundled", "nested"]
    alphas = {s.provenance.repo: s for s in result.skills if s.name == "alpha"}
    assert alphas["example/one"].provenance.confidence == "recorded"
    assert alphas["example/another"].identity_key.startswith("loc:")
    assert len(alphas["example/one"].placements) == 2


@pytest.fixture
def app_client(fake_home):
    store = fake_home / ".agents/skills"
    write_skill(store, "alpha", body="Read the review checklist.")
    write_skill(store, "bravo", body="Write the weekly notes.")
    client = TestClient(create_app())
    return client, {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}


def test_annotation_views_conflict_and_relocation(app_client, fake_home):
    client, headers = app_client
    item = client.get("/api/index", params={"q": "alpha"}).json()["items"][0]
    endpoint = "/api/assets/" + item["identity_key"]
    changes = {
        "favorite": True,
        "mine": True,
        "github": {"repo": "example/mine", "path": "skills/a/SKILL.md"},
    }
    assert client.patch(endpoint, headers={"If-Match": "0"}, json=changes).status_code == 403
    assert (
        client.patch(
            endpoint, headers={**headers, "If-Match": "0", "Origin": "https://example.invalid"}, json=changes
        ).status_code
        == 403
    )
    response = client.patch(endpoint, headers={**headers, "If-Match": "0"}, json=changes)
    assert response.status_code == 200
    assert response.json()["upstream"]["repo"] == "example/mine"
    assert (
        client.patch(endpoint, headers={**headers, "If-Match": "0"}, json={"favorite": False}).status_code
        == 409
    )
    assert client.get("/api/index", params={"view": "mine", "agent": "codex"}).json()["total"] == 1
    assert client.get("/api/index", params={"view": "github"}).json()["total"] == 0
    (fake_home / ".agents/skills/alpha").rename(fake_home / ".agents/skills/renamed")
    assert client.post("/api/scan", headers=headers).status_code == 200
    reloaded = TestClient(create_app()).get("/api/index", params={"view": "favorites"}).json()
    assert reloaded["total"] == 1 and reloaded["items"][0]["mine"]
    assert reloaded["items"][0]["realpath"].endswith("renamed")
    body = fake_home / ".agents/skills/renamed/SKILL.md"
    body.write_text(body.read_text() + "\nA local edit.\n")
    client.post("/api/scan", headers=headers).raise_for_status()
    body.parent.rename(body.parent.with_name("second-move"))
    client.post("/api/scan", headers=headers).raise_for_status()
    assert client.get("/api/index", params={"view": "favorites"}).json()["total"] == 1


def test_manage_project_from_settings(app_client, tmp_path):
    client, headers = app_client
    project = tmp_path / "project"
    write_skill(project / ".claude/skills", "project-skill")
    assert client.post("/api/projects", headers=headers, json={"path": "relative"}).status_code == 400
    for _ in range(2):
        saved = client.post("/api/projects", headers=headers, json={"path": str(project)}).json()
        assert saved["saved"] == [str(project)]
    query = {"agent": "claude", "q": "project-skill"}
    assert client.get("/api/index", params=query).json()["total"] == 1
    client.post(
        "/api/projects", headers=headers, json={"path": str(project), "remove": True}
    ).raise_for_status()
    assert client.get("/api/index", params=query).json()["total"] == 0


def test_rescan_finds_new_root_and_projects(app_client, fake_home, tmp_path, monkeypatch):
    client, headers = app_client
    write_skill(fake_home / ".codex/skills/.system", "new-system")
    project = tmp_path / "demo"
    write_skill(project / ".claude/skills", "review")
    write_skill(project / ".opencode/skills", "design")
    monkeypatch.setenv("SKILLDESK_PROJECTS", str(project))
    assert client.post("/api/scan", headers=headers).json()["counts"]["skills"] == 5
    listed = client.get("/api/index", params={"agent": "claude"}).json()["items"]
    assert [s["name"] for s in listed] == ["review"]
    assert {"agent": "claude", "scope": str(project)} in listed[0]["access"]
    assert client.get("/api/index", params={"q": "new-system", "agent": "codex"}).json()["total"] == 1
    assert any(a["value"] == "opencode" for a in client.get("/api/facets").json()["agents"])


def test_translation_preserves_markup_and_caches(fake_home, monkeypatch):
    translation.configure("http://localhost:1234/v1", "demo", "private")
    seen = []

    def translate_batch(client, settings, texts):
        seen.extend(texts)
        return ["中译" + str(i) for i, _ in enumerate(texts)]

    monkeypatch.setattr(translation, "_translate_batch", translate_batch)
    text = render(
        "Read [the guide](references/one.md), then run \x60npm test\x60.\n\n\x60\x60\x60sh\nnpm run build\n\x60\x60\x60"
    )
    first = translation.translate(text)
    assert seen and "npm test" not in seen and "references/one.md" not in seen
    assert 'href="references/one.md"' in first["html"] and "<code>npm test</code>" in first["html"]
    assert "npm run build" in first["html"] and "中译" in first["html"]
    assert not first["cached"] and translation.translate(text)["cached"]
    assert "apiKey" not in translation.public_settings()
    assert not translation.translate(render("New text."))["cached"]


def test_unconfigured_translation_and_private_settings(app_client, monkeypatch):
    client, headers = app_client
    for k in ("SKILLDESK_AI_BASE_URL", "SKILLDESK_AI_MODEL", "SKILLDESK_AI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    key = client.get("/api/index").json()["items"][0]["identity_key"]
    assert client.post("/api/ai/translate", headers=headers, json={"identity_key": key}).status_code == 501
    data = client.put(
        "/api/settings/ai",
        headers=headers,
        json={"baseUrl": "http://localhost:1234/v1", "model": "demo", "apiKey": "sample"},
    ).json()
    assert data["enabled"] and data["hasKey"] and "sample" not in json.dumps(data)


def test_manual_and_batch_checks_share_only_this_requests_evidence(fake_home, monkeypatch):
    from collections import Counter

    upstream.forget_caches()
    store = fake_home / ".agents/skills"
    names = ["alpha", "beta"]
    for name in names:
        write_skill(store, name, extra_frontmatter="version: 1.0\n")
    records = {n: lock_entry("owner/pack", n + "/SKILL.md", commit="a" * 40) for n in names}
    write_lockfile(fake_home, {n: {**v, "skilldeskTree": "b" * 40} for n, v in records.items()})
    monkeypatch.setenv("SKILLDESK_GITHUB_TOKEN", "fixture")
    calls = Counter()
    releases = []
    published = "d" * 40

    def respond(request):
        endpoint = request.url.path.removeprefix("/repos/owner/pack").strip("/")
        calls[endpoint] += 1
        data = {
            "releases": releases, "git/ref/tags/v2": {"object": {"type": "commit", "sha": published}},
            "git/trees/" + published: {"sha": "root", "tree": [
                obj for n in names for obj in ({"path": n, "type": "tree", "sha": "c" * 40},
                                               {"path": n + "/SKILL.md", "type": "blob"})]},
            "compare/" + "a" * 40 + "..." + published: {"status": "ahead"},
        }
        return httpx.Response(200, json=data[endpoint])

    monkeypatch.setattr(upstream, "http_client", lambda **kw: httpx.Client(transport=httpx.MockTransport(respond)))
    with TestClient(create_app()) as client:
        keys = [i["identity_key"] for i in client.get("/api/index").json()["items"]]
        headers = {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}
        def single():
            return client.post("/api/check", headers=headers, json={"identity_key": keys[0], "force": True}).json()

        assert single()["status"] == "no_release"
        assert calls == {"releases": 1}
        releases.append({"tag_name": "v2", "body": "New instructions for both skills."})
        calls.clear()
        result = client.post("/api/check-batch", headers=headers, json={"keys": keys}).json()["items"]
        assert [row["result"]["status"] for row in result] == ["release", "release"]
        assert calls == {"releases": 1, "git/ref/tags/v2": 1, "git/trees/" + published: 1,
                         "compare/" + "a" * 40 + "..." + published: 1}
        assert len({row["result"]["checkedAt"] for row in result}) == 1
        calls.clear()
        assert client.get("/api/check-all").json() is None
        assert client.post("/api/check-all").status_code == 403 and not calls
        assert client.post("/api/check-all", headers=headers).status_code == 202
        report = client.get("/api/check-all").json()
        assert report["total"] == report["checked"] == 2 and not report["running"]
        assert [(r["key"], r["status"]) for r in report["updates"]] == [(k, "release") for k in keys]
        assert calls == {"releases": 1, "git/ref/tags/v2": 1, "git/trees/" + published: 1,
                         "compare/" + "a" * 40 + "..." + published: 1}
        releases.clear()
        assert single()["status"] == "no_release" and calls["releases"] == 2
        before_failure = client.get("/api/skill/" + keys[0]).json()["versionStatus"]
        def unavailable(request):
            return httpx.Response(429)

        monkeypatch.setattr(upstream, "http_client", lambda **kw: httpx.Client(transport=httpx.MockTransport(unavailable)))
        failed = client.post("/api/check", headers=headers, json={"identity_key": keys[0], "force": True})
        assert failed.status_code == 429
        assert client.get("/api/skill/" + keys[0]).json()["versionStatus"] == before_failure


def test_git_tree_hash_includes_support_files(tmp_path: Path):
    folder = tmp_path / "sample"
    folder.mkdir()
    (folder / "note.txt").write_bytes(b"hello")
    blob = hashlib.sha1(b"blob 5\0hello").digest()
    data = b"100644 note.txt\0" + blob
    assert (
        upstream._local_tree(folder)
        == hashlib.sha1(b"tree " + str(len(data)).encode() + b"\0" + data).hexdigest()
    )


def test_project_lock_belongs_to_its_own_store(fake_home, tmp_path):
    project = tmp_path / "demo"
    write_skill(project / ".agents/skills", "alpha")
    write_skill(fake_home / ".agents/skills", "alpha")
    (project / "skills-lock.json").write_text(
        json.dumps(
            {
                "skills": {
                    "alpha": {
                        "sourceType": "github",
                        "source": "owner/project",
                        "skillPath": "skills/a/SKILL.md",
                    }
                }
            }
        )
    )
    entry = lock_entry("owner/global", "global/alpha/SKILL.md")
    entry["skillFolderHash"] = "a" * 40
    write_lockfile(fake_home, {"alpha": entry})
    result = scan(Config(projects=[str(project)]))
    assert {s.provenance.repo for s in result.skills} == {"owner/global", "owner/project"}
    assert next(s for s in result.skills if s.provenance.repo == "owner/global").provenance.tree == "a" * 40
    assert result.lockfile_entries == 2


def test_scoped_release_and_recorded_tree(tmp_path):
    upstream.forget_caches()
    folder = write_skill(tmp_path, "alpha", extra_frontmatter="version: 1.0.0\n")
    item = {"name": "alpha", "dir_name": "alpha", "realpath": str(folder)}
    source = {"repo": "owner/pack", "path": "skills/alpha/SKILL.md", "ref": "", "tree": "base"}

    def get(endpoint, params):
        return {
            "git/ref/tags/alpha%40v1.2.0": {"object": {"type": "commit", "sha": "d" * 40}},
            "git/trees/" + "d" * 40: {"sha": "root", "tree": [
                {"type": "tree", "path": "skills/alpha", "sha": "new"},
                {"type": "blob", "path": "skills/alpha/SKILL.md"}]},
            "releases": [{"tag_name": "beta@v5.0"}, {"tag_name": "alpha@v1.2.0"}],
        }[endpoint]

    status = upstream.evaluate(item, source, get)
    assert (status["status"], status["latest"]) == ("release", "alpha@v1.2.0")
    assert upstream.evaluate(item, source, lambda e, p: [], fresh=True)["status"] == "no_release"


def test_open_original_includes_frontmatter(app_client):
    client, _headers = app_client
    key = client.get("/api/index").json()["items"][0]["identity_key"]
    response = client.get("/api/skill/" + key + "/file", params={"rel": "SKILL.md", "raw": True})
    assert response.status_code == 200
    assert response.json()["kind"] == "text"
    assert response.json()["text"].startswith("---\nname:")


def test_translation_key_is_bound_to_its_service(fake_home, monkeypatch):
    translation.configure("https://one.example/v1", "model", "stored-key")
    monkeypatch.setenv("SKILLDESK_AI_BASE_URL", "https://two.example/v1")
    assert not translation.public_settings()["hasKey"]
    monkeypatch.setenv("SKILLDESK_AI_API_KEY", "env-key")
    assert translation.configuration()["apiKey"] == "env-key"
    monkeypatch.delenv("SKILLDESK_AI_BASE_URL")
    assert translation.configuration()["apiKey"] == "stored-key"


def test_only_enabled_installed_codex_plugin_is_scanned(fake_home):
    codex = fake_home / ".codex"
    codex.mkdir(exist_ok=True)
    (codex / "config.toml").write_text('[plugins."helper@local"]\nenabled = true\n')
    for plugin in ["helper", "previously-installed"]:
        version = codex / "plugins/cache/local" / plugin / "1.0"
        manifest = version / ".codex-plugin/plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"skills": "./instructions"}))
        write_skill(version / "instructions", plugin)
    skills = scan(Config()).skills
    assert [skill.name for skill in skills] == ["helper"]
    assert skills[0].primary_kind == "codex"
    assert skills[0].provenance.source_label == "Codex 插件 · helper"
    assert not skills[0].provenance.repo


def test_distribution_and_claims_match_in_health_facets_and_cli(fake_home):
    from skilldesk import cli

    store = fake_home / ".agents/skills"
    system = fake_home / ".codex/skills/.system"
    built_in = write_skill(system, "bundled")
    (store / "alias").symlink_to(built_in)
    external = write_skill(fake_home / "own", "draft")
    (system / "external").symlink_to(external)
    write_skill(store, "office")
    write_lockfile(fake_home, {"office": {"sourceType": "well-known", "sourceUrl": "https://open.feishu.cn/docs/office"}})
    with TestClient(create_app()) as client:
        token = client.get("/api/session").json()["token"]
        for label in ["open.feishu.cn", "Codex 内置"]:
            item, = client.get("/api/index", params={"source": label}).json()["items"]
            assert item["provenance"]["sourceLabel"] == label and not item["upstream"]
        issue, = client.get("/api/issues").json()["items"]
        assert issue["name"] == "draft" and issue["agents"] == ["codex"]
        client.patch("/api/assets/" + issue["identity_key"], json={"mine": True},
                     headers={"If-Match": "0", "X-Skilldesk-Token": token}).raise_for_status()
        summary = cli._build_index()
        issues = client.get("/api/issues").json()
        assert issues["counts"] == client.get("/api/health").json()["counts"]
        assert issues["total"] == summary["issues"] == summary["unclaimed"] == 0
        assert not issues["items"] and not summary["issues_by_kind"]
        for option in client.get("/api/facets").json()["sources"]:
            assert client.get("/api/index", params={"source": option["value"]}).json()["total"] == option["count"]


def test_ordered_code_and_remote_images_survive_support_file_and_translation(fake_home, monkeypatch):
    commands = "cd sample\n\tnpm test"
    markdown = "3. Run\n   ~~~sh\n   cd sample\n   \tnpm test\n   ~~~\n   - Again\n4. Done\n\n"
    markdown += "![remote](https://images.example.invalid/badge) ![local](doc.png)"
    skill = write_skill(fake_home / ".agents/skills", "read", body=markdown)
    (skill / "guide.md").write_text(markdown)
    translation.configure("http://localhost:1234/v1", "fixture", None)
    seen = []

    def translate_batch(client, settings, texts):
        seen.extend(texts)
        return ["译文" for _ in texts]

    monkeypatch.setattr(translation, "_translate_batch", translate_batch)
    with TestClient(create_app()) as client:
        key = client.get("/api/index").json()["items"][0]["identity_key"]
        base = "/api/skill/" + key
        headers = {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}
        bodies = [
            client.get(base).json()["html"],
            client.get(base + "/file", params={"rel": "guide.md"}).json()["html"],
            client.post("/api/ai/translate", headers=headers, json={"identity_key": key}).json()["html"],
        ]
    for body in bodies:
        assert '<ol class="md-list" start="3">' in body and '<ul class="md-list">' in body
        assert f'<pre><code class="language-sh">{commands}</code></pre>' in body
        assert 'data-remote-image="https://' in body and 'src="https://' not in body
        assert '<img alt="local" src="doc.png">' in body
    assert seen and not any("npm test" in s or "cd sample" in s for s in seen)
    block = render("1. First paragraph\ncontinued here\n\n       leave\n       \ttabs\n2. Next")
    assert "First paragraph continued here" in block and "<pre><code>leave\n\ttabs</code></pre>" in block
