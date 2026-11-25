"""Plan, fetch and install a remote skill into a host root.

Two phases, so nothing lands on disk by accident:

* **plan** — clone the repository shallowly into a cache slot, list exactly which
  files would be written, surface the license and an inventory of scripts, and
  hand back a ``planId`` that is bound to that commit.
* **apply** — verify the upstream has not moved since planning, then copy the
  skill folder into ``~/.agents/skills/<name>``, register it in the skills CLI
  lockfile, link the other agent roots and record an install baseline.

Skill scripts are never executed. A repository without a detectable license
needs an explicit acknowledgement before anything is written.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from . import baselines, upstream
from .config import cache_dir, home, load_config, state_dir
from .hosts import discover_roots
from .library import read_json, write_json
from .net import resolve_proxy
from .registry import normalise

PLAN_TTL = 600
MAX_FILES = 400
MAX_TOTAL_BYTES = 8 * 1024 * 1024
SCRIPT_SUFFIXES = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".ps1", ".fish"}
AGENT_LINK_KINDS = ("claude", "opencode")
LOCKFILE = ".skill-lock.json"


class InstallError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------- helpers


def coordinates(host: str, repo: str, path: str) -> dict[str, str]:
    entry = normalise({"host": host, "repo": repo, "path": path})
    if entry is None:
        raise InstallError("请填写合法的 host / owner-repo / 仓库内 SKILL.md 路径")
    return entry


def plans_dir() -> Path:
    return state_dir() / "plans"


def clones_dir() -> Path:
    return cache_dir() / "clones"


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    if shutil.which("git") is None:
        raise InstallError("需要本机安装 git 才能从仓库拉取 skill", 503)
    command = ["git"]
    proxy = resolve_proxy()
    if proxy and "://" in proxy:
        command += ["-c", f"http.proxy={proxy}", "-c", f"https.proxy={proxy}"]
    command += list(args)
    completed = subprocess.run(
        command, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=180, check=False
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise InstallError(f"git 失败：{detail[-1][:160] if detail else '未知错误'}", 502)
    return completed.stdout


def clone_url(host: str, repo: str) -> str:
    return f"https://{host}/{repo}.git"


def _clone_slot(host: str, repo: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "__", f"{host}__{repo}")
    return clones_dir() / safe


def _path_in_head(slot: Path, relative: str) -> bool:
    completed = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{relative}"],
        cwd=str(slot), capture_output=True, text=True, timeout=30, check=False,
    )
    return completed.returncode == 0


def materialise(slot: Path, skill_dir: str) -> None:
    """Write the skill folder into the working tree of a ``--no-checkout`` clone."""
    target = skill_dir or "."
    _git("checkout", "HEAD", "--", target, cwd=slot)


def _fresh_clone(host: str, repo: str, *, refresh: bool = False) -> tuple[Path, str]:
    """Shallow clone into a cache slot; returns (path, commit)."""
    slot = _clone_slot(host, repo)
    if refresh and slot.exists():
        shutil.rmtree(slot, ignore_errors=True)
    if not slot.exists():
        slot.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--depth", "1", "--no-checkout", clone_url(host, repo), str(slot))
    commit = _git("rev-parse", "HEAD", cwd=slot).strip()
    return slot, commit


def _remote_head(host: str, repo: str) -> str:
    output = _git("ls-remote", clone_url(host, repo), "HEAD")
    parts = output.split()
    return parts[0].strip() if parts else ""


def _license_of(host: str, repo: str) -> str:
    """Best-effort SPDX id; an empty string means "unknown, ask the user"."""
    if host != "github.com":
        return ""
    url = f"https://api.github.com/repos/{repo}/license"
    try:
        with httpx_client() as client:
            response = client.get(url)
            if response.status_code != 200:
                return ""
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return ""
    spdx = str(((payload.get("license") or {}) if isinstance(payload, dict) else {}).get("spdx_id") or "")
    return "" if spdx.upper() == "NOASSERTION" else spdx


def httpx_client() -> httpx.Client:
    from .net import http_client

    return http_client(headers=upstream.github_headers(), timeout=20, url_hint="https://api.github.com/")


def _skill_dir(path: str) -> str:
    directory = str(Path(path).parent.as_posix())
    return "" if directory == "." else directory


def _files_in(repo_root: Path, skill_dir: str) -> list[dict[str, Any]]:
    base = repo_root / skill_dir if skill_dir else repo_root
    if not base.is_dir():
        raise InstallError("仓库里找不到这个 skill 目录", 404)
    files: list[dict[str, Any]] = []
    for current, dirs, names in os.walk(base):
        dirs[:] = sorted(item for item in dirs if item != ".git")
        for name in sorted(names):
            path = Path(current) / name
            rel = str(path.relative_to(base)).replace(os.sep, "/")
            try:
                size = path.stat().st_size
            except OSError:
                continue
            files.append({"path": rel, "size": size, "mode": int(path.stat().st_mode & 0o777)})
    return files


def _scripts(files: list[dict[str, Any]]) -> list[str]:
    return [
        item["path"]
        for item in files
        if Path(item["path"]).suffix.lower() in SCRIPT_SUFFIXES or item["path"].split("/")[0] == "scripts"
    ]


def target_roots() -> tuple[Path, list[Path]]:
    """(store root, other agent roots that should get a symlink)."""
    roots = discover_roots(load_config())
    existing = [root for root in roots if root.exists and root.kind != "custom"]
    store = next((root for root in existing if root.kind == "agents"), None)
    if store is None:
        store = next((root for root in existing if root.kind in ("claude", "opencode", "codex")), None)
    if store is None:
        raise InstallError("没有找到可用于安装的宿主根（~/.agents/skills）", 500)
    links = [root.path for root in existing if root.kind in AGENT_LINK_KINDS and str(root.path) != str(store.path)]
    return Path(store.path), links


# ------------------------------------------------------------------------ plan


def plan(host: str, repo: str, path: str, *, refresh: bool = False) -> dict[str, Any]:
    entry = coordinates(host, repo, path)
    skill_dir = _skill_dir(entry["path"])
    slot, commit = _fresh_clone(entry["host"], entry["repo"], refresh=refresh)
    if not _path_in_head(slot, skill_dir or "."):
        raise InstallError("仓库里找不到这个 skill 目录", 404)
    materialise(slot, skill_dir)
    files = _files_in(slot, skill_dir)
    total = sum(item["size"] for item in files)
    store, links = target_roots()
    name = Path(skill_dir).name if skill_dir else Path(entry["repo"].split("/")[-1]).name
    target = store / name
    license_id = _license_of(entry["host"], entry["repo"])

    warnings: list[str] = []
    if not license_id:
        warnings.append("仓库未声明可识别的许可证，安装前需要你明确确认")
    if len(files) > MAX_FILES:
        warnings.append(f"文件数 {len(files)} 超过上限 {MAX_FILES}")
    if total > MAX_TOTAL_BYTES:
        warnings.append(f"体积 {total} 字节超过上限 {MAX_TOTAL_BYTES}")
    if target.exists():
        warnings.append(f"目标已存在：{target}（安装会覆盖）")
    scripts = _scripts(files)
    if scripts:
        warnings.append(f"包含 {len(scripts)} 个脚本文件（不会被自动执行）")

    plan_id = f"{entry['host']}:{entry['repo']}@{entry['path']}#{commit[:12]}"
    payload = {
        "planId": plan_id,
        "host": entry["host"],
        "repo": entry["repo"],
        "path": entry["path"],
        "name": name,
        "commit": commit,
        "license": license_id,
        "files": files,
        "scripts": scripts,
        "totalBytes": total,
        "target": str(target),
        "store": str(store),
        "links": [str(item) for item in links],
        "clone": str(slot),
        "warnings": warnings,
        "createdAt": int(time.time()),
        "expiresAt": int(time.time()) + PLAN_TTL,
    }
    plans_dir().mkdir(parents=True, exist_ok=True)
    write_json(plans_dir() / (plan_id.replace("/", "_").replace(":", "__") + ".json"), payload)
    return payload


def _load_plan(plan_id: str) -> dict[str, Any]:
    safe = plan_id.replace("/", "_").replace(":", "__")
    payload = read_json(plans_dir() / (safe + ".json"), {})
    if not isinstance(payload, dict) or payload.get("planId") != plan_id:
        raise InstallError("找不到这次安装计划，请重新预览", 404)
    if int(payload.get("expiresAt", 0)) < int(time.time()):
        raise InstallError("安装计划已过期，请重新预览", 409)
    return payload


# ----------------------------------------------------------------------- apply


def _register_lockfile(name: str, plan_payload: dict[str, Any]) -> Path:
    path = home() / ".agents" / LOCKFILE
    payload = read_json(path, {})
    if not isinstance(payload, dict) or not isinstance(payload.get("skills"), dict):
        payload = {"version": 3, "skills": {}, "dismissed": {}}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    source_type = "github" if plan_payload["host"] == "github.com" else "git"
    payload["skills"][name] = {
        "source": plan_payload["repo"],
        "sourceType": source_type,
        "sourceUrl": clone_url(plan_payload["host"], plan_payload["repo"]),
        "skillPath": plan_payload["path"],
        "installedAt": stamp,
        "updatedAt": stamp,
    }
    write_json(path, payload)
    return path


def _link_agent_roots(name: str, target: Path, links: list[str]) -> list[str]:
    made: list[str] = []
    for root in links:
        entry = Path(root) / name
        if entry.exists() or entry.is_symlink():
            continue
        Path(root).mkdir(parents=True, exist_ok=True)
        entry.symlink_to(target, target_is_directory=True)
        made.append(str(entry))
    return made


def apply(plan_id: str, *, force: bool = False, acknowledge_license: bool = False) -> dict[str, Any]:
    plan_payload = _load_plan(plan_id)
    if not plan_payload["license"] and not acknowledge_license:
        raise InstallError("该仓库未声明可识别的许可证；确认后重试（acknowledgeLicense）", 409)
    if len(plan_payload["files"]) > MAX_FILES or plan_payload["totalBytes"] > MAX_TOTAL_BYTES:
        raise InstallError("这次安装超出了文件数或体积上限", 413)

    slot = Path(plan_payload["clone"])
    if not slot.is_dir():
        slot, _commit = _fresh_clone(plan_payload["host"], plan_payload["repo"])
    materialise(slot, _skill_dir(plan_payload["path"]))
    head = _git("rev-parse", "HEAD", cwd=slot).strip()
    remote = _remote_head(plan_payload["host"], plan_payload["repo"])
    if head != plan_payload["commit"] or (remote and remote != plan_payload["commit"]):
        raise InstallError("上游在你预览之后有了新提交，请重新预览再安装", 409)

    target = Path(plan_payload["target"])
    if target.exists() or target.is_symlink():
        if not force:
            raise InstallError(f"目标已存在：{target}（确认覆盖后重试）", 409)
        if target.is_symlink():
            target.unlink()
        else:
            shutil.rmtree(target)

    skill_dir = _skill_dir(plan_payload["path"])
    source = slot / skill_dir if skill_dir else slot
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="skilldesk-install-", dir=str(target.parent)))
    try:
        written = staging / "payload"
        shutil.copytree(source, written, symlinks=False, ignore=shutil.ignore_patterns(".git"))
        written.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    lockfile = _register_lockfile(plan_payload["name"], plan_payload)
    links = _link_agent_roots(plan_payload["name"], target, plan_payload["links"])
    upstream_tree = _git("rev-parse", f"HEAD:{skill_dir}" if skill_dir else "HEAD", cwd=slot).strip()
    baselines.record(
        f"src:{plan_payload['host']}/{plan_payload['repo']}@{plan_payload['path']}",
        repo=plan_payload["repo"],
        dir_path=skill_dir,
        dir_tree=upstream_tree,
        head_ref=head,
        local_tree=upstream._local_tree(target),
    )
    return {
        "installed": True,
        "name": plan_payload["name"],
        "target": str(target),
        "commit": head,
        "license": plan_payload["license"],
        "files": len(plan_payload["files"]),
        "scripts": plan_payload["scripts"],
        "links": links,
        "lockfile": str(lockfile),
        "identity_key": f"src:{plan_payload['host']}/{plan_payload['repo']}@{plan_payload['path']}",
    }


# ---------------------------------------------------------------------- import


def vendor_path(host: str, repo: str, path: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "__", f"{host}__{repo}")
    return cache_dir() / "vendor" / safe / path


def import_only(host: str, repo: str, path: str, *, refresh: bool = False) -> dict[str, Any]:
    """Cache the SKILL.md so a registered skill can be read without installing it."""
    entry = coordinates(host, repo, path)
    target = vendor_path(entry["host"], entry["repo"], entry["path"])
    if target.is_file() and not refresh:
        return {"imported": False, "cached": str(target), "bytes": target.stat().st_size}
    slot, commit = _fresh_clone(entry["host"], entry["repo"], refresh=refresh)
    materialise(slot, _skill_dir(entry["path"]))
    source = slot / entry["path"]
    if not source.is_file():
        raise InstallError("仓库里找不到这个 SKILL.md", 404)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    write_json(
        target.with_suffix(".meta.json"),
        {"host": entry["host"], "repo": entry["repo"], "path": entry["path"], "commit": commit, "fetchedAt": int(time.time())},
    )
    return {"imported": True, "cached": str(target), "bytes": target.stat().st_size, "commit": commit}
