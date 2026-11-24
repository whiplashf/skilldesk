"""HTTP API and static frontend hosting.

Read-only in M1: every endpoint is a GET. Write endpoints (library edits,
import, install) arrive with the user library in M2/M3.
"""
from __future__ import annotations

import mimetypes
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import index as index_mod
from .config import index_path, load_config
from .health import KINDS as HEALTH_KINDS
from .health import detect
from .identity import CONFIDENCE_LABEL, lockfile_paths
from .markdown import render, split_frontmatter
from .scan import read_body, scan

RESCAN_THROTTLE_SECONDS = 3.0
_rescan_lock = threading.Lock()
_last_rescan = 0.0


def _newest_input(conn) -> int:
    """Newest mtime among everything a scan depends on (cheap: only stats)."""
    newest = 0
    for row in conn.execute("SELECT realpath FROM skill"):
        try:
            newest = max(newest, int(os.path.getmtime(os.path.join(row[0], "SKILL.md"))))
        except OSError:
            continue
    for row in conn.execute("SELECT path FROM host_root WHERE exists_ = 1"):
        try:
            newest = max(newest, int(os.path.getmtime(row[0])))
        except OSError:
            continue
    for path in lockfile_paths():
        try:
            newest = max(newest, int(os.path.getmtime(path)))
        except OSError:
            continue
    return newest


def refresh_if_stale(database: Path) -> bool:
    """Rebuild the index when the filesystem changed since the last scan."""
    global _last_rescan
    if not database.is_file():
        return False
    conn = index_mod.connect(database)
    try:
        scanned_at = int(index_mod.meta(conn).get("scanned_at", "0") or 0)
        stale = _newest_input(conn) > scanned_at
    finally:
        conn.close()
    if not stale:
        return False
    with _rescan_lock:
        if time.time() - _last_rescan < RESCAN_THROTTLE_SECONDS:
            return False
        result = scan(load_config())
        index_mod.rebuild(result, detect(result.skills, result.dangling), database)
        _last_rescan = time.time()
    return True


def ensure_index(database: Path) -> None:
    if database.is_file():
        return
    result = scan(load_config())
    index_mod.rebuild(result, detect(result.skills, result.dangling), database)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
FILE_SIZE_LIMIT = 2 * 1024 * 1024
MAX_WALK_DEPTH = 4
MAX_FILES = 200
TEXT_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".json",
    ".jsonc",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".py",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".sh",
    ".bash",
    ".zsh",
    ".css",
    ".html",
    ".csv",
    ".sql",
    ".go",
    ".rs",
    ".java",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".lua",
    ".r",
    ".jl",
    ".tf",
    ".hcl",
    ".proto",
    ".graphql",
    ".xml",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}


def _conn():
    return index_mod.connect(index_path())


def _resolve_inside(root: str, relative: str) -> Path:
    """Resolve ``relative`` under ``root``, refusing escapes and absolute input."""
    base = Path(root).resolve()
    candidate = (base / relative).resolve()
    if base != candidate and base not in candidate.parents:
        raise HTTPException(status_code=400, detail="path escapes the skill directory")
    return candidate


def _list_files(realpath: str) -> list[dict[str, Any]]:
    base = Path(realpath)
    found: list[dict[str, Any]] = []
    if not base.is_dir():
        return found
    for current, dirs, files in os.walk(base):
        depth = len(Path(current).relative_to(base).parts)
        if depth >= MAX_WALK_DEPTH:
            dirs[:] = []
        dirs[:] = sorted(item for item in dirs if not item.startswith("."))
        for name in sorted(files):
            if name.startswith(".") or name == "SKILL.md":
                continue
            path = Path(current) / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            found.append(
                {
                    "rel": str(path.relative_to(base)).replace(os.sep, "/"),
                    "name": name,
                    "size": size,
                    "kind": _file_kind(name),
                }
            )
            if len(found) >= MAX_FILES:
                return found
    return found


