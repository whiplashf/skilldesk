"""SQLite index: rebuild, filters, facets, detail lookup, atomicity."""
from __future__ import annotations

import os
from pathlib import Path

from helpers import lock_entry, write_lockfile, write_skill
from skilldesk import index as index_mod
from skilldesk.config import Config
from skilldesk.health import detect
from skilldesk.scan import scan


def build_index(fake_home: Path, tmp_path: Path) -> Path:
    result = scan(Config())
    issues = detect(result.skills, result.dangling)
    path = tmp_path / "index.db"
    index_mod.rebuild(result, issues, path)
    return path


def seed(fake_home: Path) -> None:
    store = fake_home / ".agents" / "skills"
    claude = fake_home / ".claude" / "skills"
    write_skill(store, "alpha", description="alpha does frontend things")
    write_skill(store, "beta", description="beta does backend things")
    write_skill(store, "gamma", description="gamma is a mystery")
    os.symlink(store / "alpha", claude / "alpha")
    write_lockfile(
        fake_home,
        {
            "alpha": lock_entry("acme/pack", "skills/alpha/SKILL.md"),
            "beta": lock_entry("acme/pack", "skills/beta/SKILL.md"),
        },
    )
    os.symlink("/nonexistent/gone", claude / "gone")


class TestRebuild:
    def test_meta_and_counts(self, fake_home: Path, tmp_path: Path) -> None:
        seed(fake_home)
        path = build_index(fake_home, tmp_path)
        conn = index_mod.connect(path)
        try:
            meta = index_mod.meta(conn)
            counts = index_mod.counts(conn)
        finally:
            conn.close()
        assert meta["skills"] == "3"
        assert meta["placements"] == "4"
        assert meta["dangling"] == "1"
        assert counts == {"skills": 3, "placements": 4, "dangling": 1, "unclaimed": 1, "issues": 2, "roots": 3}

    def test_rebuild_leaves_no_temp_file(self, fake_home: Path, tmp_path: Path) -> None:
        seed(fake_home)
        path = build_index(fake_home, tmp_path)
        assert path.is_file()
        assert not list(tmp_path.glob("*.tmp"))

    def test_rebuild_is_idempotent(self, fake_home: Path, tmp_path: Path) -> None:
        seed(fake_home)
        path = build_index(fake_home, tmp_path)
        first = index_mod.counts(index_mod.connect(path))
        build_index(fake_home, tmp_path)
        assert index_mod.counts(index_mod.connect(path)) == first

    def test_roots_are_recorded(self, fake_home: Path, tmp_path: Path) -> None:
        seed(fake_home)
        conn = index_mod.connect(build_index(fake_home, tmp_path))
        try:
            roots = index_mod.list_roots(conn)
        finally:
            conn.close()
        assert roots[0]["kind"] == "agents"
        assert roots[0]["entries"] == 3
        assert any(root["kind"] == "claude" and root["exists"] for root in roots)


