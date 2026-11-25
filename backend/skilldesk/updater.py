"""Update or remove a skill that is already installed.

Updating is the install pipeline plus three things an install does not need:
a diff against what is on disk today, a check for local edits (so a hand-tuned
skill is never silently replaced), and a backup of the old folder before the swap.

Removal undoes everything an install wrote: the folder, the symlinks in the other
agent roots, the lockfile entry and the install baseline.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import baselines, installer
from .config import cache_dir, home
from .library import read_json, write_json

BACKUP_KEEP = 3


class UpdateError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _hash_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_files(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    found: dict[str, str] = {}
    for current, dirs, names in os.walk(root):
        dirs[:] = [item for item in dirs if item != ".git"]
        for name in names:
            path = Path(current) / name
            if path.is_file() and not path.is_symlink():
                found[str(path.relative_to(root)).replace("\\", "/")] = _hash_of(path)
    return found


def diff(upstream_root: Path, local_root: Path) -> dict[str, Any]:
    """What an update would change, by content hash."""
    upstream = _local_files(upstream_root)
    local = _local_files(local_root)
    added = sorted(path for path in upstream if path not in local)
    removed = sorted(path for path in local if path not in upstream)
    updated = sorted(path for path in upstream if path in local and upstream[path] != local[path])
    unchanged = sorted(path for path in upstream if path in local and upstream[path] == local[path])
    return {
        "added": added,
        "updated": updated,
        "removed": removed,
        "unchanged": len(unchanged),
        "identical": not (added or updated or removed),
    }


def installed_commit(identity_key: str, repo: str, dir_path: str) -> str:
    baseline = baselines.get(identity_key, repo, dir_path)
    return str((baseline or {}).get("headRef") or "")


def plan_update(host: str, repo: str, path: str, *, identity_key: str = "", refresh: bool = False) -> dict[str, Any]:
    """An install plan plus a diff against the installed folder and a drift check."""
    base = installer.plan(host, repo, path, refresh=refresh)
    target = Path(base["target"])
    skill_dir = installer._skill_dir(path)
    slot = Path(base["clone"])
    upstream_root = slot / skill_dir if skill_dir else slot
    local = diff(upstream_root, target)

    baseline = baselines.get(identity_key, repo, skill_dir) if identity_key else None
    local_tree = installer.upstream._local_tree(target) if target.is_dir() else ""
    drift = bool(baseline and baseline.get("localTree") and local_tree != baseline["localTree"])
    from_commit = str((baseline or {}).get("headRef") or "")

    warnings = [warning for warning in base["warnings"] if not warning.startswith("目标已存在")]
    if drift:
        warnings.append("本地副本自安装后被改动，升级会用上游内容覆盖它（需要确认）")
    if local["identical"]:
        warnings.append("与已安装内容一致，升级不会有任何变化")
    if not target.is_dir():
        raise UpdateError("本机没有这个 skill 的实体目录，无法升级", 404)

    payload = {
        **base,
        "kind": "update",
        "from": from_commit,
        "fromKnown": bool(baseline and baseline.get("headRef")),
        "to": base["commit"],
        "diff": local,
        "localDrift": drift,
        "warnings": warnings,
    }
    # Re-store the enriched plan so apply can load the diff back.
    plan_file = installer.plans_dir() / (payload["planId"].replace("/", "_").replace(":", "__") + ".json")
    write_json(plan_file, payload)
    return payload


def _backup(target: Path, name: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = cache_dir() / "backup" / name
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / stamp
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(target, destination, symlinks=True)
    snapshots = sorted(item for item in folder.iterdir() if item.is_dir())
    for stale in snapshots[:-BACKUP_KEEP]:
        shutil.rmtree(stale, ignore_errors=True)
    return destination


def apply_update(
    plan_id: str,
    *,
    force: bool = False,
    acknowledge_license: bool = False,
    allow_drift: bool = False,
) -> dict[str, Any]:
    payload = installer._load_plan(plan_id)
    target = Path(payload["target"])
    if payload.get("localDrift") and not allow_drift:
        raise UpdateError("本地副本被改动过；确认要覆盖后重试（allowDrift）", 409)
    if not target.is_dir():
        raise UpdateError("本机没有这个 skill 的实体目录，无法升级", 404)
    lockfile = home() / ".agents" / installer.LOCKFILE
    previous = (read_json(lockfile, {}).get("skills") or {}).get(payload["name"]) or {}
    backup = _backup(target, payload["name"])
    try:
        result = installer.apply(plan_id, force=True, acknowledge_license=acknowledge_license)
    except installer.InstallError as error:
        raise UpdateError(error.message, error.status) from error
    lockfile = _touch_lockfile(payload["name"], kept_installed_at=str(previous.get("installedAt") or ""))
    return {
        **result,
        "updated": True,
        "backup": str(backup),
        "from": payload.get("from", ""),
        "to": payload.get("commit", ""),
        "diff": payload.get("diff", {}),
        "lockfile": str(lockfile),
    }


def _touch_lockfile(name: str, *, kept_installed_at: str = "") -> Path:
    """Keep ``installedAt`` (first install) and bump ``updatedAt``."""
    path = home() / ".agents" / installer.LOCKFILE
    payload = read_json(path, {})
    skills = payload.get("skills") if isinstance(payload, dict) else None
    if isinstance(skills, dict) and isinstance(skills.get(name), dict):
        if kept_installed_at:
            skills[name]["installedAt"] = kept_installed_at
        skills[name]["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        write_json(path, payload)
    return path


def uninstall(
    *,
    identity_key: str,
    name: str,
    target: str,
    repo: str = "",
    dir_path: str = "",
    placements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Remove a skill: folder, symlinks, lockfile entry and baseline."""
    folder = Path(target)
    removed_links: list[str] = []
    for placement in placements or []:
        entry = Path(str(placement.get("entry_path") or ""))
        if placement.get("is_symlink") and entry.is_symlink():
            try:
                entry.unlink()
                removed_links.append(str(entry))
            except OSError:
                continue
    removed_folder = False
    if folder.is_symlink():
        folder.unlink()
        removed_folder = True
    elif folder.is_dir():
        shutil.rmtree(folder)
        removed_folder = True

    lockfile = home() / ".agents" / installer.LOCKFILE
    payload = read_json(lockfile, {})
    removed_lock = False
    if isinstance(payload, dict) and isinstance(payload.get("skills"), dict) and name in payload["skills"]:
        payload["skills"].pop(name, None)
        write_json(lockfile, payload)
        removed_lock = True

    removed_baseline = baselines.forget(identity_key) if identity_key else False
    return {
        "uninstalled": True,
        "name": name,
        "removedFolder": removed_folder,
        "removedLinks": removed_links,
        "removedLockEntry": removed_lock,
        "removedBaseline": removed_baseline,
        "target": str(folder),
        "repo": repo,
        "dirPath": dir_path,
    }
