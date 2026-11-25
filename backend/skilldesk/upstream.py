"""Check the GitHub coordinates of an installed skill, at its folder granularity.

Two different questions are answered here:

* **Has the upstream moved?** — by comparing the git tree SHA of the skill folder
  at HEAD with a recorded install baseline (see :mod:`skilldesk.baselines`).
* **Was the installed copy edited?** — by comparing the installed folder's own
  git tree SHA with the one recorded next to the baseline.

Nothing is guessed: when no comparable record exists yet the first check records
one and says so instead of inventing "up to date". Repository-level responses are
cached per process so checking a page of 50 skills costs a handful of API calls
instead of hundreds (anonymous GitHub quota is 60 requests per hour).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

from . import baselines
from .config import cache_dir, config_dir
from .library import read_json, write_json
from .markdown import split_frontmatter
from .net import http_client
from .scan import read_body

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TTL = 3600
REPO_TTL = 900
RELEASE_TTL = 3600
MAX_TREE_ENTRIES = 60_000

def _optional(get, endpoint: str, params: dict):
    """Fetch something whose absence is survivable: a tree listing is an optimisation."""
    try:
        return get(endpoint, params)
    except Exception:  # noqa: BLE001 - a failing optimisation must never fail the check
        return None


_GH_TOKEN: str | None = None


def _gh_token() -> str:
    """Reuse the token of a logged-in ``gh`` CLI, the most common local setup."""
    global _GH_TOKEN
    if _GH_TOKEN is not None:
        return _GH_TOKEN
    try:
        completed = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=5, check=False
        )
        _GH_TOKEN = completed.stdout.strip() if completed.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        _GH_TOKEN = ""
    return _GH_TOKEN


def github_token() -> tuple[str, str]:
    """``(token, source)``; anonymous access returns ``("", "")``."""
    value = os.environ.get("SKILLDESK_GITHUB_TOKEN", "").strip()
    if value:
        return value, "env"
    config = read_json(config_dir() / "upstream.json", {})
    if isinstance(config, dict):
        value = str(config.get("githubToken") or "").strip()
        if value:
            return value, "config"
    value = _gh_token()
    return (value, "gh") if value else ("", "")


def github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "skilldesk"}
    token, _source = github_token()
    if token:
        headers["Authorization"] = "Bearer " + token
    return headers


def quota() -> dict:
    """How much GitHub API budget the current credential has left."""
    token, source = github_token()
    mode = "token" if token else "anonymous"
    try:
        with http_client(headers=github_headers(), timeout=10, url_hint="https://api.github.com/rate_limit") as client:
            response = client.get("https://api.github.com/rate_limit")
            response.raise_for_status()
            rate = response.json().get("rate", {})
    except (httpx.HTTPError, ValueError, LookupError) as error:
        return {"available": False, "mode": mode, "source": source, "detail": str(error)[:140]}
    return {
        "available": True,
        "mode": mode,
        "source": source,
        "limit": int(rate.get("limit", 0)),
        "remaining": int(rate.get("remaining", 0)),
        "reset": int(rate.get("reset", 0)),
        "checkedAt": int(time.time()),
    }


class QuotaExhausted(RuntimeError):
    """Anonymous GitHub quota is spent; callers should tell the user when it resets."""

    def __init__(self, reset: int) -> None:
        super().__init__(f"GitHub 检查额度已用完，{reset} 之后恢复")
        self.reset = reset


_RATE_STATE: dict[str, float] = {"checked": 0.0, "remaining": -1.0, "reset": 0.0}

_REPO_CACHE: dict[str, tuple[float, dict]] = {}
_REF_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}
_RELEASE_CACHE: dict[str, tuple[float, list]] = {}


def coordinates(repo: str, path: str) -> dict:
    repo = repo.strip().removeprefix("https://github.com/").removesuffix("/").removesuffix(".git")
    path = path.strip()
    if (
        not REPO.fullmatch(repo)
        or any(s in {".", ".."} for s in repo.split("/"))
        or any(s in {"", ".", ".."} for s in path.split("/"))
        or "\\" in path
        or PurePosixPath(path).name != "SKILL.md"
    ):
        raise ValueError("请填写 GitHub 的 owner/repo 和仓库内完整的 SKILL.md 路径")
    return {"repo": repo, "path": path}


def source_for(item: dict, asset: dict) -> dict | None:
    prov = item["provenance"]
    installed_at = prov.get("installedAt", "")
    if asset.get("github"):
        source = asset["github"]
        same = (
            prov["host"] == "github.com"
            and prov["repo"].lower() == source["repo"].lower()
            and prov["path"] == source["path"]
        )
        return {
            **source,
            "ref": prov["ref"] if same else "",
            "tree": prov.get("tree", "") if same else "",
            "installedAt": installed_at if same else "",
        }
    if prov["host"] == "github.com" and prov["repo"]:
        return {
            "repo": prov["repo"],
            "path": prov["path"],
            "ref": prov["ref"],
            "tree": prov.get("tree", ""),
            "installedAt": installed_at,
        }
    return None


def _cache_path(item: dict, source: dict) -> Path:
    digest = hashlib.sha256(
        json.dumps([2, item["identity_key"], item["content_hash"], source], sort_keys=True).encode()
    ).hexdigest()
    return cache_dir() / "upstream" / (digest + ".json")


def previous(item: dict, source: dict | None) -> dict | None:
    if not source:
        return None
    return read_json(_cache_path(item, source), {}) or None


def _local_tree(directory: Path) -> str:
    """Git tree ID for installed files. A byte/mode difference changes the result."""

    def oid(kind: str, value: bytes) -> bytes:
        return hashlib.sha1(kind.encode() + b" " + str(len(value)).encode() + b"\0" + value).digest()

    def tree(path: Path) -> bytes:
        entries = []
        for child in path.iterdir():
            if child.name == ".git":
                continue
            name = os.fsencode(child.name)
            if child.is_symlink():
                mode, digest = b"120000", oid("blob", os.fsencode(os.readlink(child)))
            elif child.is_dir():
                mode, digest = b"40000", tree(child)
            elif child.is_file():
                mode = b"100755" if child.stat().st_mode & 0o111 else b"100644"
                digestor = hashlib.sha1(b"blob " + str(child.stat().st_size).encode() + b"\0")
                with child.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digestor.update(chunk)
                digest = digestor.digest()
            else:
                continue
            entries.append((name + (b"/" if mode == b"40000" else b""), mode + b" " + name + b"\0" + digest))
        return oid("tree", b"".join(value for _, value in sorted(entries)))

    return tree(directory).hex()


def _version(tag: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+(?:\.\d+){1,3})", tag or "", re.IGNORECASE)
    if not match:
        return None
    parts = tuple(map(int, match[1].split(".")))
    return parts + (0,) * (4 - len(parts))


def _timestamp(value: str) -> float | None:
    text = (value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def installed_version(item: dict) -> str:
    directory = Path(item["realpath"])
    try:
        release = read_json(directory / "skill-release.json", {})
    except (ValueError, OSError):
        release = {}
    body = read_body(str(directory)) or ""
    fm, _ = split_frontmatter(body)
    nested = re.search(r"(?m)^\s*version\s*:\s*['\"]?([^\s'\"]+)", str(fm.get("metadata", "")))
    return str(fm.get("version") or release.get("version") or (nested[1] if nested else ""))


def repo_view(repo: str, get, *, fresh: bool = False) -> dict:
    """Head commit plus the folder tree map of a repository, cached per process.

    ``fresh`` bypasses the cache: a forced check must see the upstream as it is
    now, not as it was when a page was opened 10 minutes ago.
    """
    cached = None if fresh else _REPO_CACHE.get(repo.lower())
    if cached and time.time() - cached[0] < REPO_TTL:
        return cached[1]
    repository = get("", {})
    if not repository:
        raise ValueError("无法访问这个 GitHub 仓库，请核对来源或私有仓库的访问权限")
    branch = repository.get("default_branch") or "main"
    head = get("commits/" + quote(branch, safe=""), {}) or {}
    head_ref = str(head.get("sha") or "")
    trees: dict[str, str] = {}
    blobs: set[str] = set()
    truncated = False
    root_tree = str(((head.get("commit") or {}).get("tree") or {}).get("sha") or "")
    payload = _optional(get, "git/trees/" + head_ref, {"recursive": "1"}) if head_ref else None
    if payload:
        entries = payload.get("tree") or []
        truncated = bool(payload.get("truncated")) or len(entries) > MAX_TREE_ENTRIES
        if not truncated:
            for entry in entries:
                path = str(entry.get("path") or "")
                if not path:
                    continue
                if entry.get("type") == "tree":
                    trees[path] = str(entry.get("sha") or "")
                elif entry.get("type") == "blob":
                    blobs.add(path)
    view = {
        "repo": repo,
        "branch": branch,
        "head": head_ref,
        "headDate": str(((head.get("commit") or {}).get("committer") or {}).get("date") or ""),
        "rootTree": root_tree,
        "trees": trees,
        "blobs": blobs,
        "truncated": truncated,
        "complete": bool(payload) and not truncated,
    }
    _REPO_CACHE[repo.lower()] = (time.time(), view)
    return view


def _tree_at(repo: str, ref: str, get) -> dict | None:
    """Folder tree map at an arbitrary ref (used for a pinned install commit)."""
    key = (repo.lower(), ref)
    cached = _REF_CACHE.get(key)
    if cached and time.time() - cached[0] < TTL:
        return cached[1]
    payload = _optional(get, "git/trees/" + ref, {"recursive": "1"})
    if not payload or payload.get("truncated"):
        return None
    trees = {
        str(entry["path"]): str(entry.get("sha") or "")
        for entry in payload.get("tree") or []
        if entry.get("type") == "tree" and entry.get("path")
    }
    trees[""] = str(payload.get("sha") or "")
    _REF_CACHE[key] = (time.time(), trees)
    return trees


def _dir_tree(view: dict, dir_path: str) -> str:
    if not dir_path:
        return view.get("rootTree", "")
    return view.get("trees", {}).get(dir_path, "")


def _dir_sha_at(ref: str, dir_path: str, get, view: dict) -> str:
    """Directory tree SHA at an arbitrary ref, falling back to a contents listing."""
    if ref == view["head"] and (current := _dir_tree(view, dir_path)):
        return current
    pinned = _tree_at(view["repo"], ref, get) if ref != view["head"] else {}
    if pinned and pinned.get(dir_path):
        return pinned[dir_path]
    if not dir_path:
        commit = get("commits/" + quote(ref, safe=""), {}) or {}
        return str(((commit.get("commit") or {}).get("tree") or {}).get("sha") or "")
    return _contents_dir_sha(view["repo"], dir_path, ref, get)


def _contents_dir_sha(repo: str, dir_path: str, ref: str, get) -> str:
    """Fallback for repositories whose recursive tree listing is truncated."""
    directory = PurePosixPath(dir_path)
    parent = "" if directory.parent == PurePosixPath(".") else "/" + quote(directory.parent.as_posix())
    entries = get("contents" + parent, {"ref": ref})
    if not entries:
        return ""
    return next((str(e["sha"]) for e in entries if e.get("type") == "dir" and e.get("name") == directory.name), "")


def _releases(repo: str, get, *, fresh: bool = False) -> list:
    cached = None if fresh else _RELEASE_CACHE.get(repo.lower())
    if cached and time.time() - cached[0] < RELEASE_TTL:
        return cached[1]
    releases = get("releases", {"per_page": 100}) or []
    _RELEASE_CACHE[repo.lower()] = (time.time(), releases)
    return releases


def _scoped_release(item: dict, directory: PurePosixPath, releases: list) -> tuple[dict, str] | tuple[None, str] | None:
    """The release that belongs to this folder, and its version part."""
    names = {item.get("name", "").lower(), item.get("dir_name", "").lower(), directory.name.lower()} - {""}
    root = directory == PurePosixPath(".")
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name") or "")
        prefix = next(
            (
                name + separator
                for name in sorted(names, key=len, reverse=True)
                for separator in ("@", "/", "-")
                if tag.lower().startswith(name + separator)
            ),
            "",
        )
        if prefix or root:
            return release, tag[len(prefix) :]
    return None


def _release_verdict(
    item: dict,
    directory: PurePosixPath,
    dir_path: str,
    releases: list,
    local_version: str,
    installed_tree: str,
    source: dict,
    get,
    view: dict,
    result: dict,
) -> dict | None:
    """A release-based answer, when the tags say something the trees cannot."""
    scoped = _scoped_release(item, directory, releases)
    if scoped:
        release, tag_version = scoped
        tag = str(release.get("tag_name") or "")
        result.update(latest=tag, url=release.get("html_url", ""))
        if _version(tag_version) and _version(local_version):
            if _version(tag_version) > _version(local_version):
                return {**result, "status": "release", "detail": "这个 skill 已发布较新的正式版本"}
            if _version(tag_version) == _version(local_version) and not installed_tree:
                return {**result, "status": "current", "detail": "本地声明的版本与最近一次正式发布一致"}
        return None
    generic = next(
        (
            release
            for release in releases
            if not release.get("draft") and not release.get("prerelease") and _version(str(release.get("tag_name") or ""))
        ),
        None,
    )
    if not generic or not installed_tree or not source.get("ref"):
        return None
    tag = str(generic.get("tag_name") or "")
    released_tree = _dir_sha_at(tag, dir_path, get, view)
    if not released_tree or released_tree == installed_tree:
        return None
    comparison = get("compare/" + quote(source["ref"], safe="") + "..." + quote(tag, safe=""), {})
    if comparison and comparison.get("status") == "ahead":
        result.update(latest=tag, url=generic.get("html_url", ""))
        return {**result, "status": "release", "detail": "发布包含此 skill 目录在安装基线之后的改动"}
    return None


def evaluate(item: dict, source: dict, get, *, fresh: bool = False) -> dict:
    """get(endpoint, params) reads this installed repository; a 404 yields None."""
    directory = PurePosixPath(source["path"]).parent
    dir_path = "" if directory == PurePosixPath(".") else directory.as_posix()
    view = repo_view(source["repo"], get, fresh=fresh)
    local_version = installed_version(item)
    result = {
        "checkedAt": int(time.time()),
        "installed": local_version or source.get("ref", "")[:9],
        "latest": "",
        "url": "",
    }

    if view.get("complete"):
        upstream_has_path = source["path"] in view["blobs"]
    else:
        upstream_has_path = bool(get("contents/" + quote(source["path"], safe="/"), {"ref": view["head"]}))
    if not upstream_has_path:
        return {**result, "status": "unknown", "detail": "上游当前分支中找不到这个 SKILL.md，请核对仓库内路径"}

    current = _dir_tree(view, dir_path)
    if not current:
        current = _contents_dir_sha(source["repo"], dir_path, view["head"], get)
    if not current:
        return {**result, "status": "unknown", "detail": "GitHub 未返回该目录的指纹"}

    local_tree = _local_tree(Path(item["realpath"]))
    identity_key = str(item.get("identity_key") or "")
    baseline = baselines.get(identity_key, source["repo"], dir_path) if identity_key else None
    installed_tree = source.get("tree", "")
    if not installed_tree and source.get("ref"):
        installed_tree = _dir_sha_at(source["ref"], dir_path, get, view)
    if not installed_tree and not source.get("ref"):
        installed_tree = (baseline or {}).get("installedTree", "")
    edited = bool(baseline and baseline.get("localTree") and baseline["localTree"] != local_tree
                  and local_tree != installed_tree)
    note = "；本地副本自记录后被改动" if edited else ""

    def settle(value: str, detail: str) -> dict:
        if baseline is None and identity_key:
            baselines.record(
                item["identity_key"],
                repo=source["repo"],
                dir_path=dir_path,
                dir_tree=current,
                head_ref=view["head"],
                local_tree=local_tree,
                installed_tree=installed_tree or (current if local_tree == current else ""),
            )
        return {
            **result,
            "status": value,
            "detail": detail + note,
            "baseline": baseline is not None,
            "localModified": edited,
        }

    if installed_tree and installed_tree == current:
        return settle("current", "安装基线记录的目录与上游当前目录一致")
    if not installed_tree and local_tree == current:
        return settle("current", "本地目录与上游当前目录一致")

    releases = _releases(source["repo"], get, fresh=fresh)
    verdict = _release_verdict(
        item, directory, dir_path, releases, local_version, installed_tree, source, get, view, result
    )
    if verdict:
        return settle(verdict["status"], verdict["detail"])
    if installed_tree:
        return settle("changed", "该 skill 的上游目录相对安装基线有变化")

    # No comparable record yet: take the cheapest honest signal, then record one.
    installed_at = _timestamp(source.get("installedAt", ""))
    head_time = _timestamp(view.get("headDate", ""))
    if installed_at and head_time and head_time <= installed_at:
        return settle("current", "安装后该仓库没有新提交")
    if baseline and baseline["dirTree"] != current:
        return settle("changed", "上游目录自首次检查后发生变化")
    return settle("baseline", "已记录上游指纹，尚缺少可核对的安装版本")


def _preflight(client) -> None:
    """Refuse early when the quota is spent (``/rate_limit`` itself is free)."""
    if github_token()[0]:
        return
    now = time.time()
    if _RATE_STATE["remaining"] >= 0 and now - _RATE_STATE["checked"] < 60:
        remaining, reset = int(_RATE_STATE["remaining"]), int(_RATE_STATE["reset"])
    else:
        response = client.get("https://api.github.com/rate_limit")
        response.raise_for_status()
        rate = response.json().get("rate", {})
        remaining, reset = int(rate.get("remaining", -1)), int(rate.get("reset", 0))
        _RATE_STATE.update(checked=now, remaining=float(remaining), reset=float(reset))
    if 0 <= remaining <= 2:
        raise QuotaExhausted(reset)


def check(item: dict, source: dict, force: bool = False) -> dict:
    coordinates(source["repo"], source["path"])
    saved = previous(item, source)
    if saved and not force and time.time() - saved["checkedAt"] < TTL:
        return saved
    headers = github_headers()
    base = "https://api.github.com/repos/" + source["repo"]
    memo: dict = {}
    with http_client(headers=headers, timeout=20, url_hint=base) as client:
        _preflight(client)

        def get(endpoint, params):
            key = (endpoint, tuple(params.items()))
            if key not in memo:
                response = client.get(base + ("/" + endpoint if endpoint else ""), params=params)
                if response.status_code == 404:
                    memo[key] = None
                else:
                    response.raise_for_status()
                    memo[key] = response.json()
            return memo[key]

        # Only the per-skill result cache is bypassed here: the repository view
        # stays cached so checking a page of 50 skills costs a few requests.
        result = evaluate(item, source, get)
    write_json(_cache_path(item, source), result)
    return result


def forget_caches() -> None:
    """Drop in-process caches (used by tests and after a manual rescan)."""
    _REPO_CACHE.clear()
    _REF_CACHE.clear()
    _RELEASE_CACHE.clear()
