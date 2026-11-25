"""Exercise the install workflow with a real, local Git remote and disposable agent homes."""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import lock_entry, write_lockfile, write_skill
from skilldesk import maintenance
from skilldesk.library import read_json, write_json
from skilldesk.packages import MaintenanceError, Source
from skilldesk.placements import lock_path
from skilldesk.server import create_app

REPO = "test/collection"
ALPHA = "skills/alpha/SKILL.md"
KEY = "src:github.com/test/collection@" + ALPHA


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, text=True, capture_output=True
    ).stdout.strip()


def commit(repo):
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def remote(fake_home, tmp_path, monkeypatch):
    repo = tmp_path / "repository"
    repo.mkdir()
    git(repo, "init", "-q")
    alpha = write_skill(repo / "skills", "alpha", body="Release one.\n", extra_frontmatter="license: MIT\n")
    (alpha / "readme-link").symlink_to("SKILL.md")
    (alpha / "check.sh").write_text("#!/bin/sh\n")
    (alpha / "check.sh").chmod(0o755)
    write_skill(repo / "skills", "beta")
    commit(repo)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "url." + repo.as_uri() + ".insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://github.com/test/collection.git")
    # Even a malformed fixture must never use a network or ask for credentials.
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    return repo


@pytest.fixture
def client(fake_home):
    return TestClient(create_app())


def post(client, method, **body):
    token = client.get("/api/session").json()["token"]
    return client.post("/api/maintenance/" + method, json=body, headers={"X-Skilldesk-Token": token})


def good(response):
    assert response.status_code == 200, response.text
    return response.json()


def install(client, root, path=ALPHA):
    p = good(post(client, "install-preview", repository=REPO, path=path, root=str(root)))
    return p, good(post(client, "confirm", id=p["id"], accept_license=True))


def change(client, entry, action, key=KEY):
    return post(client, "placement-preview", action=action, entry=str(entry), identity_key=key)


def test_current_and_metadata_only_updates_do_not_replace_files(remote, client, fake_home):
    root = fake_home / ".agents/skills"
    install(client, root)
    path = root / "alpha"
    lock = lock_path(root)
    before = lock.read_bytes()
    original = (path.stat().st_ino, (path / "SKILL.md").stat().st_ino)
    current = good(change(client, path, "update"))
    assert current["outcome"] == "current" and current["backup"] == ""
    assert good(post(client, "confirm", id=current["id"]))["outcome"] == "current"
    assert lock.read_bytes() == before
    (remote / "other.txt").write_text("unrelated change")
    next_commit = commit(remote)
    plan = good(change(client, path, "update"))
    assert plan["outcome"] == "record" and plan["backup"] == ""
    receipt = good(post(client, "confirm", id=plan["id"]))
    assert good(post(client, "confirm", id=plan["id"])) == receipt
    assert read_json(lock, {})["skills"]["alpha"]["commit"] == next_commit
    assert (path.stat().st_ino, (path / "SKILL.md").stat().st_ino) == original
    assert not (maintenance.state_dir() / "backups").exists()


def test_dangling_preview_requires_same_still_missing_direct_link(client, fake_home):
    root = fake_home / ".claude/skills"
    entry = root / "lost"
    target = root.parent / "recovered"
    entry.symlink_to("../recovered")
    nested = root / "group"
    nested.mkdir()
    (nested / "broken").symlink_to("gone")
    headers = {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}
    client.post("/api/scan", headers=headers).raise_for_status()
    issues = client.get("/api/issues").json()
    assert issues["total"] == issues["counts"]["dangling"] == 2
    fixable, = [x for x in issues["items"] if x["fixable"]]
    assert fixable["name"] == "lost" and fixable["missingTarget"] == "../recovered"
    assert post(client, "dangling-preview", entry=str(nested / "broken")).status_code == 409
    plan = good(post(client, "dangling-preview", entry=str(entry)))
    assert plan["dangling"] and plan["linkTarget"] == "../recovered"
    target.mkdir()
    assert post(client, "confirm", id=plan["id"]).status_code == 409
    assert entry.is_symlink() and target.is_dir()
    entry.unlink()
    entry.symlink_to("other-missing")
    assert post(client, "confirm", id=plan["id"]).status_code == 409
    plan = good(post(client, "dangling-preview", entry=str(entry)))
    receipt = good(post(client, "confirm", id=plan["id"]))
    assert good(post(client, "confirm", id=plan["id"])) == receipt and not entry.is_symlink()
    assert (nested / "broken").is_symlink() and target.is_dir()


