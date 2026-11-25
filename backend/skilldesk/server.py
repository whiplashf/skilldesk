"""HTTP API and static frontend hosting.

The index is derived locally. User annotations are stored outside the index.
"""
from __future__ import annotations

import base64
import hmac
import mimetypes
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from . import __version__, library, prompts, translation, upstream
from . import index as index_mod
from .config import config_path, index_path, load_config
from .health import KINDS as HEALTH_KINDS
from .health import detect
from .identity import CONFIDENCE_LABEL
from .markdown import render, split_frontmatter
from .scan import MAX_SKILL_BYTES, input_stamp, read_body, scan

RESCAN_THROTTLE_SECONDS = 3.0
_rescan_lock = threading.Lock()
_last_rescan = 0.0


def refresh_if_stale(database: Path, *, force: bool = False) -> bool:
    global _last_rescan
    with _rescan_lock:
        if not force and index_mod.is_current(database):
            conn = index_mod.connect(database)
            try:
                stale = any(input_stamp(Path(row[0])) != row[1] for row in conn.execute("SELECT * FROM scan_input"))
            finally:
                conn.close()
            if not stale or time.monotonic() - _last_rescan < RESCAN_THROTTLE_SECONDS:
                return False
        result = scan(load_config())
        index_mod.rebuild(result, detect(result.skills, result.dangling), database)
        _last_rescan = time.monotonic()
    return True


def ensure_index(database: Path) -> None:
    if not index_mod.is_current(database):
        refresh_if_stale(database, force=True)


class GitHubSource(BaseModel):
    repo: str
    path: str


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    favorite: bool | None = None
    mine: bool | None = None
    github: GitHubSource | None = None


class AISettings(BaseModel):
    baseUrl: str
    model: str
    apiKey: str | None = None


class ProjectChange(BaseModel):
    path: str
    remove: bool = False


class SkillAction(BaseModel):
    identity_key: str
    force: bool = False


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
                if not path.resolve().is_relative_to(base.resolve()):
                    continue
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


