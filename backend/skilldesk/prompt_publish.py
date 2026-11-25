"""Publish one saved prompt on its repository's default branch, in one Git commit."""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastapi import HTTPException

from . import prompt_catalog as catalog

if TYPE_CHECKING:
    from .prompts import Prompt


def git(directory: Path, *args: str, data: bytes | None = None) -> bytes:
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_ASKPASS="/bin/false",
               GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=15", LC_ALL="C")
    try:
        return subprocess.run(["git", "--literal-pathspecs", "-c", "core.hooksPath=/dev/null", *args],
                              cwd=directory, input=data, capture_output=True, check=True, timeout=35, env=env).stdout
    except FileNotFoundError as exc:
        raise HTTPException(503, "运行 Skilldesk 的电脑需要安装 Git。") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "GitHub 响应超时，请稍后重试。") from exc


@dataclass(frozen=True)
class Target:
    name: str
    remote: str


def destination() -> Target:
    try:
        url = git(catalog.PROJECT, "remote", "get-url", "--push", "origin").decode().strip()
    except subprocess.CalledProcessError as exc:
        raise HTTPException(409, "请从带有 GitHub origin 的 Skilldesk 仓库启动服务。") from exc
    match = re.fullmatch(r"(?:git@github\.com:|ssh://git@github\.com/|https://github\.com/)"
                         r"([A-Za-z0-9-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?", url)
    if not match:
        raise HTTPException(409, "当前项目需要使用 GitHub 的 SSH 或 HTTPS origin 才能发布。")
    return Target(match[1], url)


def tree_entry(repo: Path, path: str) -> tuple[bytes, bytes] | None:
    row = git(repo, "ls-tree", "-z", "HEAD", "--", path)
    if not row:
        return None
    mode, _, oid = row.split(b"\t", 1)[0].split()
    return mode, oid


def blob(repo: Path, path: str) -> bytes | None:
    entry = tree_entry(repo, path)
    if not entry:
        return None
    if entry[0] != b"100644":
        raise ValueError("提示词或索引必须是普通文件")
    return git(repo, "cat-file", "blob", entry[1].decode())


def choose_path(repo: Path, prompt: Prompt, items: dict, old: dict | None) -> str:
    if old and (old["title"], old["category"]) == (prompt.title, prompt.category):
        return old["path"]
    occupied = {entry["path"].casefold() for key, entry in items.items() if key != prompt.id}
    path = catalog.entry_path(prompt.category, prompt.title)
    folder, filename = path.split("/")
    alternate = f"{folder}/{filename[:-4][:42].rstrip()}-{prompt.id[:8]}.txt"
    for candidate in (path, alternate):
        if old and candidate == old["path"]:
            return candidate
        if candidate.casefold() not in occupied and tree_entry(repo, "prompts/" + candidate) is None:
            return candidate
    raise HTTPException(409, "这个分类中已经有同名文件。请调整标题后再发布。")


def commit(repo: Path, branch: str, writes: dict[str, bytes], removed: str | None) -> None:
    git(repo, "read-tree", "HEAD")
    if removed:
        git(repo, "update-index", "--force-remove", "--", "prompts/" + removed)
    for relative, content in writes.items():
        oid = git(repo, "hash-object", "-w", "--stdin", data=content).decode().strip()
        git(repo, "update-index", "--add", "--cacheinfo", "100644", oid, "prompts/" + relative)
    tree = git(repo, "write-tree").decode().strip()
    revision = git(repo, "-c", "user.name=Skilldesk", "-c", "user.email=skilldesk@users.noreply.github.com",
                   "commit-tree", tree, "-p", "HEAD", "-m", "Publish one prompt from Skilldesk").decode().strip()
    try:
        git(repo, "push", "origin", revision + ":refs/heads/" + branch)
    except subprocess.CalledProcessError as exc:
        if b"fetch first" in exc.stderr or b"non-fast-forward" in exc.stderr or b"failed to update ref" in exc.stderr:
            raise HTTPException(409, "发布期间 GitHub 有了新的提交。请重新核对后发布。") from exc
        raise HTTPException(502, "推送失败。请检查网络以及本机 Git 对这个分支的写入权限，然后重试。") from exc


def _publication(repo: Path, target: Target, prompt: Prompt, expected: str | None) -> dict:
    branch = git(repo, "symbolic-ref", "--short", "HEAD").decode().strip()
    folder = tree_entry(repo, "prompts")
    if folder and folder[0] != b"040000":
        raise ValueError("仓库的 prompts 必须是目录")
    manifest = blob(repo, "prompts/catalog.json")
    items = catalog.read_catalog(manifest) if manifest is not None else {}
    old = items.get(prompt.id)
    previous = blob(repo, "prompts/" + old["path"]) if old else None
    if old and previous is None:
        raise ValueError("索引中的正文文件缺失")
    version = catalog.public_version(target.name, branch, prompt.id, old, previous or b"")
    path = choose_path(repo, prompt, items, old)
    category_dir = tree_entry(repo, "prompts/" + path.split("/")[0])
    if category_dir and category_dir[0] != b"040000":
        raise ValueError("仓库中的分类路径必须是目录")
    new = {**(old or {}), "title": prompt.title, "category": prompt.category, "path": path}
    content = prompt.body.encode()
    current = old == new and previous == content
    result = {"repository": target.name, "branch": branch, "base": version,
              "state": "current" if current else "update" if old else "new",
              "url": f"https://github.com/{target.name}/blob/{quote(branch, safe='')}/prompts/{quote(path)}"}
    if expected is None:
        if old and not current:
            result["previous"] = {"title": old["title"], "category": old["category"], "body": previous.decode()}
        return result
    if current:
        return result
    if expected != version:
        raise HTTPException(409, "GitHub 上这条提示词已更改。请重新核对两个版本后发布。")
    items[prompt.id] = new
    readme = catalog.index_bytes(items, blob(repo, "prompts/README.md"))
    writes = {path: content, "catalog.json": catalog.catalog_bytes(items), "README.md": readme}
    commit(repo, branch, writes, old["path"] if old and old["path"] != path else None)
    return {**result, "state": "current", "base": catalog.public_version(target.name, branch, prompt.id, new, content)}


def publication(prompt: Prompt, expected: str | None = None) -> dict:
    target = destination()
    with TemporaryDirectory(prefix="skilldesk-publish-") as folder:
        repo = Path(folder)
        try:
            git(repo, "clone", "--depth", "1", "--single-branch", "--no-tags", "--no-checkout", "--", target.remote, ".")
            return _publication(repo, target, prompt, expected)
        except subprocess.CalledProcessError as exc:
            raise HTTPException(502, "无法读取 GitHub 仓库。请检查本机 Git 的网络连接和访问权限。") from exc
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise HTTPException(409, "GitHub 提示词目录或索引异常，请核对仓库中的 prompts/ 目录。") from exc
