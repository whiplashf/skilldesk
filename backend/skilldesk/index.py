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
from collections import Counter
from pathlib import Path
from typing import Any

from . import SCHEMA_VERSION, __version__, categories, library
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
    installed_at TEXT NOT NULL,
    folder_hash TEXT NOT NULL,
    local_root TEXT NOT NULL,
    checkout_remote TEXT NOT NULL,
    provider TEXT NOT NULL,
    source_label TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence TEXT NOT NULL
);

CREATE TABLE health_issue(
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    identity_key TEXT NOT NULL,
    target TEXT NOT NULL,
    detail TEXT NOT NULL,
    fixable INTEGER NOT NULL,
    context TEXT NOT NULL
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
            "INSERT INTO provenance(identity_key, host, repo, path, ref, tree, installed_at, folder_hash, "
            "local_root, checkout_remote, provider, source_label, confidence, evidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    skill.identity_key,
                    skill.provenance.host,
                    skill.provenance.repo,
                    skill.provenance.path,
                    skill.provenance.ref,
                    skill.provenance.tree,
                    skill.provenance.installed_at,
                    skill.provenance.folder_hash,
                    skill.provenance.local_root,
                    skill.provenance.checkout_remote,
                    skill.provenance.provider,
                    skill.provenance.source_label,
                    skill.provenance.confidence,
                    skill.provenance.evidence,
                )
                for skill in result.skills
            ],
        )
        access = {str(root.path): [a for a, _scope in root.access] for root in result.roots}
        contexts = {
            skill.identity_key: {"name": skill.name, "location": skill.realpath,
                                 "agents": sorted({a for p in skill.placements for a in access.get(p.host_root, [])})}
            for skill in result.skills
        }
        contexts.update({
            d.entry_path: {"name": d.entry, "location": d.entry_path, "missingTarget": d.target,
                           "agents": access.get(d.host_root, [])} for d in result.dangling
        })
        conn.executemany(
            "INSERT INTO health_issue(id, kind, identity_key, target, detail, fixable, context) VALUES (?,?,?,?,?,?,?)",
            [
                (issue.id, issue.kind, issue.identity_key, issue.target, issue.detail, int(issue.fixable),
                 json.dumps(contexts.get(issue.identity_key or issue.target, {})))
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


def counts(conn: sqlite3.Connection, claimed: set[str] | frozenset[str] = frozenset()) -> dict[str, int]:
    """Index totals, with user claims already subtracted from the warnings.

    The index keeps every scan finding (it is a projection of the files); a claim
    is a user annotation that answers "this one is accounted for", so the counts
    the UI shows are the finding counts minus the claimed ones.
    """
    keys = json.dumps(sorted(claimed))

    def one(sql: str, params: tuple = ()) -> int:
        row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    claimed_issues = one(
        "SELECT count(*) FROM health_issue WHERE kind = 'unclaimed_source' "
        "AND identity_key IN (SELECT value FROM json_each(?))",
        (keys,),
    )
    return {
        "skills": one("SELECT count(*) FROM skill"),
        "placements": one("SELECT count(*) FROM placement"),
        "dangling": one("SELECT count(*) FROM health_issue WHERE kind = 'dangling_link'"),
        "unclaimed": one(
            "SELECT count(*) FROM provenance WHERE confidence = 'none' "
            "AND identity_key NOT IN (SELECT value FROM json_each(?))",
            (keys,),
        ),
        "issues": one("SELECT count(*) FROM health_issue") - claimed_issues,
        "roots": one("SELECT count(*) FROM host_root WHERE exists_ = 1"),
    }


_ITEM_SQL = """
SELECT s.identity_key, s.name, s.dir_name, s.description, s.license, s.content_hash,
       s.bytes, s.lines, s.mtime, s.realpath, s.primary_kind,
       p.host, p.repo, p.path, p.ref, p.tree, p.installed_at, p.local_root, p.checkout_remote, p.provider, p.source_label, p.confidence, p.evidence,
       (SELECT json_group_array(DISTINCT json_object('agent', a.agent, 'scope', a.scope))
        FROM placement pl JOIN agent_access a ON pl.host_root = a.host_root
        WHERE pl.identity_key = s.identity_key) AS access,
       (SELECT group_concat(pl.kind) FROM placement pl WHERE pl.identity_key = s.identity_key) AS kinds,
       (SELECT count(*) FROM placement pl WHERE pl.identity_key = s.identity_key) AS placement_count,
       (SELECT count(DISTINCT pl.realpath) FROM placement pl WHERE pl.identity_key = s.identity_key) AS copy_count,
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
        "copy_count": row["copy_count"],
        "health": sorted({kind for kind in (row["issues"] or "").split(",") if kind}),
        "provenance": {
            "host": row["host"] if "host" in keys else "",
            "repo": row["repo"] if "repo" in keys else "",
            "path": row["path"] if "path" in keys else "",
            "ref": row["ref"] if "ref" in keys else "",
            "tree": (row["tree"] or "") if "tree" in keys else "",
            "installedAt": (row["installed_at"] or "") if "installed_at" in keys else "",
            "localRoot": row["local_root"] or "",
            "checkoutRemote": row["checkout_remote"] or "",
            "provider": row["provider"] or "",
            "sourceLabel": row["source_label"],
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
        return row["source_label"]
    return f"{host}/{repo}" if host else repo


def repository_for(provenance: sqlite3.Row | dict, asset: dict) -> dict[str, str]:
    """Resolve the same effective repository for the directory and the reader."""
    host, repo = provenance["host"], provenance["repo"]
    if asset.get("github"):
        host, repo = "github.com", asset["github"]["repo"]
    elif provenance["checkoutRemote"]:
        host, _, repo = provenance["checkoutRemote"].partition("/")
    elif provenance["provider"] in {"well-known", "mintlify"} or (not host and provenance["provider"]):
        name = provenance["sourceLabel"]
        return {"key": f"provider:{name}", "name": name, "location": "提供方"}
    if host and repo:
        host = host.lower()
        if host == "github.com":
            repo = "/".join(repo.strip("/").split("/")[:2]).removesuffix(".git")
        key = repo.lower() if host == "github.com" else repo
        return {"key": f"{host}/{key}", "name": repo, "location": host}
    local_root = provenance["localRoot"]
    if local_root:
        return {"key": f"local:{local_root}", "name": Path(local_root).name or local_root, "location": local_root}
    return {"key": "unassigned", "name": "未关联仓库", "location": ""}


def _source_groups(conn: sqlite3.Connection, clause: str, params: list, assets: dict) -> tuple[list[dict], list[str]]:
    rows = conn.execute(
        "SELECT s.identity_key, p.host, p.repo, p.local_root AS localRoot, p.checkout_remote AS checkoutRemote, "
        "p.provider, p.source_label AS sourceLabel FROM skill s "
        "JOIN provenance p USING(identity_key)" + clause + " ORDER BY s.name COLLATE NOCASE, s.identity_key",
        params,
    )
    groups: dict[str, dict] = {}
    identities = []
    for row in rows:
        key = row["identity_key"]
        identities.append(key)
        repo = repository_for(row, assets.get(key, {}))
        groups.setdefault(repo["key"], {**repo, "members": []})["members"].append(key)
    ordered = sorted(groups.values(), key=lambda g: (
        g["key"] == "unassigned", g["key"].startswith("provider:"), g["name"].casefold(), g["key"]
    ))
    return ordered, identities


def _page_offset(keys: list, limit: int, offset: int, focus: str = "") -> int:
    if focus and focus in keys:
        return keys.index(focus) // limit * limit
    return min(offset, max(0, (len(keys) - 1) // limit * limit))


def _ordered_items(conn: sqlite3.Connection, keys: list[str]) -> list[dict]:
    if not keys:
        return []
    rows = conn.execute(_ITEM_SQL + " WHERE s.identity_key IN (SELECT value FROM json_each(?))", [json.dumps(keys)])
    items = {row["identity_key"]: _row_to_item(row) for row in rows}
    return [items[key] for key in keys]


def _repository_page(
    conn: sqlite3.Connection, clause: str, params: list, assets: dict, repository: str, focus: str,
    limit: int, offset: int, layout: str, group_pages: dict[str, int],
) -> dict[str, Any]:
    groups, identities = _source_groups(conn, clause, params, assets)
    directory = [
        {"key": g["key"], "name": g["name"], "location": g["location"], "count": len(g["members"])} for g in groups
    ]
    result = {"repositories": directory, "limit": limit, "total": len(identities), "offset": 0}
    if layout == "flat":
        offset = _page_offset(identities, limit, offset, focus)
        return {**result, "offset": offset, "items": _ordered_items(conn, identities[offset:offset + limit])}

    if layout == "sources":
        # Small sets open together. Large sets start with a compact directory, keeping a linked skill in view.
        page_keys = []
        for group, entry in zip(groups, directory):
            members, key = group["members"], group["key"]
            requested = group_pages.get(key)
            if len(groups) == 1 and requested == 0:
                requested = None
            if requested is not None:
                start = _page_offset(members, limit, (requested - 1) * limit) if requested else None
            elif focus and focus in members:
                start = _page_offset(members, limit, 0, focus)
            elif key == repository or len(groups) == 1:
                start = _page_offset(members, limit, offset)
            elif len(identities) <= 12:
                start = 0
            else:
                start = None
            entry["page"] = 0 if start is None else start // limit + 1
            if start is not None:
                page_keys.extend(members[start:start + limit])
        return {**result, "items": _ordered_items(conn, page_keys)}

    # Older API callers request a single repository and paginate within it.
    active = next((g for g in groups if focus and focus in g["members"]), None)
    if active is None:
        active = next((g for g in groups if g["key"] == repository), groups[0] if groups else None)
    key = active["key"] if active else ""
    members = active["members"] if active else []
    offset = _page_offset(members, limit, 0 if repository and repository != key else offset, focus)
    return {**result, "activeRepository": key, "matchedTotal": len(identities), "total": len(members),
            "offset": offset, "items": _ordered_items(conn, members[offset:offset + limit])}


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
    category: str = "",
    category_index: dict[str, str] | None = None,
    by_repository: bool = False,
    layout: str = "",
    group_pages: dict[str, int] | None = None,
    repository: str = "",
    focus: str = "",
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
    claims = library.claims(annotations)
    if source:
        where.append(f"(p.source_label = ? OR (p.host || '/' || p.repo) = ? OR "
                     f"(p.confidence = 'none' AND s.identity_key IN ({annotated})))")
        params.extend((source, source, json.dumps([k for k, c in claims.items() if c["label"] == source])))
    claimed = sorted(claims)
    if confidence:
        if confidence == "claimed":
            where.append(f"s.identity_key IN ({annotated}) AND p.confidence = 'none'")
            params.append(json.dumps(claimed))
        elif confidence == "none":
            where.append(f"p.confidence = 'none' AND s.identity_key NOT IN ({annotated})")
            params.append(json.dumps(claimed))
        else:
            where.append("p.confidence = ?")
            params.append(confidence)
    if health:
        if health == "unclaimed_source":
            where.append(
                f"EXISTS (SELECT 1 FROM health_issue h WHERE h.identity_key = s.identity_key "
                f"AND h.kind = 'unclaimed_source') AND s.identity_key NOT IN ({annotated})"
            )
            params.append(json.dumps(claimed))
        else:
            where.append("EXISTS (SELECT 1 FROM health_issue h WHERE h.identity_key = s.identity_key AND h.kind = ?)")
            params.append(health)

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    category_data = {}
    if category_index is not None:
        matches = conn.execute("SELECT s.identity_key FROM skill s JOIN provenance p USING(identity_key)" + clause, params)
        counts = Counter(category_index[row[0]] for row in matches)
        category_data = {
            "categories": categories.directory(counts, category),
            "pendingCategories": sum(value == categories.PENDING for value in category_index.values()),
        }
        if category:
            clause += (" AND " if where else " WHERE ") + f"s.identity_key IN ({annotated})"
            params.append(json.dumps([key for key, value in category_index.items() if value == category]))
    if by_repository or layout in {"flat", "sources"}:
        result = _repository_page(conn, clause, params, annotations, repository, focus, limit, offset, layout, group_pages or {})
        return {**result, **category_data}
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
        **category_data,
        "limit": limit,
        "offset": offset,
    }


def _claimed_without_record(conn: sqlite3.Connection, assets: dict | None) -> set[str]:
    """Claimed identity keys whose scan verdict is still ``none``.

    A claim only fills a gap: when the machine already recorded an upstream, the
    record stays the reported provenance and the claim changes nothing here.
    """
    candidates = sorted(library.claims(assets or {}))
    if not candidates:
        return set()
    return {
        row[0]
        for row in conn.execute(
            "SELECT identity_key FROM provenance WHERE confidence = 'none' "
            "AND identity_key IN (SELECT value FROM json_each(?))",
            (json.dumps(candidates),),
        )
    }


def facets(conn: sqlite3.Connection, assets: dict | None = None) -> dict[str, list[dict[str, Any]]]:
    claimed = _claimed_without_record(conn, assets)
    hosts = [
        {"value": row["kind"], "label": row["kind"], "count": row["n"]}
        for row in conn.execute(
            "SELECT kind, count(DISTINCT identity_key) AS n FROM placement GROUP BY kind ORDER BY n DESC"
        )
    ]
    source_counts = dict(conn.execute(
        "SELECT source_label, count(*) FROM provenance WHERE source_label <> '' GROUP BY source_label"
    ))
    for key in claimed:
        label = library.claim_of(assets[key])["label"]
        source_counts[label] = source_counts.get(label, 0) + 1
    sources = [{"value": label, "label": label, "count": count} for label, count in
               sorted(source_counts.items(), key=lambda pair: (-pair[1], pair[0]))]
    confidence = []
    for row in conn.execute("SELECT confidence, count(*) AS n FROM provenance GROUP BY confidence ORDER BY n DESC"):
        count = int(row["n"]) - (len(claimed) if row["confidence"] == "none" else 0)
        if count > 0:
            confidence.append({"value": row["confidence"], "label": row["confidence"], "count": count})
    if claimed:
        confidence.append({"value": "claimed", "label": "claimed", "count": len(claimed)})
    health = []
    for row in conn.execute("SELECT kind, count(*) AS n FROM health_issue GROUP BY kind ORDER BY n DESC"):
        count = int(row["n"]) - (len(claimed) if row["kind"] == "unclaimed_source" else 0)
        if count > 0:
            health.append({"value": row["kind"], "label": row["kind"], "count": count})
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


def _issue_clause(kind: str, identity_key: str, claimed) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if identity_key:
        where.append("identity_key = ?")
        params.append(identity_key)
    if claimed:
        where.append("NOT (kind = 'unclaimed_source' AND identity_key IN (SELECT value FROM json_each(?)))")
        params.append(json.dumps(sorted(claimed)))
    return (" WHERE " + " AND ".join(where)) if where else "", params


def list_issues(
    conn: sqlite3.Connection,
    *,
    kind: str = "",
    identity_key: str = "",
    claimed: set[str] | frozenset[str] = frozenset(),
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clause, params = _issue_clause(kind, identity_key, claimed)
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
            **json.loads(row["context"]),
        }
        for row in rows
    ]


def issue_total(
    conn: sqlite3.Connection,
    *,
    kind: str = "",
    identity_key: str = "",
    claimed: set[str] | frozenset[str] = frozenset(),
) -> int:
    clause, params = _issue_clause(kind, identity_key, claimed)
    return int(conn.execute("SELECT count(*) FROM health_issue" + clause, params).fetchone()[0])


def has_installed_favorites(conn: sqlite3.Connection, assets: dict) -> bool:
    keys = [key for key, asset in assets.items() if asset.get("favorite")]
    return bool(conn.execute("SELECT 1 FROM skill WHERE identity_key IN (SELECT value FROM json_each(?)) LIMIT 1",
                             (json.dumps(keys),)).fetchone())


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
