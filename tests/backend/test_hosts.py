"""Host root discovery: dedupe, priority, project roots, disabled roots."""
from __future__ import annotations

import os
from pathlib import Path

from skilldesk.config import Config, load_config
from skilldesk.hosts import discover_roots


def _reals(roots) -> set[str]:
    return {os.path.realpath(str(root.path)) for root in roots}


class TestDiscoverRoots:
    def test_store_candidates_come_first(self, fake_home: Path) -> None:
        roots = discover_roots(Config())
        assert roots[0].kind == "agents"
        assert roots[0].priority == 0
        assert roots[0].exists is True

    def test_missing_roots_are_reported_but_not_dropped(self, fake_home: Path) -> None:
        roots = discover_roots(Config())
        codex = [root for root in roots if root.kind == "codex"]
        assert codex, "codex root should still be a candidate"
        assert codex[0].exists is False

    def test_project_roots_from_config(self, fake_home: Path, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        (project / ".agents" / "skills").mkdir(parents=True)
        roots = discover_roots(Config(projects=[str(project)]))
        project_roots = [root for root in roots if root.kind == "project"]
        assert len(project_roots) == 3, "one candidate per supported project layout"
        existing = [root for root in project_roots if root.exists]
        assert len(existing) == 1
        assert existing[0].priority == 1

    def test_project_roots_from_env(self, fake_home: Path, tmp_path: Path, monkeypatch) -> None:
        project = tmp_path / "p2"
        (project / ".claude" / "skills").mkdir(parents=True)
        monkeypatch.setenv("SKILLDESK_PROJECTS", str(project))
        config = load_config()
        assert str(project) in config.projects
        roots = discover_roots(config)
        assert any(root.kind == "project" and root.exists for root in roots)

    def test_disabled_root_is_excluded(self, fake_home: Path) -> None:
        agents = fake_home / ".agents" / "skills"
        roots = discover_roots(Config(disabled_roots=[str(agents)]))
        assert os.path.realpath(agents) not in _reals(roots)

    def test_duplicate_roots_are_collapsed(self, fake_home: Path, tmp_path: Path) -> None:
        store = fake_home / ".agents" / "skills"
        alias = tmp_path / "alias"
        os.symlink(store, alias)
        roots = discover_roots(Config(extra_roots=[{"path": str(alias), "label": "alias"}]))
        reals = [os.path.realpath(str(root.path)) for root in roots]
        assert len(reals) == len(set(reals))

    def test_extra_root_from_config(self, fake_home: Path, tmp_path: Path) -> None:
        extra = tmp_path / "custom-skills"
        extra.mkdir()
        roots = discover_roots(Config(extra_roots=[{"path": str(extra), "label": "mine"}]))
        custom = [root for root in roots if root.kind == "custom"]
        assert custom and custom[0].label == "mine" and custom[0].exists
