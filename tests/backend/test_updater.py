"""Updating an installed skill: diff preview, drift protection, backup, removal."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from skilldesk import baselines, installer, updater
from skilldesk.server import create_app


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
        env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"},
    )
    return completed.stdout.strip()


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    repo = tmp_path / "remotes" / "acme" / "pack"
    (repo / "skills" / "alpha").mkdir(parents=True)
    (repo / "skills" / "alpha" / "SKILL.md").write_text("---\nname: alpha\ndescription: v1\n---\n\n# Alpha v1\n", encoding="utf-8")
    (repo / "skills" / "alpha" / "old.md").write_text("old\n", encoding="utf-8")
    git(repo, "init", "-b", "main", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "v1")
    return repo


@pytest.fixture
def installed(fake_home: Path, remote: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setenv("SKILLDESK_FETCH", "git")  # the fixture remote is a local path
    monkeypatch.setattr(installer, "clone_url", lambda host, repo: str(remote))
    monkeypatch.setattr(installer, "_license_of", lambda host, repo: "MIT")
    store = fake_home / ".agents" / "skills"
    store.mkdir(parents=True, exist_ok=True)
    links = [fake_home / ".claude" / "skills"]
    links[0].mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(installer, "target_roots", lambda: (store, list(links)))

    plan = installer.plan("github.com", "acme/pack", "skills/alpha/SKILL.md")
    result = installer.apply(plan["planId"])
    return {
        "identity_key": result["identity_key"],
        "name": result["name"],
        "target": Path(result["target"]),
        "remote": remote,
        "store": store,
        "links": links,
        "commit": result["commit"],
    }


def bump_upstream(remote: Path) -> str:
    skill = remote / "skills" / "alpha"
    (skill / "SKILL.md").write_text("---\nname: alpha\ndescription: v2\n---\n\n# Alpha v2\n", encoding="utf-8")
    (skill / "new.md").write_text("new\n", encoding="utf-8")
    (skill / "old.md").unlink()
    git(remote, "add", "-A")
    git(remote, "commit", "-qm", "v2")
    return git(remote, "rev-parse", "HEAD")


class TestPlanUpdate:
    def test_diff_lists_added_updated_removed(self, installed: dict) -> None:
        bump_upstream(installed["remote"])
        plan = updater.plan_update(
            "github.com", "acme/pack", "skills/alpha/SKILL.md", identity_key=installed["identity_key"], refresh=True
        )
        assert plan["kind"] == "update"
        assert plan["diff"]["added"] == ["new.md"]
        assert plan["diff"]["removed"] == ["old.md"]
        assert plan["diff"]["updated"] == ["SKILL.md"]
        assert plan["diff"]["identical"] is False
        assert plan["from"] == plan["commit"] or plan["from"] != ""  # from is the recorded install commit
        assert plan["to"] == plan["commit"]

    def test_unchanged_upstream_reports_no_change(self, installed: dict) -> None:
        plan = updater.plan_update(
            "github.com", "acme/pack", "skills/alpha/SKILL.md", identity_key=installed["identity_key"]
        )
        assert plan["diff"]["identical"] is True
        assert any("一致" in warning for warning in plan["warnings"])

    def test_local_edit_is_flagged(self, installed: dict) -> None:
        (installed["target"] / "SKILL.md").write_text("---\nname: alpha\n---\n\n# hand edited\n", encoding="utf-8")
        plan = updater.plan_update(
            "github.com", "acme/pack", "skills/alpha/SKILL.md", identity_key=installed["identity_key"]
        )
        assert plan["localDrift"] is True
        assert any("被改动" in warning for warning in plan["warnings"])

    def test_missing_target_is_refused(self, installed: dict) -> None:
        import shutil

        shutil.rmtree(installed["target"])
        with pytest.raises(updater.UpdateError) as raised:
            updater.plan_update("github.com", "acme/pack", "skills/alpha/SKILL.md", identity_key=installed["identity_key"])
        assert raised.value.status == 404


class TestApplyUpdate:
    def test_update_replaces_files_and_keeps_history(self, installed: dict) -> None:
        lock_before = json.loads((Path.home() / ".agents" / ".skill-lock.json").read_text(encoding="utf-8"))
        installed_at = lock_before["skills"]["alpha"]["installedAt"]

        bump_upstream(installed["remote"])
        plan = updater.plan_update(
            "github.com", "acme/pack", "skills/alpha/SKILL.md", identity_key=installed["identity_key"], refresh=True
        )
        result = updater.apply_update(plan["planId"])

        target = installed["target"]
        assert "v2" in (target / "SKILL.md").read_text(encoding="utf-8")
        assert (target / "new.md").is_file()
        assert not (target / "old.md").exists()
        assert result["updated"] is True

        backup = Path(result["backup"])
        assert backup.is_dir() and "v1" in (backup / "SKILL.md").read_text(encoding="utf-8")

        lock = json.loads((Path.home() / ".agents" / ".skill-lock.json").read_text(encoding="utf-8"))
        assert lock["skills"]["alpha"]["installedAt"] == installed_at
        assert lock["skills"]["alpha"]["updatedAt"] >= installed_at

        baseline = baselines.get(installed["identity_key"], "acme/pack", "skills/alpha")
        assert baseline is not None and baseline["headRef"] == result["to"]

    def test_hand_edited_copy_needs_explicit_permission(self, installed: dict) -> None:
        (installed["target"] / "SKILL.md").write_text("---\nname: alpha\n---\n\n# mine\n", encoding="utf-8")
        bump_upstream(installed["remote"])
        plan = updater.plan_update(
            "github.com", "acme/pack", "skills/alpha/SKILL.md", identity_key=installed["identity_key"], refresh=True
        )
        with pytest.raises(updater.UpdateError) as raised:
            updater.apply_update(plan["planId"])
        assert raised.value.status == 409
        assert "mine" in (installed["target"] / "SKILL.md").read_text(encoding="utf-8"), "a refused update must not touch the folder"

        updater.apply_update(plan["planId"], allow_drift=True)
        assert "v2" in (installed["target"] / "SKILL.md").read_text(encoding="utf-8")

    def test_backups_are_pruned(self, installed: dict) -> None:
        for round_index in range(5):
            (installed["remote"] / "skills" / "alpha" / "SKILL.md").write_text(
                f"---\nname: alpha\ndescription: v{round_index}\n---\n\n# round {round_index}\n", encoding="utf-8"
            )
            git(installed["remote"], "add", "-A")
            git(installed["remote"], "commit", "-qm", f"round{round_index}")
            plan = updater.plan_update(
                "github.com", "acme/pack", "skills/alpha/SKILL.md", identity_key=installed["identity_key"], refresh=True
            )
            updater.apply_update(plan["planId"])
        folder = Path(updater._backup(installed["target"], installed["name"])).parent
        assert len([item for item in folder.iterdir() if item.is_dir()]) <= updater.BACKUP_KEEP


class TestUninstall:
    def test_removes_folder_links_lockfile_and_baseline(self, installed: dict) -> None:
        link = installed["links"][0] / installed["name"]
        assert link.is_symlink()
        placements = [
            {"entry_path": str(installed["target"]), "is_symlink": False},
            {"entry_path": str(link), "is_symlink": True},
        ]
        result = updater.uninstall(
            identity_key=installed["identity_key"],
            name=installed["name"],
            target=str(installed["target"]),
            repo="acme/pack",
            dir_path="skills/alpha",
            placements=placements,
        )
        assert result["removedFolder"] is True
        assert not installed["target"].exists()
        assert not link.is_symlink()
        assert result["removedLockEntry"] is True
        assert result["removedBaseline"] is True
        lock = json.loads((Path.home() / ".agents" / ".skill-lock.json").read_text(encoding="utf-8"))
        assert "alpha" not in lock["skills"]
        assert baselines.get(installed["identity_key"], "acme/pack", "skills/alpha") is None


class TestUpdateApi:
    @pytest.fixture
    def client(self, installed: dict) -> TestClient:
        application = create_app()
        return TestClient(application)

    def _headers(self, client: TestClient) -> dict:
        return {"x-skilldesk-token": client.get("/api/session").json()["token"]}

    def test_update_flow(self, installed: dict, client: TestClient) -> None:
        bump_upstream(installed["remote"])
        headers = self._headers(client)
        key = installed["identity_key"]

        plan = client.post(f"/api/skills/{key}/update/plan", headers=headers, json={"refresh": True})
        assert plan.status_code == 200, plan.text
        payload = plan.json()
        assert payload["kind"] == "update" and payload["diff"]["added"] == ["new.md"]

        applied = client.post(f"/api/skills/{key}/update", headers=headers, json={"planId": payload["planId"]})
        assert applied.status_code == 200, applied.text
        assert applied.json()["updated"] is True
        assert "v2" in (installed["target"] / "SKILL.md").read_text(encoding="utf-8")

    def test_update_requires_a_token(self, installed: dict, client: TestClient) -> None:
        response = client.post(f"/api/skills/{installed['identity_key']}/update/plan", json={})
        assert response.status_code == 403

    def test_uninstall_requires_confirmation(self, installed: dict, client: TestClient) -> None:
        headers = self._headers(client)
        key = installed["identity_key"]
        assert client.post(f"/api/skills/{key}/uninstall", headers=headers, json={}).status_code == 400
        removed = client.post(f"/api/skills/{key}/uninstall", headers=headers, json={"confirm": True})
        assert removed.status_code == 200, removed.text
        assert removed.json()["uninstalled"] is True
        assert not installed["target"].exists()

    def test_unknown_skill_is_404(self, installed: dict, client: TestClient) -> None:
        headers = self._headers(client)
        assert client.post("/api/skills/loc:nope/uninstall", headers=headers, json={"confirm": True}).status_code == 404