def test_root_and_all_sibling_candidates_can_be_selected(remote, client, fake_home):
    root = fake_home / ".agents/skills"
    (remote / "SKILL.md").write_text("# Root skill")
    for n in range(21):
        write_skill(remote / "extras", "demo-" + str(n))
    commit(remote)
    choices = post(client, "install-preview", repository=REPO, root=str(root))
    assert choices.status_code == 404 and len(choices.json()["candidates"]) == 24
    for path in ["SKILL.md", "extras/demo-20/SKILL.md"]:
        assert path in choices.json()["candidates"]
        preview = good(post(client, "install-preview", repository=REPO, root=str(root), path=path))
        assert preview["source"]["path"] == path


def test_two_siblings_share_git_cache_and_replayed_confirmation(remote, client, fake_home):
    root = fake_home / ".agents/skills"
    p, result = install(client, root)
    assert p["license"] == "MIT" and p["scripts"] == ["check.sh"] and p["files"] == 3
    assert p["source"]["path"] == ALPHA and p["commit"] == git(remote, "rev-parse", "HEAD")
    assert (root / "alpha/readme-link").is_symlink()
    assert (root / "alpha/check.sh").stat().st_mode & 0o111
    assert good(post(client, "confirm", id=p["id"])) == result
    beta = good(post(client, "install-preview", repository=REPO, path="skills/beta/SKILL.md", root=str(root)))
    assert not beta["license"] and post(client, "confirm", id=beta["id"]).status_code == 400
    assert good(post(client, "confirm", id=beta["id"], accept_license=True))["target"] == str(root / "beta")
    assert good(client.get("/api/index", params={"view": "github"}))["total"] == 2
    assert post(client, "install-preview", repository=REPO, path=ALPHA, root=str(root)).status_code == 409


