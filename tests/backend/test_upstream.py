"""Upstream version check: published editions, scope and installation evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers import write_skill
from skilldesk import baselines, upstream
from skilldesk.config import Config
from skilldesk.scan import scan

REPO = "acme/pack"
HEAD = "a" * 40
PREVIOUS = "b" * 40
PATH = "skills/alpha/SKILL.md"


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


def catalog(tags, trees=None, relation="ahead"):
    trees = {"v2": "new"} if trees is None else trees
    commits = {tag: f"{n:040x}" for n, tag in enumerate(trees, 1)}
    responses = {}
    for tag, tree in trees.items():
        sha = commits[tag]
        responses["git/ref/tags/" + tag] = {"object": {"type": "commit", "sha": sha}}
        entries = [{"path": PATH, "type": "blob"}, {"path": "skills/alpha", "type": "tree", "sha": tree}]
        responses["git/trees/" + sha] = {"sha": "root", "tree": entries if tree else []}
    calls = []
    def get(endpoint, params):
        calls.append(endpoint)
        if endpoint == "releases":
            start = (params["page"] - 1) * params["per_page"]
            return tags[start:start + params["per_page"]]
        if endpoint.startswith("compare/"):
            return {"status": relation}
        return responses[endpoint]
    return get, calls, responses


def evaluate(skill, get, *, tree="old", ref=HEAD):
    return upstream.evaluate(skill, {"repo": REPO, "path": PATH, "tree": tree, "ref": ref}, get, fresh=True)


@pytest.mark.parametrize("releases", [[], [{"tag_name": "v3", "draft": True}, {"tag_name": "v2", "prerelease": True}],
                                      [{"tag_name": "beta@2.0"}, {"tag_name": "beta-v3.1"}]])
def test_only_relevant_stable_releases_are_consulted(skill, releases):
    get, calls, _ = catalog(releases)
    assert evaluate(skill, get)["status"] == "no_release"
    assert calls == ["releases"]


def test_published_notes_and_annotated_tag_resolve_to_immutable_commit(skill):
    tag = {"tag_name": "alpha/v2", "name": "New workflow", "body": "First line\nSecond line",
           "published_at": "2026-04-05T10:20:00Z", "target_commitish": "main"}
    get, calls, responses = catalog([tag], {"alpha/v2": "new"})
    commit = responses["git/ref/tags/alpha/v2"]["object"]
    responses["git/ref/tags/alpha/v2"] = {"object": {"type": "tag", "sha": PREVIOUS}}
    responses["git/tags/" + PREVIOUS] = {"object": commit}
    result = evaluate(skill, get)
    assert result["status"] == "release"
    assert result["release"] == {"tag": "alpha/v2", "title": "New workflow", "body": tag["body"],
                                 "publishedAt": tag["published_at"], "commit": commit["sha"], "html": "<p>First line Second line</p>",
                                 "url": "https://github.com/acme/pack/releases/tag/alpha%2Fv2"}
    assert "commits/main" not in calls


@pytest.mark.parametrize(("tree", "relation", "expected"),
                         [("new", "ahead", "current"), ("old", "ahead", "release"), ("old", "behind", "current"),
                          ("old", "identical", "current"), ("old", "diverged", "unknown")])
def test_only_newer_released_skill_content_is_an_update(skill, tree, relation, expected):
    get, _, _ = catalog([{"tag_name": "v2"}], relation=relation)
    result = evaluate(skill, get, tree=tree)
    assert result["status"] == expected and result["release"]["body"] == ""


def test_repository_release_for_a_sibling_does_not_replace_skill_notes(skill):
    tags = [{"tag_name": "v3", "body": "Changes beta"}, {"tag_name": "v2", "body": "Changes alpha"}]
    get, _, _ = catalog(tags, {"v3": "same", "v2": "same", "v1": "old"})
    status = evaluate(skill, get)
    assert (status["status"], status["latest"], status["release"]["body"]) == ("release", "v2", "Changes alpha")


def test_tree_only_receipt_can_match_an_older_release(skill):
    tags = [{"tag_name": "v3"}, {"tag_name": "v2"}]
    get, _, _ = catalog(tags, {"v3": "new", "v2": "old"})
    assert evaluate(skill, get, ref="")["status"] == "release"
    assert evaluate(skill, get, ref="", tree="unknown-install")["status"] == "unknown"


def test_next_page_and_missing_skill_at_release(skill):
    tags = [{"tag_name": "beta@1.0"}] * 100 + [{"tag_name": "v2"}, {"tag_name": "v1"}]
    get, calls, _ = catalog(tags, {"v2": "", "v1": "new"})
    assert evaluate(skill, get)["latest"] == "v1"
    assert calls.count("releases") == 2


def test_unreadable_repo_and_unresolved_tag_are_not_reported_as_current(skill):
    with pytest.raises(ValueError, match="无法读取"):
        evaluate(skill, lambda *args: None)
    get, _, responses = catalog([{"tag_name": "v2"}])
    responses["git/ref/tags/v2"] = None
    with pytest.raises(ValueError, match="发布提交"):
        evaluate(skill, get)


def test_truncated_tree_uses_the_pinned_commit_for_contents(skill):
    get, _, responses = catalog([{"tag_name": "v2"}])
    commit = responses["git/ref/tags/v2"]["object"]["sha"]
    responses["git/trees/" + commit]["truncated"] = True
    def truncated(endpoint, params):
        if endpoint.startswith("contents"):
            assert params == {"ref": commit}
            if endpoint == "contents/" + PATH:
                return {"type": "file"}
            assert endpoint == "contents/skills"
            return [{"name": "alpha", "sha": "old", "type": "dir"}]
        return get(endpoint, params)
    assert evaluate(skill, truncated)["status"] == "current"


class TestHelpers:
    @pytest.mark.parametrize(
        ("tag", "expected"),
        [("v1.2.3", (1, 2, 3, 0)), ("1.2", (1, 2, 0, 0)), ("nightly", None), ("", None)],
    )
    def test_version_parsing(self, tag: str, expected) -> None:
        assert upstream._version(tag) == expected

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
