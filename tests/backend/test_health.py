"""Health detection: dangling links, unclaimed provenance, duplicate content."""
from __future__ import annotations

import os
from pathlib import Path

from helpers import lock_entry, write_lockfile, write_skill
from skilldesk.config import Config
from skilldesk.health import KINDS, detect
from skilldesk.scan import scan


def _issues(fake_home: Path) -> list:
    result = scan(Config())
    return detect(result.skills, result.dangling)


class TestHealthDetection:
    def test_all_kinds_are_declared(self) -> None:
        for kind in KINDS.values():
            assert {"label", "severity", "fixable", "description"} <= set(kind)

    def test_dangling_link_issue(self, fake_home: Path) -> None:
        os.symlink("/nonexistent/x", fake_home / ".claude" / "skills" / "broken")
        issues = _issues(fake_home)
        assert [issue.kind for issue in issues] == ["dangling_link"]
        issue = issues[0]
        assert issue.fixable is True
        assert issue.identity_key == ""
        assert issue.target.endswith("/skills/broken")
        assert "nonexistent" in issue.detail

    def test_unclaimed_source_issue(self, fake_home: Path) -> None:
        write_skill(fake_home / ".agents" / "skills", "alpha")
        issues = _issues(fake_home)
        assert [issue.kind for issue in issues] == ["unclaimed_source"]
        assert issues[0].identity_key.startswith("loc:")
        assert issues[0].target == issues[0].identity_key

    def test_claimed_skill_has_no_issue(self, fake_home: Path) -> None:
        store = fake_home / ".agents" / "skills"
        write_skill(store, "beta")
        write_lockfile(fake_home, {"beta": lock_entry("acme/pack", "skills/beta/SKILL.md")})
        assert _issues(fake_home) == []

    def test_duplicate_content_reports_both_sides(self, fake_home: Path) -> None:
        store = fake_home / ".agents" / "skills"
        # identical bytes in two directories: the real-world case of one skill
        # vendored by two upstream repos.
        content = "---\nname: shared\ndescription: same description\n---\n\n# Same\n\nidentical body\n"
        for directory in ("one", "two"):
            (store / directory).mkdir(parents=True, exist_ok=True)
            (store / directory / "SKILL.md").write_text(content, encoding="utf-8")
        write_lockfile(
            fake_home,
            {
                "one": lock_entry("acme/one", "skills/one/SKILL.md"),
                "two": lock_entry("acme/two", "skills/two/SKILL.md"),
            },
        )
        issues = [issue for issue in _issues(fake_home) if issue.kind == "duplicate_content"]
        assert len(issues) == 2
        assert all(issue.fixable is False for issue in issues)

    def test_issue_ids_are_stable_and_unique(self, fake_home: Path) -> None:
        os.symlink("/nonexistent/a", fake_home / ".claude" / "skills" / "a")
        os.symlink("/nonexistent/b", fake_home / ".claude" / "skills" / "b")
        first = [issue.id for issue in _issues(fake_home)]
        second = [issue.id for issue in _issues(fake_home)]
        assert first == second
        assert len(set(first)) == len(first) == 2

    def test_dangling_issues_sort_before_unclaimed(self, fake_home: Path) -> None:
        write_skill(fake_home / ".agents" / "skills", "alpha")
        os.symlink("/nonexistent/a", fake_home / ".claude" / "skills" / "a")
        kinds = [issue.kind for issue in _issues(fake_home)]
        assert kinds == sorted(kinds)
        assert kinds[0] == "dangling_link"
