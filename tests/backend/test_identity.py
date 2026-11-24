"""Provenance inference and identity keys."""
from __future__ import annotations

from pathlib import Path

from helpers import lock_entry, write_skill
from skilldesk.identity import (
    DECLARED,
    NONE,
    RECORDED,
    Provenance,
    clean_path,
    identity_key,
    infer_provenance,
    load_lockfile,
    normalize_source,
    parse_identity_key,
    placement_fingerprint,
)


class TestNormalizeSource:
    def test_https_url(self) -> None:
        assert normalize_source("https://github.com/mattpocock/skills.git") == ("github.com", "mattpocock/skills")

    def test_https_url_without_git_suffix(self) -> None:
        assert normalize_source("https://github.com/Nutlope/hallmark") == ("github.com", "Nutlope/hallmark")

    def test_scp_style(self) -> None:
        assert normalize_source("git@github.com:owner/repo.git") == ("github.com", "owner/repo")

    def test_nested_group_keeps_every_segment(self) -> None:
        """Self-hosted hosts nest groups; dropping segments would merge sibling repos."""
        assert normalize_source("https://git.example.com/group/subgroup/plugin.git") == (
            "git.example.com",
            "group/subgroup/plugin",
        )

    def test_display_label_with_host(self) -> None:
        assert normalize_source("git.example.com/group/tools/cli") == (
            "git.example.com",
            "group/tools/cli",
        )

    def test_bare_owner_repo_is_not_a_hosted_source(self) -> None:
        assert normalize_source("owner/repo") is None

    def test_empty_and_garbage(self) -> None:
        assert normalize_source("") is None
        assert normalize_source("   ") is None
        assert normalize_source("https://github.com/onlyowner") is None


class TestIdentityKey:
    def test_src_key_when_full_provenance(self) -> None:
        provenance = Provenance(host="github.com", repo="a/b", path="skills/x/SKILL.md", confidence=RECORDED)
        assert identity_key(provenance, "/anywhere") == "src:github.com/a/b@skills/x/SKILL.md"

    def test_loc_key_when_path_unknown(self) -> None:
        provenance = Provenance(host="github.com", repo="a/b", confidence=DECLARED)
        key = identity_key(provenance, "/tmp/skill")
        assert key == f"loc:{placement_fingerprint('/tmp/skill')}"

    def test_loc_key_is_stable_for_same_path(self) -> None:
        provenance = Provenance()
        first = identity_key(provenance, "/tmp/skill")
        second = identity_key(provenance, "/tmp/skill")
        assert first == second
        assert first != identity_key(provenance, "/tmp/other")

    def test_round_trip_parse(self) -> None:
        key = "src:github.com/a/b@skills/x/SKILL.md"
        parsed = parse_identity_key(key)
        assert parsed == {"kind": "src", "host": "github.com", "repo": "a/b", "path": "skills/x/SKILL.md"}
        assert parse_identity_key("loc:abc") == {"kind": "loc", "fingerprint": "abc"}

    def test_clean_path(self) -> None:
        assert clean_path("./skills/x/SKILL.md") == "skills/x/SKILL.md"
        assert clean_path("/skills/x/SKILL.md") == "skills/x/SKILL.md"
        assert clean_path("skills\\x\\SKILL.md") == "skills/x/SKILL.md"


class TestInferProvenance:
    def test_lockfile_wins(self, tmp_path: Path) -> None:
        directory = write_skill(tmp_path, "alpha", extra_frontmatter="repository: https://github.com/other/repo\n")
        lock = {"alpha": lock_entry("owner/repo", "skills/alpha/SKILL.md", commit="abc123")}
        provenance = infer_provenance("alpha", str(directory), {"name": "alpha"}, lock)
        assert provenance.confidence == RECORDED
        assert provenance.evidence == "lockfile"
        assert provenance.label == "github.com/owner/repo"
        assert provenance.path == "skills/alpha/SKILL.md"
        assert provenance.ref == "abc123"

    def test_lockfile_matched_by_frontmatter_name(self, tmp_path: Path) -> None:
        directory = write_skill(tmp_path, "dir-name")
        lock = {"renamed-skill": lock_entry("owner/repo", "skills/renamed/SKILL.md")}
        provenance = infer_provenance("dir-name", str(directory), {"name": "renamed-skill"}, lock)
        assert provenance.confidence == RECORDED

    def test_skill_release_file(self, tmp_path: Path) -> None:
        directory = write_skill(tmp_path, "beta")
        (directory / "skill-release.json").write_text(
            '{"skillId": "beta", "name": "beta", "source": {"repository": "https://github.com/acme/beta"}}',
            encoding="utf-8",
        )
        provenance = infer_provenance("beta", str(directory), {"name": "beta"}, {})
        assert provenance.confidence == DECLARED
        assert provenance.evidence == "skill-release.json"
        assert (provenance.host, provenance.repo) == ("github.com", "acme/beta")
        assert provenance.path == ""

    def test_frontmatter_top_level(self, tmp_path: Path) -> None:
        directory = write_skill(tmp_path, "gamma", extra_frontmatter="homepage: https://github.com/acme/gamma\n")
        provenance = infer_provenance("gamma", str(directory), {"homepage": "https://github.com/acme/gamma"}, {})
        assert provenance.confidence == DECLARED
        assert provenance.evidence == "frontmatter"

    def test_frontmatter_metadata_block(self, tmp_path: Path) -> None:
        directory = write_skill(tmp_path, "delta")
        frontmatter = {"metadata": "  repository: https://github.com/acme/delta\n  version: 1.0.0"}
        provenance = infer_provenance("delta", str(directory), frontmatter, {})
        assert provenance.confidence == DECLARED
        assert provenance.repo == "acme/delta"

    def test_nothing_known_stays_unclaimed(self, tmp_path: Path) -> None:
        directory = write_skill(tmp_path, "epsilon")
        provenance = infer_provenance("epsilon", str(directory), {"name": "epsilon"}, {})
        assert provenance.confidence == NONE
        assert provenance.label == ""
        assert provenance.is_known is False


class TestLoadLockfile:
    def test_missing_lockfile(self, fake_home: Path) -> None:
        assert load_lockfile() == {}

    def test_reads_skills_map(self, fake_home: Path) -> None:
        from helpers import write_lockfile

        write_lockfile(fake_home, {"alpha": lock_entry("owner/repo", "skills/alpha/SKILL.md")})
        lock = load_lockfile()
        assert set(lock) == {"alpha"}
        assert lock["alpha"]["skillPath"] == "skills/alpha/SKILL.md"

    def test_ignores_non_dict_entries(self, fake_home: Path) -> None:
        from helpers import write_lockfile

        write_lockfile(fake_home, {"alpha": lock_entry("owner/repo", "skills/alpha/SKILL.md"), "broken": None})  # type: ignore[dict-item]
        assert set(load_lockfile()) == {"alpha"}
