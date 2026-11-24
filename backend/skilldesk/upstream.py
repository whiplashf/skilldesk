"""Check only the GitHub coordinates of an installed skill, at its folder granularity."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

from .config import cache_dir
from .library import read_json, write_json
from .markdown import split_frontmatter
from .scan import read_body

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TTL = 3600


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
    if asset.get("github"):
        source = asset["github"]
        same = (
            prov["host"] == "github.com"
            and prov["repo"].lower() == source["repo"].lower()
            and prov["path"] == source["path"]
        )
        return {**source, "ref": prov["ref"] if same else "", "tree": prov.get("tree", "") if same else ""}
    if prov["host"] == "github.com" and prov["repo"]:
        return {"repo": prov["repo"], "path": prov["path"], "ref": prov["ref"], "tree": prov.get("tree", "")}
    return None


def _cache_path(item: dict, source: dict) -> Path:
    digest = hashlib.sha256(
        json.dumps([item["identity_key"], item["content_hash"], source], sort_keys=True).encode()
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


def evaluate(item: dict, source: dict, get) -> dict:
    """get(endpoint, params) reads this installed repository; a 404 yields None."""
    directory = PurePosixPath(source["path"]).parent
    local_version = installed_version(item)
    result = {
        "checkedAt": int(time.time()),
        "installed": local_version or source["ref"][:9],
        "latest": "",
        "url": "",
    }

    def status(value: str, detail: str) -> dict:
        return {**result, "status": value, "detail": detail}

    def tree_id(ref: str) -> str | None:
        if directory == PurePosixPath("."):
            commit = get("commits/" + quote(ref, safe=""), {})
            return commit["commit"]["tree"]["sha"] if commit else None
        parent = "" if directory.parent == PurePosixPath(".") else "/" + quote(directory.parent.as_posix())
        entries = get("contents" + parent, {"ref": ref})
        return next(
            (e["sha"] for e in entries or [] if e["type"] == "dir" and e["name"] == directory.name), None
        )

    repository = get("", {})
    if not repository:
        raise ValueError("无法访问这个 GitHub 仓库，请核对来源或私有仓库的访问权限")
    # HEAD is immutable for the duration of this comparison.
    head = get("commits/" + quote(repository["default_branch"], safe=""), {})
    head_ref = head["sha"] if head else ""
    if not head_ref or not get("contents/" + quote(source["path"]), {"ref": head_ref}):
        return status("unknown", "上游当前分支中找不到这个 SKILL.md，请核对仓库内路径")
    current = tree_id(head_ref)
    if not current:
        return status("unknown", "GitHub 未返回该目录的指纹")
    installed = source.get("tree") or (tree_id(source["ref"]) if source["ref"] else None)
    releases = get("releases", {"per_page": 100}) or []
    names = {item["name"].lower(), item["dir_name"].lower(), directory.name.lower()} - {""}
    scoped_release = generic_release = None
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release["tag_name"]
        prefix = next(
            (
                n + sep
                for n in sorted(names, key=len, reverse=True)
                for sep in ("@", "/", "-")
                if tag.lower().startswith(n + sep)
            ),
            "",
        )
        if prefix or directory == PurePosixPath("."):
            scoped_release = (release, tag[len(prefix) :])
            break
        if generic_release is None and _version(tag):
            generic_release = (release, tag)

    candidate = scoped_release or generic_release
    if candidate:
        release, tag_version = candidate
        tag = release["tag_name"]
        scoped = scoped_release is not None
        if scoped:
            result.update(latest=tag, url=release.get("html_url", ""))
        if scoped and _version(local_version) and _version(tag_version):
            if _version(tag_version) > _version(local_version):
                return status("release", "这个 skill 已发布较新的正式版本")
            if _version(tag_version) == _version(local_version) and not installed:
                return status("current", "本地声明的版本与最近一次正式发布一致")
        elif installed and source["ref"]:
            released = tree_id(tag)
            if released and released != installed:
                comparison = get("compare/" + quote(source["ref"], safe="") + "..." + quote(tag, safe=""), {})
                if comparison and comparison.get("status") == "ahead":
                    result.update(latest=tag, url=release.get("html_url", ""))
                    return status("release", "发布包含此 skill 目录在安装基线之后的改动")
    if installed == current or (not installed and _local_tree(Path(item["realpath"])) == current):
        return status("current", "与上游当前目录一致" if not installed else "安装基线与上游当前目录一致")
    if installed:
        return status("changed", "该 skill 的上游目录相对安装记录有变化")
    return status("unknown", "本地与上游目录不同，缺少可比较的安装提交或版本")


def check(item: dict, source: dict, force: bool = False) -> dict:
    coordinates(source["repo"], source["path"])
    saved = previous(item, source)
    if saved and not force and time.time() - saved["checkedAt"] < TTL:
        return saved
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "skilldesk"}
    if token := os.environ.get("SKILLDESK_GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + token
    base = "https://api.github.com/repos/" + source["repo"]
    memo = {}
    with httpx.Client(headers=headers, timeout=12) as client:

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

        result = evaluate(item, source, get)
    write_json(_cache_path(item, source), result)
    return result
