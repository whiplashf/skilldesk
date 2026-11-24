"""Local discovery: placements, dedupe by real path, dangling links, identity."""
from __future__ import annotations

import os
from pathlib import Path

from helpers import lock_entry, write_lockfile, write_skill
from skilldesk.config import Config
from skilldesk.scan import scan


class TestScanPlacements:
    def test_symlinked_skill_is_one_entity_with_two_placements(self, fake_home: Path) -> None:
        store = fake_home / ".agents" / "skills"
        claude = fake_home / ".claude" / "skills"
        write_skill(store, "alpha")
        os.symlink(store / "alpha", claude / "alpha")

        result = scan(Config())
        skill = next(item for item in result.skills if item.dir_name == "alpha")
        assert len(skill.placements) == 2
        assert {placement.kind for placement in skill.placements} == {"agents", "claude"}
        assert skill.primary_kind == "agents"
        assert any(placement.is_symlink for placement in skill.placements)

    def test_same_entity_through_three_roots_counts_once(self, fake_home: Path) -> None:
        store = fake_home / ".agents" / "skills"
        claude = fake_home / ".claude" / "skills"
        opencode = fake_home / ".config" / "opencode" / "skills"
        write_skill(store, "beta")
        os.symlink(store / "beta", claude / "beta")
        os.symlink(store / "beta", opencode / "beta")

        result = scan(Config())
        assert sum(1 for skill in result.skills if skill.dir_name == "beta") == 1
        assert len(next(skill for skill in result.skills if skill.dir_name == "beta").placements) == 3

    def test_entries_without_skill_md_are_ignored(self, fake_home: Path) -> None:
        store = fake_home / ".agents" / "skills"
        (store / "not-a-skill").mkdir(parents=True)
        (store / "not-a-skill" / "README.md").write_text("hi", encoding="utf-8")
        result = scan(Config())
        assert all(skill.dir_name != "not-a-skill" for skill in result.skills)

    def test_empty_roots_yield_nothing(self, fake_home: Path) -> None:
        result = scan(Config())
        assert result.skills == []
        assert result.dangling == []


class TestDanglingLinks:
    def test_broken_symlink_is_reported_not_counted_as_skill(self, fake_home: Path) -> None:
        claude = fake_home / ".claude" / "skills"
        os.symlink("/nonexistent/skills-main/skills/engineering/ask-matt", claude / "ask-matt")

        result = scan(Config())
        assert result.skills == []
        assert len(result.dangling) == 1
        entry = result.dangling[0]
        assert entry.entry == "ask-matt"
        assert entry.kind == "claude"
        assert entry.target == "/nonexistent/skills-main/skills/engineering/ask-matt"

    def test_link_to_a_directory_without_skill_md_is_not_dangling(self, fake_home: Path) -> None:
        target = fake_home / "target"
        target.mkdir()
        os.symlink(target, fake_home / ".claude" / "skills" / "empty")
        result = scan(Config())
        assert result.dangling == []
        assert result.skills == []


class TestIdentityDuringScan:
    def test_lockfile_gives_recorded_source_and_src_key(self, fake_home: Path) -> None:
        store = fake_home / ".agents" / "skills"
        write_skill(store, "gamma")
        write_lockfile(fake_home, {"gamma": lock_entry("acme/pack", "skills/gamma/SKILL.md")})

        skill = scan(Config()).skills[0]
        assert skill.provenance.confidence == "recorded"
        assert skill.identity_key == "src:github.com/acme/pack@skills/gamma/SKILL.md"

    def test_unknown_source_gives_loc_key(self, fake_home: Path) -> None:
        store = fake_home / ".agents" / "skills"
        write_skill(store, "delta")

        skill = scan(Config()).skills[0]
        assert skill.provenance.confidence == "none"
        assert skill.identity_key.startswith("loc:")

    def test_two_directories_with_same_upstream_merge_into_one_skill(self, fake_home: Path) -> None:
        store = fake_home / ".agents" / "skills"
        write_skill(store, "one")
        write_skill(store, "two")
        write_lockfile(
            fake_home,
            {
                "one": lock_entry("acme/pack", "skills/shared/SKILL.md"),
                "two": lock_entry("acme/pack", "skills/shared/SKILL.md"),
            },
        )

        result = scan(Config())
        assert len(result.skills) == 1
        assert result.skills[0].identity_key == "src:github.com/acme/pack@skills/shared/SKILL.md"
        assert len(result.skills[0].placements) == 2

    def test_frontmatter_fields_drive_display_not_identity(self, fake_home: Path) -> None:
        store = fake_home / ".agents" / "skills"
        write_skill(store, "epsilon", description="This skill should be used when the user asks to do things.")
        skill = scan(Config()).skills[0]
        assert skill.name == "epsilon"
        assert skill.description.startswith("Do things.")
        assert skill.license == ""


class TestScanScope:
    def test_disabled_root_contributes_nothing(self, fake_home: Path) -> None:
        store = fake_home / ".agents" / "skills"
        write_skill(store, "zeta")
        result = scan(Config(disabled_roots=[str(store)]))
        assert result.skills == []

    def test_project_root_is_scanned(self, fake_home: Path, tmp_path: Path) -> None:
        project = tmp_path / "proj"
        project_skills = project / ".agents" / "skills"
        project_skills.mkdir(parents=True)
        write_skill(project_skills, "project-skill")

        result = scan(Config(projects=[str(project)]))
        skill = next(item for item in result.skills if item.dir_name == "project-skill")
        assert skill.primary_kind == "project"
        assert skill.provenance.confidence == "none"
