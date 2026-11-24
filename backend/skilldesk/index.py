"""SQLite index — a rebuildable projection of a scan.

The index is machine state: deleting it loses nothing the user authored. A
rebuild writes a fresh database next to the old one and swaps it in with
``os.replace`` so readers never observe a half-written index.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION, __version__, library
from .config import index_path
from .health import Issue
from .scan import ScanResult

SCHEMA = """
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);

CREATE TABLE host_root(
    path TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    priority INTEGER NOT NULL,
    exists_ INTEGER NOT NULL,
    entries INTEGER NOT NULL
);

CREATE TABLE skill(
    identity_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    dir_name TEXT NOT NULL,
    description TEXT NOT NULL,
    license TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    lines INTEGER NOT NULL,
    mtime INTEGER NOT NULL,
    realpath TEXT NOT NULL,
    primary_kind TEXT NOT NULL
);

CREATE TABLE agent_access(host_root TEXT, agent TEXT, scope TEXT, PRIMARY KEY(host_root,agent,scope));
CREATE TABLE scan_input(path TEXT PRIMARY KEY, stamp TEXT NOT NULL);

CREATE TABLE placement(
    identity_key TEXT NOT NULL,
    host_root TEXT NOT NULL,
    kind TEXT NOT NULL,
    entry TEXT NOT NULL,
    entry_path TEXT NOT NULL,
    realpath TEXT NOT NULL,
    is_symlink INTEGER NOT NULL,
    PRIMARY KEY(identity_key, entry_path)
);

CREATE TABLE provenance(
    identity_key TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    repo TEXT NOT NULL,
    path TEXT NOT NULL,
    ref TEXT NOT NULL,
    tree TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence TEXT NOT NULL
);

CREATE TABLE health_issue(
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    target TEXT NOT NULL,
    detail TEXT NOT NULL,
    fixable INTEGER NOT NULL
);

CREATE INDEX idx_skill_name ON skill(name COLLATE NOCASE);
CREATE INDEX idx_placement_kind ON placement(kind);
CREATE INDEX idx_issue_kind ON health_issue(kind);
CREATE INDEX idx_prov_repo ON provenance(host, repo);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(path) if path else index_path()
    conn = sqlite3.connect(str(target), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rebuild(result: ScanResult, issues: list[Issue], path: Path | str | None = None) -> dict[str, Any]:
    """Write a complete new index atomically. Returns summary counts."""
    target = Path(path) if path else index_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name + ".", suffix=".tmp", delete=False) as tmpfile:
        tmp = Path(tmpfile.name)
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA)
        scanned_at = int(time.time())
        conn.executemany("INSERT INTO scan_input VALUES (?, ?)", result.inputs.items())
        conn.executemany("INSERT INTO agent_access VALUES (?, ?, ?)",
                         [(str(root.path), agent, scope) for root in result.roots for agent, scope in root.access])
        conn.executemany(
            "INSERT INTO host_root(path, kind, label, priority, exists_, entries) VALUES (?,?,?,?,?,?)",
            [
                (
                    str(root.path),
                    root.kind,
                    root.label,
                    root.priority,
                    int(root.exists),
                    _count_entries(root.path) if root.exists else 0,
                )
                for root in result.roots
            ],
        )
        conn.executemany(
            "INSERT INTO skill(identity_key, name, dir_name, description, license, content_hash, bytes, lines,"
            " mtime, realpath, primary_kind) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    skill.identity_key,
                    skill.name,
                    skill.dir_name,
                    skill.description,
                    skill.license,
                    skill.content_hash,
                    skill.nbytes,
                    skill.lines,
                    skill.mtime,
                    skill.realpath,
                    skill.primary_kind,
                )
                for skill in result.skills
            ],
        )
        conn.executemany(
            "INSERT INTO placement(identity_key, host_root, kind, entry, entry_path, realpath, is_symlink)"
            " VALUES (?,?,?,?,?,?,?)",
            [
                (
                    skill.identity_key,
                    placement.host_root,
                    placement.kind,
                    placement.entry,
                    placement.entry_path,
                    placement.realpath,
                    int(placement.is_symlink),
                )
                for skill in result.skills
                for placement in skill.placements
            ],
        )
        conn.executemany(
            "INSERT INTO provenance(identity_key, host, repo, path, ref, tree, confidence, evidence) VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    skill.identity_key,
                    skill.provenance.host,
                    skill.provenance.repo,
                    skill.provenance.path,
                    skill.provenance.ref,
                    skill.provenance.tree,
                    skill.provenance.confidence,
                    skill.provenance.evidence,
                )
                for skill in result.skills
            ],
        )
        conn.executemany(
            "INSERT INTO health_issue(id, kind, identity_key, target, detail, fixable) VALUES (?,?,?,?,?,?)",
            [
                (issue.id, issue.kind, issue.identity_key, issue.target, issue.detail, int(issue.fixable))
                for issue in issues
            ],
        )
        meta = {
            "schema": str(SCHEMA_VERSION),
            "version": __version__,
            "scanned_at": str(scanned_at),
            "generation": str(time.time_ns()),
            "skills": str(len(result.skills)),
            "placements": str(sum(len(skill.placements) for skill in result.skills)),
            "dangling": str(len(result.dangling)),
            "issues": str(len(issues)),
            "lockfile_entries": str(result.lockfile_entries),
        }
        conn.executemany("INSERT INTO meta(k, v) VALUES (?, ?)", list(meta.items()))
        conn.commit()
    except BaseException:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    finally:
        conn.close()

    os.replace(tmp, target)
    current = connect(target)
    try:
        library.reconcile(current)
    finally:
        current.close()
    return meta


