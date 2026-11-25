"""Upstream version check: baselines, tree comparison and release hints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import write_skill
from skilldesk import baselines, upstream
from skilldesk.config import Config
from skilldesk.scan import scan

REPO = "acme/pack"
BRANCH = "main"
HEAD = "a" * 40
HEAD_DATE = "2026-11-20T10:00:00Z"


@pytest.fixture(autouse=True)
def clear_caches():
    upstream.forget_caches()
    yield
    upstream.forget_caches()


@pytest.fixture
def skill(fake_home: Path) -> dict:
    """A real installed skill directory plus the index item describing it."""
    directory = write_skill(fake_home / ".agents" / "skills", "alpha", description="alpha skill")
    result = scan(Config())
    item = next(record for record in result.skills if record.dir_name == "alpha")
    return {
        "identity_key": item.identity_key,
        "name": item.name,
        "dir_name": item.dir_name,
        "content_hash": item.content_hash,
        "realpath": str(directory),
        "_path": directory,
    }


class Recorder:
    """Stands in for the GitHub `get(endpoint, params)` closure."""

    def __init__(
        self,
        *,
        trees: dict[str, str] | None = None,
        blobs: set[str] | None = None,
        releases: list | None = None,
        truncated: bool = False,
        head_date: str = HEAD_DATE,
        ref_trees: dict[str, dict[str, str]] | None = None,
        contents: dict[str, list] | None = None,
    ) -> None:
        self.trees = trees or {}
        self.blobs = blobs if blobs is not None else {"skills/alpha/SKILL.md"}
        self.releases = releases or []
        self.truncated = truncated
        self.head_date = head_date
        self.ref_trees = ref_trees or {}
        self.contents = contents or {}
        self.calls: list[tuple[str, tuple]] = []

    def __call__(self, endpoint: str, params: dict):
        self.calls.append((endpoint, tuple(sorted(params.items()))))
        if endpoint == "":
            return {"default_branch": BRANCH, "full_name": REPO}
        if endpoint.startswith("commits/"):
            return {"sha": HEAD, "commit": {"tree": {"sha": "root" + HEAD[4:]}, "committer": {"date": self.head_date}}}
        if endpoint.startswith("git/trees/"):
            ref = endpoint.split("/", 2)[2]
            if ref == HEAD:
                entries = [{"path": path, "type": "tree", "sha": sha} for path, sha in self.trees.items()]
                entries += [{"path": path, "type": "blob", "sha": "b" * 40} for path in sorted(self.blobs)]
                return {"tree": entries, "truncated": self.truncated}
            if ref in self.ref_trees:
                return {
                    "tree": [{"path": p, "type": "tree", "sha": s} for p, s in self.ref_trees[ref].items()],
                    "truncated": False,
                }
            return None
        if endpoint == "releases":
            return self.releases
        if endpoint.endswith("SKILL.md"):
            return {"type": "file", "name": "SKILL.md"}
        if endpoint.startswith("contents"):
            return self.contents.get(endpoint)
        return None

    def endpoints(self) -> list[str]:
        return [endpoint for endpoint, _ in self.calls]


def source_for(skill: dict, **overrides) -> dict:
    source = {"repo": REPO, "path": "skills/alpha/SKILL.md", "ref": "", "tree": "", "installedAt": ""}
    source.update(overrides)
    coordinates = upstream.coordinates(source["repo"], source["path"])
    return {**coordinates, **{k: v for k, v in source.items() if k not in coordinates}}


class TestTreeComparison:
    def test_recorded_install_tree_matches_head(self, skill: dict) -> None:
        get = Recorder(trees={"skills/alpha": "t" * 40})
        result = upstream.evaluate(skill, source_for(skill, tree="t" * 40), get)
        assert result["status"] == "current"
        assert "基线" in result["detail"]
        assert result["localModified"] is False

    def test_recorded_install_tree_differs(self, skill: dict) -> None:
        get = Recorder(trees={"skills/alpha": "t" * 40}, releases=[])
        result = upstream.evaluate(skill, source_for(skill, tree="s" * 40), get)
        assert result["status"] == "changed"
        assert "相对安装基线" in result["detail"]

    def test_pristine_local_copy_counts_as_current(self, skill: dict) -> None:
        local = upstream._local_tree(skill["_path"])
        get = Recorder(trees={"skills/alpha": local})
        result = upstream.evaluate(skill, source_for(skill), get)
        assert result["status"] == "current"
        assert "本地目录与上游" in result["detail"]

    def test_first_check_records_a_baseline(self, skill: dict) -> None:
        get = Recorder(trees={"skills/alpha": "t" * 40})
        result = upstream.evaluate(skill, source_for(skill), get)
        assert result["status"] == "baseline"
        assert result["baseline"] is False
        stored = baselines.get(skill["identity_key"], REPO, "skills/alpha")
        assert stored is not None
        assert stored["dirTree"] == "t" * 40
        assert stored["localTree"] == upstream._local_tree(skill["_path"])

    def test_second_check_uses_the_recorded_baseline(self, skill: dict) -> None:
        first = Recorder(trees={"skills/alpha": "t" * 40})
        assert upstream.evaluate(skill, source_for(skill), first)["status"] == "baseline"

        same = upstream.evaluate(skill, source_for(skill), Recorder(trees={"skills/alpha": "t" * 40}))
        assert same["status"] == "baseline"
        assert same["baseline"] is True

        upstream.forget_caches()
        moved = upstream.evaluate(skill, source_for(skill), Recorder(trees={"skills/alpha": "u" * 40}))
        assert moved["status"] == "changed"

    def test_pinned_install_ref_is_compared(self, skill: dict) -> None:
        get = Recorder(
            trees={"skills/alpha": "t" * 40},
            ref_trees={"c" * 40: {"skills/alpha": "t" * 40}},
        )
        result = upstream.evaluate(skill, source_for(skill, ref="c" * 40), get)
        assert result["status"] == "current"

    def test_old_pinned_install_remains_outdated_after_check_and_restart(self, skill: dict) -> None:
        ref = "c" * 40
        get = Recorder(trees={"skills/alpha": "d" * 40}, ref_trees={ref: {"skills/alpha": "b" * 40}})
        source = source_for(skill, ref=ref)
        assert upstream.evaluate(skill, source, get)["status"] == "changed"
        upstream.forget_caches()
        assert upstream.evaluate(skill, source, get, fresh=True)["status"] == "changed"
        record = baselines.get(skill["identity_key"], REPO, "skills/alpha")
        assert record["installedTree"] == "b" * 40 and record["dirTree"] == "d" * 40

    def test_missing_skill_md_upstream(self, skill: dict) -> None:
        get = Recorder(trees={"skills/alpha": "t" * 40}, blobs={"skills/other/SKILL.md"})
        result = upstream.evaluate(skill, source_for(skill), get)
        assert result["status"] == "unknown"
        assert "找不到这个 SKILL.md" in result["detail"]

    def test_unreadable_repository(self, skill: dict) -> None:
        def get_missing(endpoint: str, params: dict):
            return None

        with pytest.raises(ValueError, match="无法访问"):
            upstream.evaluate(skill, source_for(skill), get_missing)


class TestBaselineDetails:
    def test_local_edit_is_reported(self, skill: dict) -> None:
        upstream.evaluate(skill, source_for(skill), Recorder(trees={"skills/alpha": "t" * 40}))
        (skill["_path"] / "SKILL.md").write_text("---\nname: alpha\n---\n\n# Edited\n", encoding="utf-8")
        result = upstream.evaluate(skill, source_for(skill), Recorder(trees={"skills/alpha": "t" * 40}))
        assert result["localModified"] is True
        assert "本地副本自记录后被改动" in result["detail"]

    def test_baseline_is_ignored_when_the_folder_moves(self, skill: dict) -> None:
        upstream.evaluate(skill, source_for(skill), Recorder(trees={"skills/alpha": "t" * 40}))
        moved = source_for(skill, path="skills/renamed/SKILL.md")
        upstream.forget_caches()
        result = upstream.evaluate(
            skill, moved, Recorder(trees={"skills/renamed": "v" * 40}, blobs={"skills/renamed/SKILL.md"})
        )
        assert result["status"] == "baseline"
        assert baselines.get(skill["identity_key"], REPO, "skills/renamed") is not None

    def test_install_time_after_head_commit_is_current(self, skill: dict) -> None:
        get = Recorder(trees={"skills/alpha": "t" * 40}, head_date="2026-11-01T00:00:00Z")
        result = upstream.evaluate(skill, source_for(skill, installedAt="2026-11-20T00:00:00Z"), get)
        assert result["status"] == "current"
        assert "安装后该仓库没有新提交" in result["detail"]


class TestReleases:
    def test_newer_scoped_release_wins(self, skill: dict) -> None:
        releases = [
            {"tag_name": "alpha@1.2.0", "html_url": "https://example/1.2.0", "draft": False, "prerelease": False},
            {"tag_name": "alpha@1.0.0", "html_url": "https://example/1.0.0", "draft": False, "prerelease": False},
        ]
        get = Recorder(trees={"skills/alpha": "t" * 40}, releases=releases)
        item = dict(skill)
        item["_path"] = skill["_path"]
        result = upstream.evaluate(item, source_for(skill, tree="s" * 40), get)
        assert result["status"] in {"release", "changed"}

    def test_release_matches_installed_version(self, skill: dict) -> None:
        (skill["_path"] / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: x\nversion: 1.2.0\n---\n\n# Alpha\n", encoding="utf-8"
        )
        assert upstream.installed_version(skill) == "1.2.0"
        releases = [{"tag_name": "alpha@1.2.0", "html_url": "https://example/1.2.0"}]
        get = Recorder(trees={"skills/alpha": "t" * 40}, releases=releases)
        result = upstream.evaluate(skill, source_for(skill), get)
        assert result["status"] == "current"
        assert result["detail"] == "本地声明的版本与最近一次正式发布一致"


class TestRepositoryCache:
    def test_forced_check_bypasses_the_repository_cache(self, skill: dict) -> None:
        upstream.evaluate(skill, source_for(skill), Recorder(trees={"skills/alpha": "t" * 40}))
        fresh = Recorder(trees={"skills/alpha": "u" * 40})
        result = upstream.evaluate(skill, source_for(skill), fresh, fresh=True)
        assert result["status"] == "changed", "the fresh tree must win over the cached one"
        assert fresh.calls, "a forced check must ask GitHub again"

    def test_repository_view_is_fetched_once_per_process(self, skill: dict) -> None:
        first = Recorder(trees={"skills/alpha": "t" * 40})
        upstream.evaluate(skill, source_for(skill), first)
        second = Recorder(trees={"skills/alpha": "t" * 40})
        upstream.evaluate(skill, source_for(skill), second)
        assert second.calls == [], "second evaluation should hit the in-process cache"

    def test_truncated_tree_falls_back_to_contents(self, skill: dict) -> None:
        get = Recorder(
            truncated=True,
            trees={},
            contents={"contents/skills": [{"type": "dir", "name": "alpha", "sha": "t" * 40}]},
        )
        result = upstream.evaluate(skill, source_for(skill, tree="t" * 40), get)
        assert result["status"] == "current"
        assert any(endpoint.startswith("contents") for endpoint in get.endpoints())


class TestHelpers:
    @pytest.mark.parametrize(
        ("tag", "expected"),
        [("v1.2.3", (1, 2, 3, 0)), ("1.2", (1, 2, 0, 0)), ("nightly", None), ("", None)],
    )
    def test_version_parsing(self, tag: str, expected) -> None:
        assert upstream._version(tag) == expected

    def test_timestamp_parsing(self) -> None:
        assert upstream._timestamp("2026-11-20T10:00:00Z") is not None
        assert upstream._timestamp("") is None
        assert upstream._timestamp("not a date") is None

    def test_coordinates_validation(self) -> None:
        assert upstream.coordinates("acme/pack", "skills/alpha/SKILL.md") == {
            "repo": "acme/pack",
            "path": "skills/alpha/SKILL.md",
        }
        for repo, path in (("acme", "skills/alpha/SKILL.md"), ("acme/pack", "skills/alpha/README.md"), ("acme/pack", "../x/SKILL.md")):
            with pytest.raises(ValueError):
                upstream.coordinates(repo, path)

    def test_source_for_prefers_a_confirmed_claim(self, skill: dict) -> None:
        item = {"identity_key": "loc:x", "provenance": {"host": "", "repo": "", "path": "", "ref": "", "tree": ""}}
        asset = {"github": {"repo": REPO, "path": "skills/alpha/SKILL.md"}}
        source = upstream.source_for(item, asset)
        assert source == {"repo": REPO, "path": "skills/alpha/SKILL.md", "ref": "", "tree": "", "installedAt": ""}
        assert upstream.source_for(item, {}) is None


class TestBaselineStorage:
    def test_record_and_forget(self, fake_home: Path) -> None:
        entry = baselines.record("src:a/b@c", repo="a/b", dir_path="d", dir_tree="t", head_ref="h", local_tree="l")
        assert entry["dirTree"] == "t"
        assert baselines.get("src:a/b@c", "a/b", "d")["localTree"] == "l"
        assert baselines.get("src:a/b@c", "a/b", "other") is None
        assert baselines.forget("src:a/b@c") is True
        assert baselines.get("src:a/b@c", "a/b", "d") is None

    def test_storage_survives_an_index_rebuild(self, fake_home: Path) -> None:
        baselines.record("src:a/b@c", repo="a/b", dir_path="d", dir_tree="t", head_ref="h", local_tree="l")
        payload = json.loads(baselines.baseline_path().read_text(encoding="utf-8"))
        assert payload["entries"]["src:a/b@c"]["headRef"] == "h"


class TestQuota:
    def test_preflight_raises_when_the_quota_is_spent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Client:
            calls = 0

            def get(self, url: str):
                Client.calls += 1
                assert url.endswith("/rate_limit")

                class Response:
                    def raise_for_status(self) -> None:
                        return None

                    def json(self) -> dict:
                        return {"rate": {"remaining": 1, "reset": 1795568800}}

                return Response()

        upstream._RATE_STATE.update(checked=0.0, remaining=-1.0, reset=0.0)
        monkeypatch.delenv("SKILLDESK_GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(upstream, "_gh_token", lambda: "")
        with pytest.raises(upstream.QuotaExhausted) as raised:
            upstream._preflight(Client())
        assert raised.value.reset == 1795568800
        assert Client.calls == 1

    def test_preflight_is_skipped_with_a_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Client:
            def get(self, url: str):  # pragma: no cover - must not be called
                raise AssertionError("no preflight with a token")

        monkeypatch.setenv("SKILLDESK_GITHUB_TOKEN", "t")
        upstream._preflight(Client())

    def test_preflight_result_is_cached_for_a_minute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Client:
            calls = 0

            def get(self, url: str):
                Client.calls += 1

                class Response:
                    def raise_for_status(self) -> None:
                        return None

                    def json(self) -> dict:
                        return {"rate": {"remaining": 55, "reset": 0}}

                return Response()

        monkeypatch.delenv("SKILLDESK_GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(upstream, "_gh_token", lambda: "")
        upstream._RATE_STATE.update(checked=0.0, remaining=-1.0, reset=0.0)
        upstream._preflight(Client())
        upstream._preflight(Client())
        assert Client.calls == 1


class FakeHTTP:
    """Minimal stand-in for httpx.Client used by quota()."""

    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.headers: dict = {}

    def __enter__(self) -> FakeHTTP:  # noqa: PYI034 - py3.10 has no typing.Self
        return self

    def __exit__(self, *exc) -> None:
        return None

    def get(self, url: str):
        assert "rate_limit" in url

        class Response:
            status_code = self.status

            def raise_for_status(inner) -> None:
                import httpx

                if self.status >= 400:
                    raise httpx.HTTPStatusError("nope", request=None, response=None)  # type: ignore[arg-type]

            def json(inner) -> dict:
                return self.payload

        return Response()


class TestGithubCredential:
    def test_env_token_wins(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKILLDESK_GITHUB_TOKEN", "env-token")
        assert upstream.github_token() == ("env-token", "env")
        assert upstream.github_headers()["Authorization"] == "Bearer env-token"

    def test_config_file_is_used_without_env(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKILLDESK_GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(upstream, "_gh_token", lambda: "")
        (fake_home / ".config" / "skilldesk").mkdir(parents=True, exist_ok=True)
        (fake_home / ".config" / "skilldesk" / "upstream.json").write_text(
            json.dumps({"githubToken": "file-token"}), encoding="utf-8"
        )
        assert upstream.github_token() == ("file-token", "config")

    def test_gh_cli_is_the_last_resort(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKILLDESK_GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(upstream, "_gh_token", lambda: "gh-token")
        assert upstream.github_token() == ("gh-token", "gh")

    def test_anonymous_when_nothing_is_configured(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKILLDESK_GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(upstream, "_gh_token", lambda: "")
        assert upstream.github_token() == ("", "")
        assert "Authorization" not in upstream.github_headers()

    def test_preflight_is_skipped_with_any_token(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKILLDESK_GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(upstream, "_gh_token", lambda: "gh-token")

        class Client:
            def get(self, url: str):  # pragma: no cover - must not run
                raise AssertionError("preflight must not run with a token")

        upstream._preflight(Client())


class TestQuotaReporting:
    def test_quota_reports_a_token_budget(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKILLDESK_GITHUB_TOKEN", "t")
        monkeypatch.setattr(upstream, "http_client", lambda **kw: FakeHTTP({"rate": {"limit": 5000, "remaining": 4999, "reset": 1795572222}}))
        result = upstream.quota()
        assert (result["available"], result["mode"], result["source"]) == (True, "token", "env")
        assert result["limit"] == 5000 and result["remaining"] == 4999

    def test_quota_reports_anonymous_mode(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SKILLDESK_GITHUB_TOKEN", raising=False)
        monkeypatch.setattr(upstream, "_gh_token", lambda: "")
        monkeypatch.setattr(upstream, "http_client", lambda **kw: FakeHTTP({"rate": {"limit": 60, "remaining": 0, "reset": 1795572222}}))
        result = upstream.quota()
        assert result["mode"] == "anonymous" and result["remaining"] == 0

    def test_quota_survives_a_network_error(self, fake_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SKILLDESK_GITHUB_TOKEN", "t")
        monkeypatch.setattr(upstream, "http_client", lambda **kw: FakeHTTP({}, status=500))
        result = upstream.quota()
        assert result["available"] is False and result["detail"]


def test_reinstall_uses_the_new_install_fingerprint(skill):
    upstream.evaluate(skill, source_for(skill), Recorder(trees={"skills/alpha": "t" * 40}))
    (skill["_path"] / "SKILL.md").write_text("A newly installed version.")
    tree = upstream._local_tree(skill["_path"])
    result = upstream.evaluate(skill, source_for(skill, tree=tree), Recorder(trees={"skills/alpha": tree}), fresh=True)
    assert result["status"] == "current" and not result["localModified"]


def test_truncated_tree_falls_back_for_pinned_head():
    def get(path, params):
        assert path == "contents/skills" and params == {"ref": HEAD}
        return [{"name": "alpha", "type": "dir", "sha": "folder-tree"}]

    assert upstream._dir_sha_at(HEAD, "skills/alpha", get, {"head": HEAD, "repo": REPO}) == "folder-tree"
