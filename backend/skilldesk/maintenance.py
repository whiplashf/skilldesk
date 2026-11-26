"""Preview and apply changes to one exact install entry. Plans survive server restarts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import packages
from .config import state_dir
from .library import read_json, write_json
from .packages import SCRIPT_EXTENSIONS, MaintenanceError
from .placements import (
    dangling_target,
    dependencies,
    install_name,
    lock_data,
    lock_path,
    manifest,
    plain,
    select,
    source_of,
    stores,
    token,
)
from .upstream import _local_tree

PLAN_TTL = 600
PLAN_ID = re.compile(r"[0-9a-f]{32}")
STALE = "安装位置、文件或安装记录已变化，请重新预览"


def plans() -> Path:
    return state_dir() / "maintenance"


@contextmanager
def writing():
    root = plans()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = sqlite3.connect(root / "operations.lock", timeout=10)
    try:
        try:
            lock.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            raise MaintenanceError("其他安装操作仍在进行，请稍后重试", 409) from exc
        recover()
        yield
    finally:
        lock.close()


def exists(path: Path) -> bool:
    return os.path.lexists(path)


def digest(files: dict) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def backup_path(target: Path, plan_id: str) -> Path:
    bucket = target.name + "-" + hashlib.sha256(os.fsencode(target)).hexdigest()[:16]
    return state_dir() / "backups" / bucket / plan_id


def old_state(target: Path, action: str) -> dict:
    lock = lock_path(target.parent)
    data = lock_data(lock) if lock else {}
    record = data.get("skills", {}).get(target.name)
    if lock and target.name in data["skills"] and not isinstance(record, dict):
        raise MaintenanceError("同名安装记录格式无法识别，请核对后重试", 409)
    if action == "install":
        if exists(target) or record is not None:
            raise MaintenanceError("此位置已经有同名目录或安装记录，请在技能详情中管理该副本", 409)
        return {"inode": [], "link": "", "files": {}, "lock": str(lock or ""), "record": None}
    return {
        "inode": token(target),
        "link": os.readlink(target) if target.is_symlink() else "",
        "files": {} if action == "unlink" else manifest(target),
        "lock": str(lock or ""),
        "record": record,
    }


def changed_files(before: dict, after: dict) -> dict:
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "changed": sorted(p for p in before.keys() & after.keys() if before[p] != after[p]),
    }


def drift(target: Path, old: dict) -> str:
    record = old["record"] or {}
    if saved := record.get("skilldeskSnapshot"):
        return "clean" if digest(old["files"]) == saved else "modified"
    tree = record.get("skilldeskTree") or record.get("skillFolderHash") or ""
    if re.fullmatch(r"[0-9a-f]{40}", str(tree)):
        return "clean" if _local_tree(target) == tree else "modified"
    return "unknown"


def expire_plans():
    for slot in plans().iterdir():
        if PLAN_ID.fullmatch(slot.name) and slot.is_dir() and time.time() - slot.stat().st_mtime > 86400:
            shutil.rmtree(slot)


def preview(
    action: str,
    *,
    root: str = "",
    repository: str = "",
    path: str = "",
    item: dict | None = None,
    entry: str = "",
    dangling: bool = False,
    release: dict | None = None,
    expected_record: dict | None = None,
) -> dict:
    with writing():
        expire_plans()
        slot = plans() / uuid.uuid4().hex
        slot.mkdir(mode=0o700)
        try:
            request = None
            if action == "install":
                if Path(root) not in stores():
                    raise MaintenanceError("请选择已配置的全局或项目安装目录")
                request = packages.install_source(repository, path)
                target = None
            elif action == "unlink" and dangling:
                target = Path(entry)
                if not dangling_target(target):
                    raise MaintenanceError("此入口不符合解除条件或已经恢复，请刷新安装健康", 409)
            else:
                if not item or action not in {"update", "uninstall", "unlink"}:
                    raise MaintenanceError("请选择本机库中的具体安装位置")
                target = select(item, entry, action)
            license_name = commit = ""
            coordinate = None
            before = old_state(target, action) if target else None
            after = {}
            new_tree = cli_digest = ""
            if action == "update":
                record = before["record"]
                installed = source_of(record)
                if installed.host == "github.com" and not release:
                    raise MaintenanceError("请先检查正式 Release，再选择要更新的版本", 409)
                if release and record != expected_record:
                    raise MaintenanceError(STALE, 409)
                request = packages.InstallSource(installed, ref=str(record.get("ref") or ""),
                                                 commit=release["commit"] if release else "")
            if request is not None:
                try:
                    resolved, commit, license_name = packages.materialize(request, slot / "package")
                except MaintenanceError as error:
                    if action == "update" and error.status == 404:
                        raise MaintenanceError("原安装路径已从仓库移除，请核实上游目录", 409) from error
                    raise
                coordinate = resolved.json()
                if target is None:
                    target = Path(root) / install_name(resolved, slot / "package")
                    before = old_state(target, action)
                after = manifest(slot / "package")
                new_tree = _local_tree(slot / "package")
                cli_digest = packages.cli_hash(slot / "package")
            report = {
                "id": slot.name,
                "action": action,
                **({"release": release} if release else {}),
                "target": str(target),
                "source": coordinate,
                "backup": str(backup_path(target, slot.name)) if action in {"update", "uninstall"} else "",
                "commit": commit,
                "ref": request.ref if request else "",
                "license": license_name,
                "expiresAt": int(time.time()) + PLAN_TTL,
                "localState": drift(target, before) if action in {"update", "uninstall"} else "clean",
                "links": dependencies(item, target) if item and action != "unlink" else [],
                "linkTarget": (os.readlink(target) if dangling else str(target.resolve())) if action == "unlink" else "",
                "dangling": dangling,
                "changes": changed_files(before["files"], after),
                "files": len([v for v in after.values() if v[0] != "dir"]),
                "bytes": sum(v[2] for v in after.values()),
                "scripts": sorted(
                    p
                    for p, v in after.items()
                    if v[0] != "dir"
                    and (Path(p).suffix.lower() in SCRIPT_EXTENSIONS or v[0] == "file" and v[1] & 0o111)
                ),
            }
            anchor = next(parent for parent in target.parents if parent.is_dir())
            plan = {
                "anchor": [str(anchor), token(anchor)], "report": report,
                "key": item["identity_key"] if item else "", "before": before,
                "after": after, "tree": new_tree, "cliHash": cli_digest,
            }
            if action == "update" and report["localState"] == "clean" and before["files"] == after:
                candidate = record_after(plan)
                candidate["updatedAt"] = before["record"].get("updatedAt")
                report["backup"] = ""
                if candidate == before["record"]:
                    report["outcome"] = "current"
                    shutil.rmtree(slot / "package")
                else:
                    report["outcome"] = "record"
            write_json(slot / "plan.json", plan)
            return report
        except BaseException:
            shutil.rmtree(slot)
            raise


def record_after(plan: dict) -> dict | None:
    r = plan["report"]
    if r["action"] not in {"install", "update"}:
        return None
    source = r["source"]
    old = plan["before"]["record"] or {}
    now = datetime.now(timezone.utc).isoformat()
    record = {
        **old,
        "source": old.get("source") or (source["repo"] if source["host"] == "github.com" else source["url"]),
        "sourceType": old.get("sourceType") or ("github" if source["host"] == "github.com" else "git"),
        "sourceUrl": source["url"],
        "skillPath": source["path"],
        "commit": r["commit"],
        "skilldeskTree": plan["tree"],
        "skilldeskSnapshot": digest(plan["after"]),
        "installedAt": old.get("installedAt") or now,
        "updatedAt": now,
    }
    lock = Path(plan["before"]["lock"])
    if r.get("ref"):
        record["ref"] = r["ref"]
    if lock.name == "skills-lock.json":
        record["computedHash"] = (
            plan["cliHash"]
            if lock_data(lock).get("version") == 2
            else packages.legacy_cli_hash(
                Path(r["target"]) if r.get("outcome") == "record" else plans() / r["id"] / "package", plan["after"]
            )
        )
    else:
        record["skillFolderHash"] = plan["tree"] if source["host"] == "github.com" else plan["cliHash"]
        record["computedHash"] = plan["cliHash"]
    return record


def edit_record(plan: dict, expected: dict | None, value: dict | None):
    if not plan["before"]["lock"] or expected == value:
        return
    path = Path(plan["before"]["lock"])
    name = Path(plan["report"]["target"]).name
    data = lock_data(path)
    current = data["skills"].get(name)
    if current != expected:
        raise MaintenanceError(STALE, 409)
    if value is None:
        data["skills"].pop(name, None)
    else:
        data["skills"][name] = value
    write_json(path, data)


def verify(plan: dict, get_item):
    report = plan["report"]
    target = Path(report["target"])
    action = report["action"]
    anchor, inode = plan["anchor"]
    if not plain(Path(anchor)) or not Path(anchor).is_dir() or token(Path(anchor)) != inode:
        raise MaintenanceError(STALE, 409)
    if action == "install" or report.get("outcome") == "current":
        if target.parent not in stores():
            raise MaintenanceError(STALE, 409)
    elif report.get("dangling"):
        if not dangling_target(target) or os.readlink(target) != plan["before"]["link"]:
            raise MaintenanceError(STALE, 409)
    else:
        item = get_item(plan["key"])
        if not item:
            raise MaintenanceError(STALE, 409)
        select(item, str(target), action)
        if action != "unlink" and report["links"] != dependencies(item, target):
            raise MaintenanceError(STALE, 409)
    if old_state(target, action) != plan["before"]:
        raise MaintenanceError(STALE, 409)


def remove_scratch(path: Path):
    # Backups preserve original permissions. Temporary copies can contain read-only directories.
    for folder, _, _ in os.walk(path, followlinks=False):
        directory = Path(folder)
        if not directory.is_symlink():
            directory.chmod(directory.stat().st_mode | 0o700)
    shutil.rmtree(path)


def cleanup(journal: dict):
    txn = Path(journal["txn"])
    if txn.is_dir() and plain(txn):
        remove_scratch(txn)
    (plans() / "active.json").unlink(missing_ok=True)


def recover():
    journal = read_json(plans() / "active.json", {})
    if not journal:
        return
    if journal.get("staging"):
        cleanup(journal)
        return
    slot = plans() / journal["id"]
    plan = read_json(slot / "plan.json", {})
    target = Path(plan["report"]["target"])
    previous = Path(journal["previous"])
    if not plain(target.parent) or not plain(previous.parent):
        raise MaintenanceError("恢复操作需要检查原安装目录 " + str(previous), 409)
    if not (slot / "result.json").exists():
        if exists(target) and token(target) == journal["incoming"]:
            if manifest(target) != plan["after"]:
                raise MaintenanceError("中断后新副本又被修改，旧副本保存在 " + str(previous), 409)
            os.replace(target, Path(journal["txn"]) / "incoming")
        if exists(previous):
            if exists(target):
                raise MaintenanceError("恢复位置已被占用，原副本保存在 " + str(previous), 409)
            os.replace(previous, target)
        lock = plan["before"]["lock"]
        if lock:
            current = lock_data(Path(lock))["skills"].get(target.name)
            if current == journal["record"]:
                edit_record(plan, current, plan["before"]["record"])
        if backup_name := plan["report"]["backup"]:
            backup = Path(backup_name)
            if plain(backup) and backup.is_dir():
                remove_scratch(backup)
    cleanup(journal)


def recover_pending():
    if (plans() / "active.json").is_file():
        with writing():
            pass


def apply(plan_id: str, get_item, *, accept_license: bool = False, accept_local: bool = False) -> dict:
    if not PLAN_ID.fullmatch(plan_id):
        raise MaintenanceError("预览编号无效", 404)
    with writing():
        slot = plans() / plan_id
        if result := read_json(slot / "result.json", {}):
            return result
        plan = read_json(slot / "plan.json", {})
        if not plan or plan["report"]["expiresAt"] <= time.time():
            raise MaintenanceError("预览已过期，请重新预览", 410)
        r = plan["report"]
        action = r["action"]
        if action == "update" and (r.get("source") or {}).get("host") == "github.com" and not r.get("release"):
            raise MaintenanceError("旧版升级预览已过期，请重新检查正式 Release", 410)
        if r.get("outcome") == "current":
            verify(plan, get_item)
            return {"action": action, "target": r["target"], "backup": "", "outcome": "current"}
        record_only = r.get("outcome") == "record"
        incoming = action in {"install", "update"} and not record_only
        if incoming and not r["license"] and not accept_license:
            raise MaintenanceError("请确认已了解上游没有声明许可证")
        if r["localState"] != "clean" and not accept_local:
            raise MaintenanceError("请确认已查看本地修改或缺失的安装基准")
        verify(plan, get_item)
        target = Path(r["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not plain(target.parent):
            raise MaintenanceError(STALE, 409)
        txn = Path(tempfile.mkdtemp(dir=target.parent, prefix=".skilldesk-txn-"))
        stage = txn / "incoming"
        backup = Path(r["backup"]) if r["backup"] else None
        previous = txn / "previous"
        result = {"action": action, "target": str(target), "backup": r["backup"]}
        if release := r.get("release"):
            result.update(release=release, key=plan["key"])
        if record_only:
            result["outcome"] = "record"
        journal = {"id": plan_id, "txn": str(txn), "previous": str(previous), "staging": True}
        try:
            write_json(plans() / "active.json", journal)
            if incoming:
                shutil.copytree(slot / "package", stage, symlinks=True)
                if manifest(stage) != plan["after"]:
                    raise MaintenanceError("暂存文件与预览不一致，请重新预览", 409)
            if backup:
                if not plain(backup.parent) or exists(backup):
                    raise MaintenanceError("备份位置已变化，请检查本机目录", 409)
                backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            verify(plan, get_item)
            record = plan["before"]["record"] if r.get("dangling") else record_after(plan)
            journal.update(staging=False, incoming=token(stage) if incoming else [], record=record)
            write_json(plans() / "active.json", journal)
            if action != "install" and not record_only:
                os.replace(target, previous)
                if token(previous) != plan["before"]["inode"]:
                    raise MaintenanceError(STALE, 409)
                if r.get("dangling") and (os.readlink(previous) != plan["before"]["link"]
                                          or (target.parent / r["linkTarget"]).exists()):
                    raise MaintenanceError(STALE, 409)
                if action != "unlink" and manifest(previous) != plan["before"]["files"]:
                    raise MaintenanceError(STALE, 409)
            if incoming:
                if exists(target):
                    raise MaintenanceError(STALE, 409)
                os.replace(stage, target)
            if backup:
                shutil.copytree(previous, backup, symlinks=True)
                if manifest(backup) != plan["before"]["files"]:
                    raise MaintenanceError("原副本的备份未完整写入，操作已取消", 409)
            edit_record(plan, plan["before"]["record"], record)
            write_json(slot / "result.json", result)
        except BaseException:
            if (plans() / "active.json").exists():
                recover()
            else:
                remove_scratch(txn)
            raise
        cleanup(journal)
        shutil.rmtree(slot / "package", ignore_errors=True)
        return result
