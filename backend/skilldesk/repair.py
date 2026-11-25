"""Repairs for the problems health can actually fix on its own.

Only one class of issue is mechanically safe: a dangling symlink in a host root.
If a store copy with the same entry name exists, the link is re-pointed at it;
if nothing exists, the dead link can be removed on request. Everything else —
unclaimed provenance, duplicate content — needs a human decision, so it is
refused here rather than guessed at.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


class RepairError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _host_roots(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute("SELECT path, kind FROM host_root WHERE exists_ = 1 ORDER BY priority, path")
    return [(str(row["path"]), str(row["kind"])) for row in rows]


def find_issue(conn: sqlite3.Connection, issue_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM health_issue WHERE id = ?", [issue_id]).fetchone()
    if row is None:
        raise RepairError("这条问题已不存在，请刷新后重试", 404)
    return row


def _store_copy(conn: sqlite3.Connection, entry: Path) -> Path | None:
    """A real directory with the same name living in another host root."""
    here = os.path.realpath(str(entry.parent))
    roots = [(path, kind) for path, kind in _host_roots(conn) if os.path.realpath(path) != here]
    # The store is the physical home of installed skills, so prefer it.
    roots.sort(key=lambda pair: (pair[1] != "agents", pair[0]))
    for path, _kind in roots:
        candidate = Path(path) / entry.name
        if candidate.is_dir() and not candidate.is_symlink():
            return candidate
    return None


def fix_issue(conn: sqlite3.Connection, issue_id: str, action: str = "auto") -> dict:
    row = find_issue(conn, issue_id)
    if row["kind"] != "dangling_link":
        raise RepairError("这类问题需要人工判断：请到 skill 详情里认领来源或处理重复副本", 400)

    entry = Path(str(row["target"]))
    if not entry.is_symlink():
        raise RepairError("这条软链已经不存在，可能已被修复，请刷新", 409)
    roots = {os.path.realpath(path) for path, _ in _host_roots(conn)}
    if os.path.realpath(str(entry.parent)) not in roots:
        raise RepairError("这条软链不在已登记的宿主根里，拒绝操作", 400)

    if action == "remove":
        old = os.readlink(entry)
        entry.unlink()
        return {"fixed": True, "action": "removed", "entry": str(entry), "previous": old}

    store = _store_copy(conn, entry)
    if store is None:
        raise RepairError("没有找到同名的实体副本；这条只能移除死链", 409)
    old = os.readlink(entry)
    entry.unlink()
    entry.symlink_to(store, target_is_directory=True)
    return {"fixed": True, "action": "relinked", "entry": str(entry), "previous": old, "target": str(store)}