def _file_kind(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in (".md", ".markdown"):
        return "markdown"
    if suffix in TEXT_SUFFIXES:
        return "text"
    return "binary"


def create_app(db_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="skilldesk", version=__version__, docs_url="/api/docs", redoc_url=None)
    database = Path(db_path) if db_path else index_path()
    ensure_index(database)

    def with_conn():
        return index_mod.connect(database)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        rescanned = refresh_if_stale(database)
        conn = with_conn()
        try:
            meta = index_mod.meta(conn)
            for key in ("scanned_at", "skills", "placements", "dangling", "issues", "lockfile_entries"):
                if key in meta:
                    meta[key] = int(meta[key])
            return {
                "ok": True,
                "version": __version__,
                "rescanned": rescanned,
                "meta": meta,
                "counts": index_mod.counts(conn),
            }
        finally:
            conn.close()

    @app.get("/api/index")
    def api_index(
        q: str = "",
        host: str = "",
        source: str = "",
        confidence: str = "",
        health_kind: str = Query("", alias="health"),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        conn = with_conn()
        try:
            return index_mod.list_skills(
                conn,
                q=q,
                host=host,
                source=source,
                confidence=confidence,
                health=health_kind,
                limit=limit,
                offset=offset,
            )
        finally:
            conn.close()

    @app.get("/api/facets")
    def api_facets() -> dict[str, Any]:
        conn = with_conn()
        try:
            data = index_mod.facets(conn)
        finally:
            conn.close()
        data["confidenceLabels"] = CONFIDENCE_LABEL
        data["healthLabels"] = {key: value["label"] for key, value in HEALTH_KINDS.items()}
        return data

    @app.get("/api/roots")
    def api_roots() -> dict[str, Any]:
        conn = with_conn()
        try:
            return {"items": index_mod.list_roots(conn)}
        finally:
            conn.close()

    @app.get("/api/issues")
    def api_issues(
        kind: str = "",
        identity_key: str = "",
        limit: int = Query(500, ge=1, le=2000),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        conn = with_conn()
        try:
            items = index_mod.list_issues(conn, kind=kind, identity_key=identity_key, limit=limit, offset=offset)
            total = int(conn.execute("SELECT count(*) FROM health_issue").fetchone()[0])
        finally:
            conn.close()
        return {"items": items, "total": total, "limit": limit, "offset": offset, "kinds": HEALTH_KINDS}

    @app.get("/api/skill/{key:path}/file")
    def api_file(key: str, rel: str = Query(..., min_length=1)) -> dict[str, Any]:
        conn = with_conn()
        try:
            skill = index_mod.get_skill(conn, key)
        finally:
            conn.close()
        if skill is None:
            raise HTTPException(status_code=404, detail="unknown skill")
        path = _resolve_inside(skill["realpath"], rel)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="unknown file")
        size = path.stat().st_size
        if size > FILE_SIZE_LIMIT:
            raise HTTPException(status_code=413, detail="file too large")
        kind = _file_kind(path.name)
        payload: dict[str, Any] = {
            "rel": rel,
            "name": path.name,
            "size": size,
            "kind": kind,
            "path": str(path),
        }
        if kind == "markdown":
            text = path.read_text(encoding="utf-8", errors="replace")
            _frontmatter, body = split_frontmatter(text)
            payload["html"] = render(body)
        elif kind == "text":
            payload["text"] = path.read_text(encoding="utf-8", errors="replace")
        elif kind in ("image", "binary"):
            payload["url"] = f"/api/skill/{quote(key, safe='')}/asset?rel={quote(rel, safe='')}"
        return payload

    @app.get("/api/skill/{key:path}/asset")
    def api_asset(key: str, rel: str = Query(..., min_length=1)) -> FileResponse:
        conn = with_conn()
        try:
            skill = index_mod.get_skill(conn, key)
        finally:
            conn.close()
        if skill is None:
            raise HTTPException(status_code=404, detail="unknown skill")
        path = _resolve_inside(skill["realpath"], rel)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="unknown file")
        if path.stat().st_size > FILE_SIZE_LIMIT:
            raise HTTPException(status_code=413, detail="file too large")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type)

    @app.get("/api/skill/{key:path}/files")
    def api_files(key: str) -> dict[str, Any]:
        conn = with_conn()
        try:
            skill = index_mod.get_skill(conn, key)
        finally:
            conn.close()
        if skill is None:
            raise HTTPException(status_code=404, detail="unknown skill")
        return {"items": _list_files(skill["realpath"])}

    @app.get("/api/skill/{key:path}")
    def api_skill(key: str) -> dict[str, Any]:
        conn = with_conn()
        try:
            skill = index_mod.get_skill(conn, key)
        finally:
            conn.close()
        if skill is None:
            raise HTTPException(status_code=404, detail="unknown skill")
        body = read_body(skill["realpath"])
        if body is None:
            raise HTTPException(status_code=410, detail="skill body is gone from disk")
        frontmatter, markdown_body = split_frontmatter(body)
        skill["frontmatter"] = frontmatter
        skill["html"] = render(markdown_body)
        skill["confidenceLabel"] = CONFIDENCE_LABEL.get(skill["provenance"]["confidence"], "")
        return skill

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
    else:

        @app.get("/")
        def placeholder() -> JSONResponse:
            return JSONResponse(
                {
                    "ok": True,
                    "message": "skilldesk API is running; the frontend is not built yet.",
                    "hint": "cd frontend && pnpm install && pnpm build",
                    "api": ["/api/health", "/api/index", "/api/facets", "/api/issues", "/api/docs"],
                }
            )

    return app