def _count_entries(path: Path) -> int:
    try:
        return len(os.listdir(path))
    except OSError:
        return 0


def meta(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["k"]: row["v"] for row in conn.execute("SELECT k, v FROM meta")}


def is_current(path: Path) -> bool:
    if not path.is_file():
        return False
    conn = connect(path)
    try:
        return meta(conn).get("schema") == str(SCHEMA_VERSION)
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.close()


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    def one(sql: str) -> int:
        row = conn.execute(sql).fetchone()
        return int(row[0]) if row else 0

    return {
        "skills": one("SELECT count(*) FROM skill"),
        "placements": one("SELECT count(*) FROM placement"),
        "dangling": one("SELECT count(*) FROM health_issue WHERE kind = 'dangling_link'"),
        "unclaimed": one("SELECT count(*) FROM provenance WHERE confidence = 'none'"),
        "issues": one("SELECT count(*) FROM health_issue"),
        "roots": one("SELECT count(*) FROM host_root WHERE exists_ = 1"),
    }


_ITEM_SQL = """
SELECT s.identity_key, s.name, s.dir_name, s.description, s.license, s.content_hash,
       s.bytes, s.lines, s.mtime, s.realpath, s.primary_kind,
       p.host, p.repo, p.path, p.ref, p.tree, p.confidence, p.evidence,
       (SELECT json_group_array(DISTINCT json_object('agent', a.agent, 'scope', a.scope))
        FROM placement pl JOIN agent_access a ON pl.host_root = a.host_root
        WHERE pl.identity_key = s.identity_key) AS access,
       (SELECT group_concat(pl.kind) FROM placement pl WHERE pl.identity_key = s.identity_key) AS kinds,
       (SELECT count(*) FROM placement pl WHERE pl.identity_key = s.identity_key) AS placement_count,
       (SELECT group_concat(DISTINCT h.kind) FROM health_issue h WHERE h.identity_key = s.identity_key) AS issues
FROM skill s LEFT JOIN provenance p ON p.identity_key = s.identity_key
"""


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "identity_key": row["identity_key"],
        "name": row["name"],
        "dir_name": row["dir_name"],
        "description": row["description"],
        "license": row["license"],
        "content_hash": row["content_hash"],
        "bytes": row["bytes"],
        "lines": row["lines"],
        "mtime": row["mtime"],
        "realpath": row["realpath"],
        "primary_kind": row["primary_kind"],
        "host_kinds": sorted({kind for kind in (row["kinds"] or "").split(",") if kind}),
        "access": json.loads(row["access"]),
        "placement_count": row["placement_count"],
        "health": sorted({kind for kind in (row["issues"] or "").split(",") if kind}),
        "provenance": {
            "host": row["host"] if "host" in keys else "",
            "repo": row["repo"] if "repo" in keys else "",
            "path": row["path"] if "path" in keys else "",
            "ref": row["ref"] if "ref" in keys else "",
            "tree": row["tree"] or "",
            "confidence": (row["confidence"] if "confidence" in keys else "") or "none",
            "evidence": row["evidence"] if "evidence" in keys else "",
            "label": _provenance_label(row, keys),
        },
    }


def _provenance_label(row: sqlite3.Row, keys: set[str]) -> str:
    if "host" not in keys:
        return ""
    host = row["host"] or ""
    repo = row["repo"] or ""
    if not host and not repo:
        return ""
    return f"{host}/{repo}" if host else repo


