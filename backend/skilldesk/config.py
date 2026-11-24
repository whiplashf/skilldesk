"""Paths and configuration.

Everything skilldesk owns lives in XDG locations so the tool never writes inside
a checked-out repository:

* config  ``$XDG_CONFIG_HOME/skilldesk``  (user authored, exportable)
* state   ``$XDG_STATE_HOME/skilldesk``   (machine index, rebuildable)
* cache   ``$XDG_CACHE_HOME/skilldesk``   (fetched skill bodies, translations)

Each of the three can be redirected with ``SKILLDESK_{CONFIG,STATE,CACHE}_DIR``,
which is what the test suite uses.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

APP = "skilldesk"


def home() -> Path:
    return Path(os.path.expanduser("~"))


def _xdg(env: str, fallback: Path) -> Path:
    value = os.environ.get(env, "").strip()
    return Path(os.path.expanduser(value)) if value else fallback


def config_dir() -> Path:
    override = os.environ.get("SKILLDESK_CONFIG_DIR", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return _xdg("XDG_CONFIG_HOME", home() / ".config") / APP


def state_dir() -> Path:
    override = os.environ.get("SKILLDESK_STATE_DIR", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return _xdg("XDG_STATE_HOME", home() / ".local" / "state") / APP


def cache_dir() -> Path:
    override = os.environ.get("SKILLDESK_CACHE_DIR", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return _xdg("XDG_CACHE_HOME", home() / ".cache") / APP


def index_path() -> Path:
    override = os.environ.get("SKILLDESK_INDEX", "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return state_dir() / "index.db"


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass(slots=True)
class Config:
    """User authored settings. Absent file means "all defaults"."""

    projects: list[str] = field(default_factory=list)
    extra_roots: list[dict] = field(default_factory=list)
    disabled_roots: list[str] = field(default_factory=list)


def _split_paths(raw: str) -> list[str]:
    parts: list[str] = []
    for chunk in raw.replace(",", os.pathsep).split(os.pathsep):
        chunk = chunk.strip()
        if chunk:
            parts.append(os.path.expanduser(chunk))
    return parts


def load_config(path: Path | None = None) -> Config:
    """Read ``config.json`` plus the ``SKILLDESK_PROJECTS`` environment override."""
    target = path or config_path()
    data: dict = {}
    if target.is_file():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            data = {}

    projects = [os.path.expanduser(str(item)) for item in data.get("projects", []) if str(item).strip()]
    env_projects = os.environ.get("SKILLDESK_PROJECTS", "")
    for item in _split_paths(env_projects):
        if item not in projects:
            projects.append(item)

    extra_roots = [item for item in data.get("extraRoots", []) if isinstance(item, dict) and item.get("path")]
    disabled = [os.path.expanduser(str(item)) for item in data.get("disabledRoots", []) if str(item).strip()]
    return Config(projects=projects, extra_roots=extra_roots, disabled_roots=disabled)
