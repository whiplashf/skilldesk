"""Release-only update checks for installed GitHub skills."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

from .config import cache_dir, config_dir
from .library import read_json, write_json
from .markdown import split_frontmatter
from .net import http_client
from .packages import OID
from .scan import read_body

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TTL = 3600
RELEASE_TTL = 3600
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

_RELEASE_CACHE: dict[tuple[str, int], tuple[float, list]] = {}


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
            **({"trackingOnly": True} if not same and prov["host"] and prov["repo"] else {}),
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
        json.dumps([3, item["identity_key"], item["realpath"], item["content_hash"], source], sort_keys=True).encode()
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
    match = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", tag or "", re.IGNORECASE)
    if not match:
        return None
    parts = tuple(map(int, match[1].split(".")))
    return parts + (0,) * (4 - len(parts))


def installed_version(item: dict) -> str:
    directory = Path(item["realpath"])
    try:
        release = read_json(directory / "skill-release.json", {})
    except (ValueError, OSError):
        release = {}
    body = read_body(str(directory)) or ""
    fm, _ = split_frontmatter(body)
    nested = re.search(r"(?m)^\s*version\s*:\s*['\"]?([^\s'\"]+)", str(fm.get("metadata", "")))
    declared = release.get("version") if isinstance(release, dict) else ""
    return str(fm.get("version") or declared or (nested[1] if nested else ""))


def _candidates(item: dict, source: dict, get, fresh: bool):
    """Yield published releases in GitHub order, excluding tags scoped to other skills."""
    names = {str(item.get(key) or "").lower() for key in ("name", "dir_name")}
    names.add(PurePosixPath(source["path"]).parent.name.lower())
    root = source["path"] == "SKILL.md"
    page = 1
    while True:
        key = (source["repo"].lower(), page)
        cached = _RELEASE_CACHE.get(key)
        if not fresh and cached and time.time() - cached[0] < RELEASE_TTL:
            releases = cached[1]
        else:
            releases = get("releases", {"per_page": 100, "page": page})
            if not isinstance(releases, list):
                raise ValueError("无法读取这个 GitHub 仓库的 Release，请核对来源和访问权限")
            _RELEASE_CACHE[key] = (time.time(), releases)
        for release in releases:
            tag = str(release.get("tag_name") or "")
            if not tag or release.get("draft") or release.get("prerelease"):
                continue
            scope = re.fullmatch(r"(.+)[@/](.+)", tag) or re.fullmatch(
                r"([a-z][\w.-]*?)-(v?\d+[.\w+-]*)", tag, re.IGNORECASE
            )
            if scope:
                prefix = scope[1].rsplit("/", 1)[-1].lower()
                if prefix in names:
                    yield release, scope[2]
                    continue
                if prefix not in {"release", "releases", "version", "stable", source["repo"].split("/")[-1].lower()}:
                    continue
            yield release, tag if root else ""
        if len(releases) < 100:
            return
        page += 1


def _tag_commit(tag: str, get) -> str:
    ref = get("git/ref/tags/" + quote(tag, safe="/"), {}) or {}
    obj = ref.get("object") or {}
    seen = set()
    while obj.get("type") == "tag":
        sha = obj.get("sha", "")
        if not OID.fullmatch(sha) or sha in seen:
            return ""
        seen.add(sha)
        obj = (get("git/tags/" + sha, {}) or {}).get("object") or {}
    sha = obj.get("sha", "")
    return sha if obj.get("type") == "commit" and OID.fullmatch(sha) else ""


def _folder(path: str, commit: str, get, snapshot: dict) -> str | None:
    """Return the directory SHA. An empty string means this edition lacks the skill."""
    trees = snapshot.setdefault("trees", {})
    directory = path.rpartition("/")[0]
    if commit not in trees:
        data = get("git/trees/" + commit, {"recursive": "1"})
        if data and not data.get("truncated"):
            entries = {e["path"]: e for e in data["tree"]}
            entries[""] = {"sha": data["sha"]}
            trees[commit] = entries
        else:
            trees[commit] = None
    tree = trees[commit]
    if tree is not None:
        if tree.get(path, {}).get("type") != "blob":
            return ""
        return tree.get(directory, {}).get("sha") or None

    # GitHub truncated the recursive tree. Look up just the document and its parent.
    doc = get("contents/" + quote(path), {"ref": commit})
    if not doc or doc.get("type") != "file":
        return ""
    if not directory:
        return ((get("commits/" + commit, {}) or {}).get("commit", {}).get("tree") or {}).get("sha")
    parent, _, name = directory.rpartition("/")
    listing = get("contents" + ("/" + quote(parent) if parent else ""), {"ref": commit}) or []
    return next((row["sha"] for row in listing if row["type"] == "dir" and row["name"] == name), None)


def _editions(item, source, get, snapshot, fresh):
    for release, version in _candidates(item, source, get, fresh):
        tag = release["tag_name"]
        commit = _tag_commit(tag, get)
        if not commit:
            raise ValueError(f"无法确认正式版 {tag} 的发布提交，请稍后重新检查")
        tree = _folder(source["path"], commit, get, snapshot)
        if tree is None:
            raise ValueError(f"无法核对 {tag} 中的技能目录，请稍后重新检查")
        if tree:
            yield {
                "tag": tag, "title": release.get("name") or "", "body": (release.get("body") or "").strip(),
                "publishedAt": release.get("published_at") or "", "commit": commit,
                "url": "https://github.com/" + source["repo"] + "/releases/tag/" + quote(tag, safe=""),
            }, tree, version


def evaluate(item: dict, source: dict, get, *, fresh: bool = False, snapshot: dict | None = None) -> dict:
    """Compare the installed skill with published, stable Releases, never branch HEAD."""
    snapshot = {} if snapshot is None else snapshot
    ref = source.get("ref") or ""
    result = {"checkedAt": int(time.time()), "installed": ref[:9], "latest": "", "url": ""}
    editions = _editions(item, source, get, snapshot, fresh)
    edition = next(editions, None)
    if not edition:
        return {**result, "status": "no_release", "detail": "上游尚未发布包含此技能的正式 Release。"}
    release, tree, version = edition
    local_version = "" if source.get("trackingOnly") else installed_version(item)
    result["installed"] = local_version or ref[:9]

    def verdict(status: str, detail: str) -> dict:
        return {**result, "latest": release["tag"], "url": release["url"], "release": release,
                "status": status, "detail": detail}

    if ref == release["commit"]:
        result["installed"] = release["tag"]
        return verdict("current", "已安装此正式版。")
    installed_tree = source.get("tree")
    if not installed_tree and OID.fullmatch(ref):
        installed_tree = _folder(source["path"], ref, get, snapshot)
    if not installed_tree and not source.get("trackingOnly"):
        installed_tree = _local_tree(Path(item["realpath"]))
    if installed_tree == tree:
        return verdict("current", "已安装此正式版的技能内容。")

    def compare(base, head):
        return (get("compare/" + base + "..." + head, {"per_page": 1}) or {}).get("status")

    if OID.fullmatch(ref):
        relation = compare(ref, release["commit"])
        if relation in {"behind", "identical"}:
            return verdict("current", "本机已包含此正式版的提交。")
        if relation != "ahead" or not installed_tree:
            return verdict("unknown", "安装提交与发布提交的先后关系无法确认。")
        available = True
    else:
        latest, installed = _version(version), _version(local_version)
        if latest and installed and latest <= installed:
            return verdict("current", "本机声明的技能版本已达到此正式版。")
        available = bool(latest and installed)
    if source.get("trackingOnly"):
        return verdict("unknown", "跟踪来源与此副本的安装来源不同。")

    # For a repository-wide release, show the notes for the edition that actually
    # shipped this folder. Later sibling-only releases may carry identical bytes.
    # Legacy receipts sometimes have only a tree. An older matching release can
    # also prove their place in history without guessing from an installation date.
    if not version or not available:
        same_history = not version
        for older, older_tree, older_version in editions:
            same_history = same_history and older_tree == tree
            if same_history:
                if available and OID.fullmatch(ref) and compare(ref, older["commit"]) != "ahead":
                    break
                release, version = older, older_version
                same_history = not version
            if not available and older_tree == installed_tree:
                available = compare(older["commit"], release["commit"]) == "ahead"
                break
            if available and (version or older_tree != tree):
                break
    if available:
        return verdict("release", "此正式版包含已安装版本之后的技能更新。")
    return verdict("unknown", "已找到正式版，但缺少可核对的安装版本。")


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


def check(item: dict, source: dict, force: bool = False, *, batch: dict | None = None) -> dict:
    coordinates(source["repo"], source["path"])
    saved = previous(item, source)
    if saved and not force and time.time() - saved["checkedAt"] < TTL:
        return saved
    headers = github_headers()
    base = "https://api.github.com/repos/" + source["repo"]
    snapshot = {} if batch is None else batch.setdefault(source["repo"].lower(), {})
    memo = snapshot.setdefault("responses", {})
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

        result = evaluate(item, source, get, fresh=force, snapshot=snapshot)
    write_json(_cache_path(item, source), result)
    return result


def record_applied(item: dict, source: dict, release: dict) -> None:
    """The confirmed, pinned package and its new receipt prove installation even offline."""
    previous_release = (previous(item, source) or {}).get("release")
    if previous_release and previous_release["commit"] != release["commit"]:
        return
    write_json(_cache_path(item, source), {
        "checkedAt": int(time.time()), "installed": release["tag"], "latest": release["tag"],
        "release": release, "url": release["url"], "status": "current", "detail": "已安装此正式版。",
    })


def forget_caches() -> None:
    """Drop in-process caches (used by tests and after a manual rescan)."""
    _RELEASE_CACHE.clear()
