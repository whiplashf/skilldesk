"""The registry: remote skills the product knows about, and what state each is in.

A registry entry is *coordinates only* — host, repository, the SKILL.md path, the
license and a one-line description. It never carries skill content, so a registry
file can live in a public repository without redistributing anyone's work; the
content is fetched on demand and cached locally (see ``installer``).

Sources are files: the shipped default list inside the install, plus one user
list in the config directory. Which ones are enabled is user state.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .config import config_dir
from .library import read_json, write_json

ENTRY_LIMIT = 500
REPO = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+$")
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def settings_path() -> Path:
    return config_dir() / "registry.json"


def shipped_default() -> Path:
    """``registry/default.json`` next to the package (shipped with the product)."""
    return Path(__file__).resolve().parents[2] / "registry" / "default.json"


def _settings() -> dict[str, Any]:
    payload = read_json(settings_path(), {})
    if not isinstance(payload, dict):
        payload = {}
    disabled = payload.get("disabled") if isinstance(payload.get("disabled"), list) else []
    custom = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    return {"disabled": [str(item) for item in disabled], "sources": custom}


def sources() -> list[dict[str, Any]]:
    """Every configured source, default first, with its enabled flag."""
    state = _settings()
    items: list[dict[str, Any]] = [
        {"id": "default", "kind": "builtin", "label": "内置清单", "path": str(shipped_default()), "enabled": "default" not in state["disabled"]}
    ]
    for index, source in enumerate(state["sources"]):
        if not isinstance(source, dict):
            continue
        items.append(
            {
                "id": str(source.get("id") or f"custom-{index + 1}"),
                "kind": "file",
                "label": str(source.get("label") or source.get("path") or ""),
                "path": str(source.get("path") or ""),
                "enabled": source.get("enabled", True) is not False,
            }
        )
    return items


def add_source(path: str, label: str = "") -> dict[str, Any]:
    target = str(Path(path).expanduser())
    state = _settings()
    for source in state["sources"]:
        if isinstance(source, dict) and str(source.get("path")) == target:
            return source
    entry = {"id": f"custom-{int(time.time() * 1000) % 10**9}", "kind": "file", "label": label or target, "path": target, "enabled": True}
    state["sources"].append(entry)
    write_json(settings_path(), {"disabled": state["disabled"], "sources": state["sources"]})
    return entry


def remove_source(source_id: str) -> bool:
    state = _settings()
    kept = [item for item in state["sources"] if isinstance(item, dict) and str(item.get("id")) != source_id]
    changed = len(kept) != len(state["sources"])
    if changed:
        write_json(settings_path(), {"disabled": state["disabled"], "sources": kept})
    return changed


def set_enabled(source_id: str, enabled: bool) -> bool:
    state = _settings()
    if source_id == "default":
        disabled = [item for item in state["disabled"] if item != "default"]
        if not enabled:
            disabled.append("default")
        write_json(settings_path(), {"disabled": disabled, "sources": state["sources"]})
        return True
    for source in state["sources"]:
        if isinstance(source, dict) and str(source.get("id")) == source_id:
            source["enabled"] = enabled
            write_json(settings_path(), {"disabled": state["disabled"], "sources": state["sources"]})
            return True
    return False


def normalise(raw: dict[str, Any]) -> dict[str, str] | None:
    """Validate one registry row; anything malformed is dropped, not guessed at."""
    host = str(raw.get("host") or "github.com").strip().lower()
    repo = str(raw.get("repo") or "").strip().strip("/").removesuffix(".git")
    path = str(raw.get("path") or "").strip().lstrip("/")
    if not REPO.fullmatch(repo) or any(segment in {"", ".", ".."} for segment in repo.split("/")):
        return None
    if not path.endswith("SKILL.md") or any(not SAFE_SEGMENT.fullmatch(segment) for segment in path.split("/")[:-1]):
        return None
    return {
        "host": host,
        "repo": repo,
        "path": path,
        "license": str(raw.get("license") or "").strip(),
        "description": str(raw.get("description") or "").strip()[:200],
        "branch": str(raw.get("branch") or "").strip(),
    }


def _read_source(path: str) -> list[dict[str, str]]:
    payload = read_json(Path(path).expanduser(), {})
    rows = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    found: list[dict[str, str]] = []
    for raw in rows[:ENTRY_LIMIT]:
        if not isinstance(raw, dict):
            continue
        entry = normalise(raw)
        if entry is not None:
            found.append(entry)
    return found


def entries() -> dict[str, Any]:
    """Every registry entry from every enabled source, deduplicated by coordinates."""
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    for source in sources():
        if not source["enabled"]:
            continue
        path = source["path"]
        if not Path(path).expanduser().is_file():
            errors.append({"source": source["id"], "error": "文件不存在", "path": path})
            continue
        try:
            rows = _read_source(path)
        except ValueError as error:
            errors.append({"source": source["id"], "error": str(error)[:120], "path": path})
            continue
        for row in rows:
            key = (row["host"], row["repo"].lower(), row["path"])
            if key not in seen:
                seen[key] = {**row, "source": source["id"]}
    return {"entries": sorted(seen.values(), key=lambda row: (row["host"], row["repo"], row["path"])), "errors": errors}


def find(host: str, repo: str, path: str) -> dict[str, Any] | None:
    for entry in entries()["entries"]:
        if entry["host"] == host and entry["repo"].lower() == repo.lower() and entry["path"] == path:
            return entry
    return None


def save_entry(entry: dict[str, str], *, source_id: str = "user") -> dict[str, str]:
    """Remember one hand-added coordinate so it survives a restart."""
    state = _settings()
    path = config_dir() / "registry-user.json"
    payload = read_json(path, {"entries": []})
    rows = payload.get("entries") if isinstance(payload, dict) else []
    rows = [row for row in rows if isinstance(row, dict)]
    key = (entry["host"], entry["repo"].lower(), entry["path"])
    rows = [row for row in rows if (str(row.get("host") or "github.com").lower(), str(row.get("repo") or "").lower(), str(row.get("path") or "")) != key]
    rows.append(entry)
    write_json(path, {"entries": rows})
    if not any(str(item.get("path")) == str(path) for item in state["sources"] if isinstance(item, dict)):
        state["sources"].append({"id": source_id, "kind": "file", "label": "本机添加", "path": str(path), "enabled": True})
        write_json(settings_path(), {"disabled": state["disabled"], "sources": state["sources"]})
    return entry


def dumps_default(entries_rows: list[dict[str, str]]) -> str:
    return json.dumps({"entries": entries_rows}, ensure_ascii=False, indent=2) + "\n"
