"""Registry + installer: coordinates, planning, and the writes an install performs."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from helpers import write_skill
from skilldesk import baselines, installer, registry


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"},
    )
    return completed.stdout.strip()


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A local git repository shaped like a skills repo."""
    repo = tmp_path / "remotes" / "acme" / "pack"
    (repo / "skills" / "alpha").mkdir(parents=True)
    (repo / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: alpha skill\n---\n\n# Alpha\n", encoding="utf-8"
    )
    (repo / "skills" / "alpha" / "references").mkdir()
    (repo / "skills" / "alpha" / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (repo / "skills" / "alpha" / "scripts").mkdir()
    (repo / "skills" / "alpha" / "scripts" / "run.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (repo / "LICENSE").write_text("MIT\n", encoding="utf-8")
    git(repo, "init", "-b", "main", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "initial")
    return repo


@pytest.fixture
def wired(fake_home: Path, remote: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the installer at the local remote and the throwaway HOME."""
    monkeypatch.setenv("SKILLDESK_FETCH", "git")  # the fixture remote is a local path
    monkeypatch.setattr(installer, "clone_url", lambda host, repo: str(remote))
    monkeypatch.setattr(installer, "_license_of", lambda host, repo: "MIT")
    store = fake_home / ".agents" / "skills"
    store.mkdir(parents=True, exist_ok=True)
    links = [fake_home / ".claude" / "skills", fake_home / ".config" / "opencode" / "skills"]
    for link in links:
        link.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(installer, "target_roots", lambda: (store, list(links)))
    return {"store": store, "links": links, "remote": remote}


class TestRegistryFiles:
    def test_shipped_default_is_readable(self, fake_home: Path) -> None:
        payload = registry.entries()
        assert payload["entries"], "the shipped registry must contain coordinates"
        assert all(entry["path"].endswith("SKILL.md") for entry in payload["entries"])
        assert all("host" in entry and "repo" in entry for entry in payload["entries"])

    def test_user_source_is_merged(self, fake_home: Path, tmp_path: Path) -> None:
        extra = tmp_path / "mine.json"
        extra.write_text(json.dumps({"entries": [{"repo": "me/skills", "path": "x/SKILL.md"}]}), encoding="utf-8")
        registry.add_source(str(extra))
        entries = registry.entries()["entries"]
        assert any(entry["repo"] == "me/skills" and entry["host"] == "github.com" for entry in entries)

    def test_bad_rows_are_dropped(self, fake_home: Path, tmp_path: Path) -> None:
        extra = tmp_path / "bad.json"
        extra.write_text(
            json.dumps({"entries": [{"repo": "no-slash", "path": "x/SKILL.md"}, {"repo": "a/b", "path": "x/readme.md"}]}),
            encoding="utf-8",
        )
        registry.add_source(str(extra))
        assert all(entry["repo"] != "no-slash" for entry in registry.entries()["entries"])

    def test_missing_file_is_reported_not_fatal(self, fake_home: Path) -> None:
        registry.add_source("/nonexistent/registry.json")
        payload = registry.entries()
        assert payload["entries"], "default entries still load"
        assert any(error["path"] == "/nonexistent/registry.json" for error in payload["errors"])

    def test_toggle_and_remove(self, fake_home: Path, tmp_path: Path) -> None:
        extra = tmp_path / "mine.json"
        extra.write_text(json.dumps({"entries": []}), encoding="utf-8")
        added = registry.add_source(str(extra))
        assert registry.set_enabled(added["id"], False) is True
        assert any(source["id"] == added["id"] and not source["enabled"] for source in registry.sources())
        assert registry.remove_source(added["id"]) is True
        assert all(source["id"] != added["id"] for source in registry.sources())

    def test_hand_added_entry_persists(self, fake_home: Path) -> None:
        registry.save_entry({"host": "github.com", "repo": "acme/one", "path": "s/SKILL.md", "license": "", "description": ""})
        assert any(entry["repo"] == "acme/one" for entry in registry.entries()["entries"])


class TestPlan:
    def test_plan_lists_files_scripts_and_license(self, wired) -> None:
        result = installer.plan("github.com", "acme/pack", "skills/alpha/SKILL.md")
        paths = {item["path"] for item in result["files"]}
        assert {"SKILL.md", "references/guide.md", "scripts/run.sh"} <= paths
        assert result["scripts"] == ["scripts/run.sh"]
        assert result["license"] == "MIT"
        assert result["name"] == "alpha"
        assert Path(result["target"]) == wired["store"] / "alpha"
        assert result["warnings"] == [] or all(isinstance(item, str) for item in result["warnings"])

    def test_plan_warns_when_the_target_exists(self, wired) -> None:
        write_skill(wired["store"], "alpha")
        result = installer.plan("github.com", "acme/pack", "skills/alpha/SKILL.md")
        assert any("目标已存在" in warning for warning in result["warnings"])

    def test_plan_warns_about_a_missing_license(self, wired, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(installer, "_license_of", lambda host, repo: "")
        result = installer.plan("github.com", "acme/pack", "skills/alpha/SKILL.md")
        assert result["license"] == ""
        assert any("许可证" in warning for warning in result["warnings"])

    def test_unknown_skill_directory(self, wired) -> None:
        with pytest.raises(installer.InstallError) as raised:
            installer.plan("github.com", "acme/pack", "skills/missing/SKILL.md")
        assert raised.value.status == 404

    def test_bad_coordinates_are_rejected(self, wired) -> None:
        for repo, path in (("acme", "skills/alpha/SKILL.md"), ("acme/pack", "../SKILL.md")):
            with pytest.raises(installer.InstallError):
                installer.plan("github.com", repo, path)


class TestApply:
    def test_install_writes_files_lockfile_links_and_baseline(self, wired) -> None:
        plan = installer.plan("github.com", "acme/pack", "skills/alpha/SKILL.md")
        result = installer.apply(plan["planId"])

        target = Path(result["target"])
        assert (target / "SKILL.md").is_file()
        assert (target / "references" / "guide.md").is_file()
        assert result["license"] == "MIT"
        assert result["scripts"] == ["scripts/run.sh"]

        lock = json.loads((Path.home() / ".agents" / ".skill-lock.json").read_text(encoding="utf-8"))
        assert lock["skills"]["alpha"]["skillPath"] == "skills/alpha/SKILL.md"
        assert lock["skills"]["alpha"]["sourceUrl"].endswith("acme/pack")

        for link in wired["links"]:
            entry = link / "alpha"
            assert entry.is_symlink() and entry.exists()

        baseline = baselines.get(result["identity_key"], "acme/pack", "skills/alpha")
        assert baseline is not None and baseline["dirTree"]

    def test_unknown_license_needs_acknowledgement(self, wired, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(installer, "_license_of", lambda host, repo: "")
        plan = installer.plan("github.com", "acme/pack", "skills/alpha/SKILL.md")
        with pytest.raises(installer.InstallError) as raised:
            installer.apply(plan["planId"])
        assert raised.value.status == 409
        assert not (wired["store"] / "alpha").exists()

        installer.apply(plan["planId"], acknowledge_license=True)
        assert (wired["store"] / "alpha" / "SKILL.md").is_file()

    def test_existing_target_requires_force(self, wired) -> None:
        write_skill(wired["store"], "alpha")
        plan = installer.plan("github.com", "acme/pack", "skills/alpha/SKILL.md")
        with pytest.raises(installer.InstallError) as raised:
            installer.apply(plan["planId"])
        assert raised.value.status == 409

        installer.apply(plan["planId"], force=True)
        assert (wired["store"] / "alpha" / "references" / "guide.md").is_file()

    def test_upstream_moved_after_planning(self, wired) -> None:
        plan = installer.plan("github.com", "acme/pack", "skills/alpha/SKILL.md")
        remote = wired["remote"]
        (remote / "skills" / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n\n# Changed\n", encoding="utf-8")
        git(remote, "commit", "-qam", "second")
        with pytest.raises(installer.InstallError) as raised:
            installer.apply(plan["planId"])
        assert raised.value.status == 409
        assert "新提交" in raised.value.message

    def test_expired_plan_is_refused(self, wired) -> None:
        plan = installer.plan("github.com", "acme/pack", "skills/alpha/SKILL.md")
        plan["expiresAt"] = 0
        path = installer.plans_dir() / (plan["planId"].replace("/", "_").replace(":", "__") + ".json")
        path.write_text(json.dumps(plan), encoding="utf-8")
        with pytest.raises(installer.InstallError) as raised:
            installer.apply(plan["planId"])
        assert raised.value.status == 409

    def test_unknown_plan(self, wired) -> None:
        with pytest.raises(installer.InstallError) as raised:
            installer.apply("github.com:nope@x#deadbeef")
        assert raised.value.status == 404


class TestImport:
    def test_import_caches_only_the_skill_md(self, wired) -> None:
        result = installer.import_only("github.com", "acme/pack", "skills/alpha/SKILL.md")
        cached = Path(result["cached"])
        assert cached.is_file() and "name: alpha" in cached.read_text(encoding="utf-8")
        assert not (wired["store"] / "alpha").exists(), "importing must not install anything"

    def test_second_import_reuses_the_cache(self, wired) -> None:
        first = installer.import_only("github.com", "acme/pack", "skills/alpha/SKILL.md")
        second = installer.import_only("github.com", "acme/pack", "skills/alpha/SKILL.md")
        assert first["imported"] is True
        assert second["imported"] is False


class TestFetchStrategy:
    def test_github_uses_the_tarball(self) -> None:
        assert installer.fetch_strategy("github.com") == "tarball"

    def test_other_hosts_use_git(self) -> None:
        assert installer.fetch_strategy("git.example.com") == "git"

    def test_env_override_forces_git(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKILLDESK_FETCH", "git")
        assert installer.fetch_strategy("github.com") == "git"


class TestWrongPathHint:
    def test_a_single_skill_md_is_used_automatically(self, wired) -> None:
        """Pasting just the repository URL is enough when the repo has one skill."""
        plan = installer.plan("github.com", "acme/pack", "SKILL.md")
        assert plan["resolved"] is True
        assert plan["path"] == "skills/alpha/SKILL.md"
        assert plan["requestedPath"] == "SKILL.md"
        assert plan["name"] == "alpha"

    def test_several_skills_are_reported_instead_of_guessed(self, wired) -> None:
        extra = wired["remote"] / "skills" / "bravo"
        extra.mkdir(parents=True)
        (extra / "SKILL.md").write_text("---\nname: bravo\n---\n\n# Bravo\n", encoding="utf-8")
        git(wired["remote"], "add", "-A")
        git(wired["remote"], "commit", "-qm", "second skill")
        with pytest.raises(installer.InstallError) as raised:
            installer.plan("github.com", "acme/pack", "SKILL.md", refresh=True)
        assert raised.value.status == 404
        assert "可用的 SKILL.md" in raised.value.message
        assert set(raised.value.candidates) == {"skills/alpha/SKILL.md", "skills/bravo/SKILL.md"}

    def test_candidates_walk_a_prepared_tree(self, wired, tmp_path: Path) -> None:
        root = tmp_path / "tree"
        (root / "skills" / "one").mkdir(parents=True)
        (root / "skills" / "one" / "SKILL.md").write_text("x", encoding="utf-8")
        (root / "other").mkdir()
        (root / "other" / "SKILL.md").write_text("y", encoding="utf-8")
        found = installer._tar_candidates(root)
        assert found == ["other/SKILL.md", "skills/one/SKILL.md"]


class TestArchiveGuards:
    def test_archive_too_large_is_a_413(self) -> None:
        error = installer.ArchiveTooLarge(installer.MAX_ARCHIVE_BYTES + 1)
        assert error.status == 413
        assert "MB" in error.message

    def test_archive_too_slow_is_a_504(self) -> None:
        error = installer.ArchiveTooSlow(1024)
        assert error.status == 504
        assert "超时" in error.message