def list_skills(
    conn: sqlite3.Connection,
    *,
    q: str = "",
    host: str = "",
    source: str = "",
    confidence: str = "",
    health: str = "",
    agent: str = "",
    view: str = "all",
    assets: dict | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    if q:
        like = f"%{q}%"
        where.append("(s.name LIKE ? OR s.description LIKE ? OR s.dir_name LIKE ?)")
        params.extend([like, like, like])
    if host:
        where.append("EXISTS (SELECT 1 FROM placement pl WHERE pl.identity_key = s.identity_key AND pl.kind = ?)")
        params.append(host)
    if agent:
        where.append("EXISTS (SELECT 1 FROM placement pl JOIN agent_access a ON a.host_root = pl.host_root "
                     "WHERE pl.identity_key = s.identity_key AND a.agent = ?)")
        params.append(agent)
    annotations = assets or {}
    annotated = "SELECT value FROM json_each(?)"
    if view in ("favorites", "mine"):
        flag = "favorite" if view == "favorites" else "mine"
        where.append(f"s.identity_key IN ({annotated})")
        params.append(json.dumps([key for key, value in annotations.items() if value.get(flag)]))
    if view == "github":
        where.append(f"(p.host = 'github.com' OR s.identity_key IN ({annotated})) AND s.identity_key NOT IN ({annotated})")
        params.append(json.dumps([key for key, value in annotations.items() if value.get("github")]))
        params.append(json.dumps([key for key, value in annotations.items() if value.get("mine")]))
    if source:
        where.append("(p.host || '/' || p.repo) = ?")
        params.append(source)
    if confidence:
        where.append("p.confidence = ?")
        params.append(confidence)
    if health:
        where.append("EXISTS (SELECT 1 FROM health_issue h WHERE h.identity_key = s.identity_key AND h.kind = ?)")
        params.append(health)

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        "SELECT count(*) FROM skill s LEFT JOIN provenance p ON p.identity_key = s.identity_key" + clause,
        params,
    ).fetchone()[0]
    rows = conn.execute(
        _ITEM_SQL + clause + " ORDER BY s.name COLLATE NOCASE, s.identity_key LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return {
        "items": [_row_to_item(row) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


def facets(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    hosts = [
        {"value": row["kind"], "label": row["kind"], "count": row["n"]}
        for row in conn.execute(
            "SELECT kind, count(DISTINCT identity_key) AS n FROM placement GROUP BY kind ORDER BY n DESC"
        )
    ]
    sources = [
        {"value": f"{row['host']}/{row['repo']}", "label": f"{row['host']}/{row['repo']}", "count": row["n"]}
        for row in conn.execute(
            "SELECT host, repo, count(*) AS n FROM provenance WHERE repo <> '' GROUP BY host, repo ORDER BY n DESC"
        )
    ]
    confidence = [
        {"value": row["confidence"], "label": row["confidence"], "count": row["n"]}
        for row in conn.execute("SELECT confidence, count(*) AS n FROM provenance GROUP BY confidence ORDER BY n DESC")
    ]
    health = [
        {"value": row["kind"], "label": row["kind"], "count": row["n"]}
        for row in conn.execute("SELECT kind, count(*) AS n FROM health_issue GROUP BY kind ORDER BY n DESC")
    ]
    agents = [{"value": row[0], "count": row[1]} for row in conn.execute(
        "SELECT agent, count(DISTINCT identity_key) FROM agent_access JOIN placement USING(host_root) "
        "GROUP BY agent ORDER BY agent")]
    return {"hosts": hosts, "agents": agents, "sources": sources, "confidence": confidence, "health": health}


def get_skill(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    row = conn.execute(_ITEM_SQL + " WHERE s.identity_key = ?", [key]).fetchone()
    if row is None:
        return None
    item = _row_to_item(row)
    item["placements"] = list_placements(conn, key)
    item["issues"] = list_issues(conn, identity_key=key)
    return item


def list_placements(conn: sqlite3.Connection, key: str) -> list[dict[str, Any]]:
    return [
        {
            "host_root": row["host_root"],
            "kind": row["kind"],
            "entry": row["entry"],
            "entry_path": row["entry_path"],
            "realpath": row["realpath"],
            "is_symlink": bool(row["is_symlink"]),
        }
        for row in conn.execute(
            "SELECT * FROM placement WHERE identity_key = ? ORDER BY kind, entry_path", [key]
        )
    ]


def list_issues(
    conn: sqlite3.Connection, *, kind: str = "", identity_key: str = "", limit: int = 500, offset: int = 0
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if identity_key:
        where.append("identity_key = ?")
        params.append(identity_key)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        "SELECT * FROM health_issue" + clause + " ORDER BY kind, target LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "identity_key": row["identity_key"],
            "target": row["target"],
            "detail": row["detail"],
            "fixable": bool(row["fixable"]),
        }
        for row in rows
    ]


def list_roots(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {
            "path": row["path"],
            "kind": row["kind"],
            "label": row["label"],
            "priority": row["priority"],
            "exists": bool(row["exists_"]),
            "entries": row["entries"],
        }
        for row in conn.execute("SELECT * FROM host_root ORDER BY priority, path")
    ]