def test_project_and_global_same_skill_update_exact_copy_and_preserve_lock_fields(
    remote, client, fake_home, tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("SKILLDESK_PROJECTS", str(project))
    global_root = fake_home / ".agents/skills"
    project_root = project / ".agents/skills"
    install(client, global_root)
    install(client, project_root)
    old = (global_root / "alpha/SKILL.md").read_bytes()
    lock = project / "skills-lock.json"
    metadata = read_json(lock, {})
    installed = metadata["skills"]["alpha"]["installedAt"]
    metadata["other"] = ["preserve"]
    metadata["skills"]["alpha"]["custom"] = "keep"
    write_json(lock, metadata)
    (remote / ALPHA).write_bytes(old + b"\nVersion two\n")
    commit(remote)
    p = good(change(client, project_root / "alpha", "update"))
    assert p["changes"]["changed"] == ["SKILL.md"] and p["localState"] == "clean"
    # HEAD advances after preview; confirmation still installs the displayed commit.
    (remote / ALPHA).write_bytes(b"later unpublished bytes")
    commit(remote)
    result = good(post(client, "confirm", id=p["id"]))
    assert (Path(result["backup"]) / "SKILL.md").read_bytes() == old
    assert (project_root / "alpha/SKILL.md").read_bytes() == old + b"\nVersion two\n"
    assert (global_root / "alpha/SKILL.md").read_bytes() == old
    actual = read_json(lock, {})
    assert actual["version"] == 2 and len(actual["skills"]["alpha"]["computedHash"]) == 64
    assert actual["other"] == ["preserve"] and actual["skills"]["alpha"]["custom"] == "keep"
    assert (
        actual["skills"]["alpha"]["installedAt"] == installed
        and actual["skills"]["alpha"]["commit"] == p["commit"]
    )
    assert change(client, tmp_path / "alpha", "uninstall").status_code == 409


def test_preview_rechecks_drift_and_lock_before_confirm(remote, client, fake_home):
    root = fake_home / ".agents/skills"
    install(client, root)
    local = root / "alpha"
    p = good(change(client, local, "update"))
    (local / "my-notes").write_text("keep")
    refused = post(client, "confirm", id=p["id"], accept_local=True)
    assert refused.status_code == 409 and (local / "my-notes").read_text() == "keep"
    after = good(change(client, local, "uninstall"))
    assert after["localState"] == "modified" and "my-notes" in after["changes"]["removed"]
    assert post(client, "confirm", id=after["id"]).status_code == 400
    lock = lock_path(fake_home / ".agents/skills")
    data = read_json(lock, {})
    data["skills"]["alpha"]["sourceUrl"] = "https://git.example/test/collection.git"
    write_json(lock, data)
    assert post(client, "confirm", id=after["id"], accept_local=True).status_code == 409
    assert local.is_dir()


def test_alias_removal_keeps_checked_out_source_and_other_alias(fake_home, tmp_path, client):
    repo = tmp_path / "authored"
    source = write_skill(repo / "skills", "personal")
    git(repo, "init", "-q")
    commit(repo)
    one = fake_home / ".agents/skills/personal"
    two = fake_home / ".claude/skills/personal"
    one.symlink_to(source)
    two.symlink_to(source)
    token = client.get("/api/session").json()["token"]
    client.post("/api/scan", headers={"X-Skilldesk-Token": token}).raise_for_status()
    skill = client.get("/api/index").json()["items"][0]
    key = skill["identity_key"]
    assert change(client, one, "uninstall", key).status_code == 409
    p = good(change(client, one, "unlink", key))
    assert p["linkTarget"] == str(source)
    good(post(client, "confirm", id=p["id"]))
    assert not one.is_symlink() and two.resolve(strict=True) == source
    assert (source / "SKILL.md").is_file() and git(repo, "status", "--porcelain") == ""


def test_uninstall_protects_link_users_then_archives_physical_copy(remote, client, fake_home):
    root = fake_home / ".agents/skills"
    install(client, root)
    alias = fake_home / ".claude/skills/assistant"
    p = good(change(client, root / "alpha", "uninstall"))
    alias.symlink_to(root / "alpha")
    assert post(client, "confirm", id=p["id"]).status_code == 409
    assert change(client, root / "alpha", "uninstall").status_code == 409
    link = good(change(client, alias, "unlink"))
    good(post(client, "confirm", id=link["id"]))
    p = good(change(client, root / "alpha", "uninstall"))
    result = good(post(client, "confirm", id=p["id"]))
    assert (Path(result["backup"]) / "SKILL.md").is_file() and not (root / "alpha").exists()
    assert good(client.get("/api/index"))["total"] == 0
    assert read_json(lock_path(fake_home / ".agents/skills"), {})["skills"] == {}


@pytest.mark.parametrize("failure", ["stage", "promote", "backup", "metadata"])
def test_failed_update_keeps_original_files_and_metadata(failure, remote, client, fake_home, monkeypatch):
    root = fake_home / ".agents/skills"
    install(client, root)
    entry = root / "alpha"
    before = (entry / "SKILL.md").read_bytes()
    (remote / ALPHA).write_bytes(before + b" change")
    commit(remote)
    plan = good(change(client, entry, "update"))
    lock = lock_path(fake_home / ".agents/skills")
    record = lock.read_bytes()
    if failure in {"stage", "backup"}:
        copy = maintenance.shutil.copytree

        def fail_copy(src, dst, *args, **kwargs):
            if (failure == "stage" and Path(dst).name == "incoming") or (
                failure == "backup" and Path(src).name == "previous"
            ):
                raise OSError("fixture disk full")
            return copy(src, dst, *args, **kwargs)

        monkeypatch.setattr(maintenance.shutil, "copytree", fail_copy)
    else:
        replace = os.replace

        def fail_move(src, dst):
            if (
                failure == "promote"
                and Path(src).name == "incoming"
                and dst == entry
                or failure == "metadata"
                and dst == lock
            ):
                raise OSError("fixture promotion failure")
            return replace(src, dst)

        monkeypatch.setattr(os, "replace", fail_move)
    assert post(client, "confirm", id=plan["id"]).status_code == 409
    assert lock.read_bytes() == record and (entry / "SKILL.md").read_bytes() == before
    assert not (maintenance.plans() / "active.json").exists()


def test_parallel_confirmations_apply_once(remote, client, fake_home):
    root = fake_home / ".agents/skills"
    plan = good(post(client, "install-preview", repository=REPO, path=ALPHA, root=str(root)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: good(post(client, "confirm", id=plan["id"])), range(2)))
    assert results[0] == results[1] and (root / "alpha/SKILL.md").is_file()


def test_tampered_stage_and_plan_expiry_leave_install_untouched(remote, client, fake_home):
    root = fake_home / ".agents/skills"
    p = good(post(client, "install-preview", repository=REPO, path=ALPHA, root=str(root)))
    slot = maintenance.plans() / p["id"]
    (slot / "package/new-file").write_text("unexpected")
    assert post(client, "confirm", id=p["id"]).status_code == 409 and not (root / "alpha").exists()
    data = read_json(slot / "plan.json", {})
    data["report"]["expiresAt"] = 0
    write_json(slot / "plan.json", data)
    assert post(client, "confirm", id=p["id"]).status_code == 410


def test_protect_unknown_managed_names_and_git_worktrees(fake_home, client):
    root = fake_home / ".agents/skills"
    own = write_skill(root, "alpha")
    token = client.get("/api/session").json()["token"]
    client.post("/api/scan", headers={"X-Skilldesk-Token": token}).raise_for_status()
    key = client.get("/api/index").json()["items"][0]["identity_key"]
    assert change(client, own, "uninstall", key).status_code == 409
    write_lockfile(fake_home, {"alpha": lock_entry(REPO, ALPHA)})
    git(own, "init", "-q")
    assert change(client, own, "uninstall").status_code == 409
    assert (own / "SKILL.md").is_file()


def test_unverified_legacy_record_needs_explicit_confirmation(fake_home, client):
    entry = write_skill(fake_home / ".agents/skills", "renamed")
    write_lockfile(fake_home, {"renamed": lock_entry(REPO, ALPHA)})
    p = good(change(client, entry, "uninstall"))
    assert p["target"] == str(entry) and p["localState"] == "unknown"
    assert post(client, "confirm", id=p["id"]).status_code == 400
    assert Path(good(post(client, "confirm", id=p["id"], accept_local=True))["backup"]).is_dir()


def test_managed_source_validation_and_multiskill_selection(remote, client, fake_home):
    root = fake_home / ".agents/skills"
    missing = post(client, "install-preview", repository=REPO, root=str(root))
    assert missing.status_code == 404 and ALPHA in missing.json()["detail"]
    assert (
        Source.parse("git@git.example:Test/Collection.git", ALPHA).coordinates()
        != Source.parse(REPO, ALPHA).coordinates()
    )
    for invalid in ("file:///tmp/data", "https://example.test:bad/a/b", "https://github.com/org/../other"):
        with pytest.raises(MaintenanceError):
            Source.parse(invalid, ALPHA)
    assert (
        post(client, "install-preview", repository=REPO, path=ALPHA, root=str(fake_home)).status_code == 400
    )
    assert client.post("/api/maintenance/confirm", json={"id": "x"}).status_code == 403
    assert post(client, "confirm", id="wrong", target=str(root)).status_code == 422


def test_reject_outside_links_and_symlinked_store(remote, client, fake_home, tmp_path, monkeypatch):
    (remote / "skills/alpha/external").symlink_to("../beta/SKILL.md")
    commit(remote)
    root = fake_home / ".agents/skills"
    failed = post(client, "install-preview", repository=REPO, path=ALPHA, root=str(root))
    assert failed.status_code == 400 and not (root / "alpha").exists()
    project = tmp_path / "project"
    project.mkdir()
    (project / ".agents").symlink_to(fake_home / ".agents", target_is_directory=True)
    monkeypatch.setenv("SKILLDESK_PROJECTS", str(project))
    available = good(client.get("/api/maintenance/roots"))["items"]
    assert [r["path"] for r in available] == [str(root)]


def test_restart_recovers_interrupted_update(remote, client, fake_home, monkeypatch):
    root = fake_home / ".agents/skills"
    install(client, root)
    entry = root / "alpha"
    old = (entry / "SKILL.md").read_bytes()
    (remote / ALPHA).write_bytes(old + b" new")
    commit(remote)
    preview = good(change(client, entry, "update"))
    lock = lock_path(fake_home / ".agents/skills")
    before = json.loads(lock.read_text())
    write = maintenance.write_json
    recovery = maintenance.recover

    # Simulate termination after both filesystem and lockfile changed, before publication.
    def interrupt(path, value):
        if path.name == "result.json":
            raise OSError("interrupted")
        return write(path, value)

    monkeypatch.setattr(maintenance, "write_json", interrupt)
    monkeypatch.setattr(maintenance, "recover", lambda: None)
    assert post(client, "confirm", id=preview["id"]).status_code == 409
    assert (entry / "SKILL.md").read_bytes() != old
    monkeypatch.setattr(maintenance, "write_json", write)
    monkeypatch.setattr(maintenance, "recover", recovery)
    restarted = TestClient(create_app())
    assert good(restarted.get("/api/index"))["total"] == 1
    assert (entry / "SKILL.md").read_bytes() == old and json.loads(lock.read_text()) == before
    assert not (maintenance.plans() / "active.json").exists()


def test_keep_configured_tracking_branch_and_annotated_tag(remote, client, fake_home):
    root = fake_home / ".agents/skills"
    install(client, root)
    fixed = git(remote, "rev-parse", "HEAD")
    git(remote, "branch", "stable", fixed)
    git(
        remote,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "tag",
        "-a",
        "v1",
        "-m",
        "one",
    )
    (remote / ALPHA).write_text("new default branch bytes")
    commit(remote)
    lock = lock_path(root)
    for ref in ("stable", "v1", fixed):
        data = read_json(lock, {})
        data["skills"]["alpha"]["ref"] = ref
        write_json(lock, data)
        plan = good(change(client, root / "alpha", "update"))
        assert plan["commit"] == fixed
        good(post(client, "confirm", id=plan["id"]))
        assert "Release one" in (root / "alpha/SKILL.md").read_text()


def test_native_v2_content_hash_matches_reference_bytes(tmp_path):
    import hashlib

    from skilldesk.packages import cli_hash

    (tmp_path / "SKILL.md").write_bytes(b"A\r\nB\r\n")
    (tmp_path / "metadata.json").write_text("excluded by the skills CLI")
    (tmp_path / "local-link").symlink_to("SKILL.md")
    expected = hashlib.sha256(b"SKILL.md\x004\x00A\nB\nlocal-link\x004\x00A\nB\n")
    assert cli_hash(tmp_path) == expected.hexdigest()


def test_legacy_project_lock_preserves_version_and_computes_native_digest(
    remote, client, tmp_path, monkeypatch
):
    import hashlib

    project = tmp_path / "legacy"
    project.mkdir()
    lock = project / "skills-lock.json"
    write_json(lock, {"version": 1, "skills": {}})
    monkeypatch.setenv("SKILLDESK_PROJECTS", str(project))
    install(client, project / ".agents/skills", "skills/beta/SKILL.md")
    data = read_json(lock, {})
    assert data["version"] == 1
    assert (
        data["skills"]["beta"]["computedHash"]
        == hashlib.sha256(b"SKILL.md" + (remote / "skills/beta/SKILL.md").read_bytes()).hexdigest()
    )