def create_app(db_path: str | Path | None = None, *, remote_token: str | None = None) -> FastAPI:
    app = FastAPI(title="skilldesk", version=__version__, docs_url="/api/docs", redoc_url=None)
    app.include_router(prompts.router)
    database = Path(db_path) if db_path else index_path()
    ensure_index(database)
    write_token = secrets.token_urlsafe(32)

    @app.middleware("http")
    async def local_session(request: Request, call_next):
        if remote_token:
            auth = request.headers.get("authorization", "")
            try:
                password = base64.b64decode(auth.removeprefix("Basic "), validate=True).decode().split(":", 1)[1]
            except (ValueError, IndexError):
                password = ""
            if not auth.startswith("Basic ") or not hmac.compare_digest(password.encode(), remote_token.encode()):
                return JSONResponse({"detail": "请输入远程访问令牌作为密码"}, status_code=401,
                                    headers={"WWW-Authenticate": 'Basic realm="Skilldesk"'})
        elif request.url.hostname not in {"127.0.0.1", "localhost", "::1"} and not (
            request.client and request.client.host == "testclient" and request.url.hostname == "testserver"
        ):
            return JSONResponse({"detail": "仅允许本机访问"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if (origin and origin != f"{request.url.scheme}://{request.headers.get('host')}") or not hmac.compare_digest(
                request.headers.get("x-skilldesk-token", "").encode(), write_token.encode()
            ):
                return JSONResponse({"detail": "本次会话无效，请刷新页面后重试"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/session")
    def session():
        return {"token": write_token}

    def with_conn():
        return index_mod.connect(database)

    def get_installed(key: str):
        conn = with_conn()
        try:
            item = index_mod.get_skill(conn, key)
            if not item:
                raise HTTPException(404, "本机没有这项 skill")
            return item, library.resolved(library.stored(), conn)
        finally:
            conn.close()

    def decorate(item, annotations):
        asset = annotations["assets"].get(item["identity_key"], {})
        source = upstream.source_for(item, asset)
        item.update(repository=index_mod.repository_for(item["provenance"], asset),
                    favorite=bool(asset.get("favorite")), mine=bool(asset.get("mine")), upstream=source,
                    versionStatus=upstream.previous(item, source), libraryRevision=annotations["revision"])
        return item

    @app.get("/api/library")
    def user_library():
        conn = with_conn()
        try:
            return library.resolved(library.stored(), conn)
        finally:
            conn.close()

    @app.patch("/api/assets/{key:path}")
    def patch_asset(key: str, patch: AssetPatch, if_match: int = Header()):
        conn = with_conn()
        try:
            item = index_mod.get_skill(conn, key)
            if not item:
                raise HTTPException(404, "本机没有这项 skill")
            changes = patch.model_dump(exclude_unset=True)
            if changes.get("github"):
                changes["github"] = upstream.coordinates(changes["github"]["repo"], changes["github"]["path"])
            return decorate(item, library.update(conn, item, changes, if_match))
        except library.RevisionConflict:
            raise HTTPException(409, "用户库已在另一窗口更改，请刷新后重试")
        except ValueError as error:
            raise HTTPException(400, str(error))
        finally:
            conn.close()

    @app.post("/api/scan")
    def rescan():
        refresh_if_stale(database, force=True)
        return health()

    @app.get("/api/projects")
    def projects():
        saved = library.read_json(config_path(), {}).get("projects", [])
        return {"saved": saved, "effective": load_config().projects}

    @app.post("/api/projects")
    def change_project(change: ProjectChange):
        path = Path(change.path).expanduser()
        if not path.is_absolute() or (not change.remove and not path.is_dir()):
            raise HTTPException(400, "请输入本机已存在的项目绝对路径")
        with _rescan_lock:
            settings = library.read_json(config_path(), {})
            saved = settings.get("projects", [])
            if change.remove:
                settings["projects"] = [p for p in saved if Path(p).expanduser() != path]
            else:
                settings["projects"] = list(dict.fromkeys([*saved, str(path)]))
            library.write_json(config_path(), settings)
        refresh_if_stale(database, force=True)
        return projects()

    @app.get("/api/settings/ai")
    def ai_settings():
        return translation.public_settings()

    @app.put("/api/settings/ai")
    def save_ai(settings: AISettings):
        try:
            return translation.configure(settings.baseUrl.strip(), settings.model, settings.apiKey)
        except ValueError as error:
            raise HTTPException(400, str(error))

    @app.post("/api/ai/translate")
    def translate(action: SkillAction):
        item, _ = get_installed(action.identity_key)
        body = read_body(item["realpath"])
        if body is None:
            raise HTTPException(410, "正文已从本机移除")
        try:
            return translation.translate(render(split_frontmatter(body)[1]))
        except translation.NotConfigured as error:
            raise HTTPException(501, str(error))
        except (httpx.HTTPError, ValueError, LookupError, TypeError) as error:
            raise HTTPException(502, "翻译失败，请检查服务地址、模型与密钥后重试") from error

    @app.post("/api/check")
    def check_upstream(action: SkillAction):
        item, annotations = get_installed(action.identity_key)
        source = upstream.source_for(item, annotations["assets"].get(action.identity_key, {}))
        if not source or not source["path"]:
            raise HTTPException(400, "请先在来源中确认 GitHub 仓库与 SKILL.md 路径")
        try:
            return upstream.check(item, source, action.force)
        except ValueError as error:
            raise HTTPException(400, str(error))
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 429 or (
                error.response.status_code == 403 and error.response.headers.get("x-ratelimit-remaining") == "0"
            ):
                raise HTTPException(429, "GitHub 检查额度已用完，请稍后重试") from error
            raise HTTPException(502, "GitHub 未能返回版本信息，请核对仓库访问权限") from error
        except (httpx.HTTPError, OSError) as error:
            raise HTTPException(502, "检查失败，请稍后重试或检查 GitHub 访问权限及配额") from error

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
        agent: str = "",
        view: str = "all",
        by_repository: bool = False,
        repository: str = "",
        focus: str = "",
        host: str = "",
        source: str = "",
        confidence: str = "",
        health_kind: str = Query("", alias="health"),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        conn = with_conn()
        try:
            annotations = library.resolved(library.stored(), conn)
            result = index_mod.list_skills(
                conn,
                q=q, agent=agent, view=view, assets=annotations["assets"],
                by_repository=by_repository, repository=repository, focus=focus,
                host=host,
                source=source,
                confidence=confidence,
                health=health_kind,
                limit=limit,
                offset=offset,
            )
            for item in result["items"]:
                decorate(item, annotations)
            return result
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
    def api_file(key: str, rel: str = Query(..., min_length=1), raw: bool = False) -> dict[str, Any]:
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
        if size > (MAX_SKILL_BYTES if rel == "SKILL.md" else FILE_SIZE_LIMIT):
            raise HTTPException(status_code=413, detail="file too large")
        kind = _file_kind(path.name)
        if raw and kind == "markdown":
            kind = "text"
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
        return FileResponse(path, media_type=media_type, headers={
            "Content-Security-Policy": "sandbox; default-src 'none'", "X-Content-Type-Options": "nosniff",
        })

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
        skill, annotations = get_installed(key)
        body = read_body(skill["realpath"])
        if body is None:
            raise HTTPException(status_code=410, detail="skill body is gone from disk")
        frontmatter, markdown_body = split_frontmatter(body)
        skill["frontmatter"] = frontmatter
        skill["html"] = render(markdown_body)
        skill["confidenceLabel"] = CONFIDENCE_LABEL.get(skill["provenance"]["confidence"], "")
        return decorate(skill, annotations)

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