class TestQueries:
    def _conn(self, fake_home: Path, tmp_path: Path):
        seed(fake_home)
        return index_mod.connect(build_index(fake_home, tmp_path))

    def test_list_all(self, fake_home: Path, tmp_path: Path) -> None:
        conn = self._conn(fake_home, tmp_path)
        try:
            payload = index_mod.list_skills(conn)
        finally:
            conn.close()
        assert payload["total"] == 3
        assert [item["name"] for item in payload["items"]] == ["alpha", "beta", "gamma"]

    def test_query_matches_description(self, fake_home: Path, tmp_path: Path) -> None:
        conn = self._conn(fake_home, tmp_path)
        try:
            payload = index_mod.list_skills(conn, q="frontend")
        finally:
            conn.close()
        assert payload["total"] == 1
        assert payload["items"][0]["name"] == "alpha"

    def test_filter_by_host_kind(self, fake_home: Path, tmp_path: Path) -> None:
        conn = self._conn(fake_home, tmp_path)
        try:
            assert index_mod.list_skills(conn, host="claude")["total"] == 1
            assert index_mod.list_skills(conn, host="agents")["total"] == 3
            assert index_mod.list_skills(conn, host="project")["total"] == 0
        finally:
            conn.close()

    def test_filter_by_source(self, fake_home: Path, tmp_path: Path) -> None:
        conn = self._conn(fake_home, tmp_path)
        try:
            payload = index_mod.list_skills(conn, source="github.com/acme/pack")
        finally:
            conn.close()
        assert payload["total"] == 2

    def test_filter_by_confidence(self, fake_home: Path, tmp_path: Path) -> None:
        conn = self._conn(fake_home, tmp_path)
        try:
            assert index_mod.list_skills(conn, confidence="recorded")["total"] == 2
            assert index_mod.list_skills(conn, confidence="none")["total"] == 1
        finally:
            conn.close()

    def test_filter_by_health(self, fake_home: Path, tmp_path: Path) -> None:
        conn = self._conn(fake_home, tmp_path)
        try:
            payload = index_mod.list_skills(conn, health="unclaimed_source")
        finally:
            conn.close()
        assert payload["total"] == 1
        assert payload["items"][0]["name"] == "gamma"

    def test_pagination(self, fake_home: Path, tmp_path: Path) -> None:
        conn = self._conn(fake_home, tmp_path)
        try:
            first = index_mod.list_skills(conn, limit=2, offset=0)
            second = index_mod.list_skills(conn, limit=2, offset=2)
        finally:
            conn.close()
        assert first["total"] == second["total"] == 3
        assert len(first["items"]) == 2
        assert len(second["items"]) == 1
        assert not {item["name"] for item in first["items"]} & {item["name"] for item in second["items"]}

    def test_facets(self, fake_home: Path, tmp_path: Path) -> None:
        conn = self._conn(fake_home, tmp_path)
        try:
            facets = index_mod.facets(conn)
        finally:
            conn.close()
        assert {entry["value"]: entry["count"] for entry in facets["hosts"]} == {"agents": 3, "claude": 1}
        assert {entry["value"]: entry["count"] for entry in facets["confidence"]} == {"recorded": 2, "none": 1}
        assert {entry["value"]: entry["count"] for entry in facets["health"]} == {"unclaimed_source": 1, "dangling_link": 1}
        assert facets["sources"][0]["value"] == "github.com/acme/pack"
        assert facets["sources"][0]["count"] == 2

    def test_item_shape(self, fake_home: Path, tmp_path: Path) -> None:
        conn = self._conn(fake_home, tmp_path)
        try:
            item = index_mod.list_skills(conn, q="alpha")["items"][0]
        finally:
            conn.close()
        assert item["identity_key"].startswith("src:github.com/acme/pack@")
        assert item["host_kinds"] == ["agents", "claude"]
        assert item["placement_count"] == 2
        assert item["primary_kind"] == "agents"
        assert item["provenance"]["confidence"] == "recorded"
        assert item["provenance"]["label"] == "github.com/acme/pack"
        assert item["health"] == []


class TestDetail:
    def test_get_skill_returns_placements_and_issues(self, fake_home: Path, tmp_path: Path) -> None:
        seed(fake_home)
        conn = index_mod.connect(build_index(fake_home, tmp_path))
        try:
            key = index_mod.list_skills(conn, q="gamma")["items"][0]["identity_key"]
            skill = index_mod.get_skill(conn, key)
        finally:
            conn.close()
        assert skill is not None
        assert len(skill["placements"]) == 1
        assert [issue["kind"] for issue in skill["issues"]] == ["unclaimed_source"]

    def test_get_skill_missing_returns_none(self, fake_home: Path, tmp_path: Path) -> None:
        seed(fake_home)
        conn = index_mod.connect(build_index(fake_home, tmp_path))
        try:
            assert index_mod.get_skill(conn, "src:nope/nope@x") is None
        finally:
            conn.close()

    def test_issues_filter_by_kind(self, fake_home: Path, tmp_path: Path) -> None:
        seed(fake_home)
        conn = index_mod.connect(build_index(fake_home, tmp_path))
        try:
            dangling = index_mod.list_issues(conn, kind="dangling_link")
        finally:
            conn.close()
        assert len(dangling) == 1
        assert dangling[0]["target"].endswith("/skills/gone")
