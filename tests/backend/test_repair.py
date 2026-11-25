"""Repairing dangling symlinks: relink to the store, or remove the dead link."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import write_skill
from skilldesk import index as index_mod
from skilldesk.config import Config
from skilldesk.health import detect
from skilldesk.repair import RepairError, fix_issue
from skilldesk.scan import scan
from skilldesk.server import create_app


def build(fake_home: Path) -> tuple[Path, list]:
    result = scan(Config())
    issues = detect(result.skills, result.dangling)
    database = fake_home / "index.db"
    index_mod.rebuild(result, issues, database)
    return database, issues


def dangling_id(issues: list, entry: Path) -> str:
    issue = next(item for item in issues if item.kind == "dangling_link" and item.target == str(entry))
    return issue.id


def make_dangling(fake_home: Path, name: str, target: str = "/nonexistent/skills-main/skills/engineering/x") -> Path:
    entry = fake_home / ".claude" / "skills" / name
    entry.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, entry)
    return entry


class TestRelink:
    def test_repoints_to_the_store_copy(self, fake_home: Path) -> None:
        store_copy = write_skill(fake_home / ".agents" / "skills", "alpha")
        entry = make_dangling(fake_home, "alpha")
        database, issues = build(fake_home)

        conn = index_mod.connect(database)
        try:
            result = fix_issue(conn, dangling_id(issues, entry))
        finally:
            conn.close()

        assert result["action"] == "relinked"
        assert entry.is_symlink() and entry.exists()
        assert Path(os.readlink(entry)) == store_copy
        assert result["previous"].startswith("/nonexistent/")

    def test_issue_disappears_after_a_rescan(self, fake_home: Path) -> None:
        write_skill(fake_home / ".agents" / "skills", "alpha")
        entry = make_dangling(fake_home, "alpha")
        database, issues = build(fake_home)
        conn = index_mod.connect(database)
        try:
            fix_issue(conn, dangling_id(issues, entry))
        finally:
            conn.close()

        result = scan(Config())
        kinds = [issue.kind for issue in detect(result.skills, result.dangling)]
        assert "dangling_link" not in kinds, "the repaired link must no longer dangle"
        assert any(record.dir_name == "alpha" and any(p.kind == "claude" for p in record.placements) for record in result.skills)

    def test_missing_copy_is_reported_instead_of_guessed(self, fake_home: Path) -> None:
        entry = make_dangling(fake_home, "gone")
        database, issues = build(fake_home)
        conn = index_mod.connect(database)
        try:
            with pytest.raises(RepairError) as raised:
                fix_issue(conn, dangling_id(issues, entry))
        finally:
            conn.close()
        assert raised.value.status == 409
        assert "没有找到同名的实体副本" in raised.value.message
        assert entry.is_symlink(), "a failed repair must not touch the link"


class TestRemove:
    def test_remove_drops_a_dead_link(self, fake_home: Path) -> None:
        entry = make_dangling(fake_home, "gone")
        database, issues = build(fake_home)
        conn = index_mod.connect(database)
        try:
            result = fix_issue(conn, dangling_id(issues, entry), "remove")
        finally:
            conn.close()
        assert result["action"] == "removed"
        assert not entry.is_symlink() and not entry.exists()


class TestRefusals:
    def test_unknown_issue_is_404(self, fake_home: Path) -> None:
        database, _issues = build(fake_home)
        conn = index_mod.connect(database)
        try:
            with pytest.raises(RepairError) as raised:
                fix_issue(conn, "nope")
        finally:
            conn.close()
        assert raised.value.status == 404

    def test_unclaimed_source_is_not_automatically_fixable(self, fake_home: Path) -> None:
        write_skill(fake_home / ".agents" / "skills", "alpha")
        database, issues = build(fake_home)
        unclaimed = next(item for item in issues if item.kind == "unclaimed_source")
        conn = index_mod.connect(database)
        try:
            with pytest.raises(RepairError) as raised:
                fix_issue(conn, unclaimed.id)
        finally:
            conn.close()
        assert raised.value.status == 400
        assert "人工判断" in raised.value.message

    def test_link_outside_known_roots_is_refused(self, fake_home: Path, tmp_path: Path) -> None:
        database, _issues = build(fake_home)
        outside = tmp_path / "elsewhere" / "alpha"
        outside.parent.mkdir(parents=True)
        os.symlink("/nonexistent/x", outside)
        conn = index_mod.connect(database)
        try:
            conn.execute(
                "INSERT INTO health_issue(id, kind, identity_key, target, detail, fixable) VALUES (?,?,?,?,?,?)",
                ("manual", "dangling_link", "", str(outside), "outside", 1),
            )
            conn.commit()
            with pytest.raises(RepairError) as raised:
                fix_issue(conn, "manual")
        finally:
            conn.close()
        assert raised.value.status == 400
        assert outside.is_symlink()


class TestRepairApi:
    def test_fix_endpoint_relinks_and_refreshes_counts(self, fake_home: Path) -> None:
        write_skill(fake_home / ".agents" / "skills", "alpha")
        entry = make_dangling(fake_home, "alpha")
        client = TestClient(create_app())
        headers = {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}

        issues = client.get("/api/issues", params={"kind": "dangling_link"}).json()["items"]
        issue = next(item for item in issues if item["target"] == str(entry))

        response = client.post(f"/api/issues/{issue['id']}/fix", headers=headers, json={"action": "auto"})
        assert response.status_code == 200
        body = response.json()
        assert body["action"] == "relinked"
        assert body["counts"]["dangling"] == 0
        assert client.get("/api/issues", params={"kind": "dangling_link"}).json()["items"] == []

    def test_fix_endpoint_requires_the_session_token(self, fake_home: Path) -> None:
        make_dangling(fake_home, "alpha")
        client = TestClient(create_app())
        issues = client.get("/api/issues", params={"kind": "dangling_link"}).json()["items"]
        assert client.post(f"/api/issues/{issues[0]['id']}/fix", json={"action": "auto"}).status_code == 403

    def test_unknown_issue_returns_404_from_the_api(self, fake_home: Path) -> None:
        client = TestClient(create_app())
        headers = {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}
        assert client.post("/api/issues/missing/fix", headers=headers, json={}).status_code == 404
