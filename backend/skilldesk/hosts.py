"""Host roots — the directories different agent clients read skills from.

A root is a container: ``<root>/<entry>/SKILL.md``. Entries may be real
directories or symlinks into a store; both are recorded, and the entities they
point at are deduplicated by real path (see :mod:`skilldesk.scan`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import Config, home

# Lower number wins when several roots expose the same entity: the store
# (``~/.agents/skills``) is the physical home, everything else is usually a link.
STORE_PRIORITY = {"agents": 0, "project": 1, "codex": 2, "claude": 3, "opencode": 4, "custom": 5}


@dataclass(slots=True)
class HostRoot:
    path: Path
    kind: str
    label: str
    priority: int
    enabled: bool = True
    exists: bool = False

    @property
    def key(self) -> str:
        return str(self.path)


def _home_roots() -> list[tuple[Path, str, str]]:
    h = home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or (h / ".config"))
    roots: list[tuple[Path, str, str]] = [
        (h / ".agents" / "skills", "agents", "agents"),
        (h / ".claude" / "skills", "claude", "claude"),
        (h / ".codex" / "skills", "codex", "codex"),
        (config_home / "opencode" / "skills", "opencode", "opencode"),
        (config_home / "opencode" / "skill", "opencode", "opencode (legacy)"),
        (h / ".opencode" / "skills", "opencode", "opencode (home)"),
        (h / ".opencode" / "skill", "opencode", "opencode (home, legacy)"),
    ]
    custom = os.environ.get("OPENCODE_CONFIG_DIR", "").strip()
    if custom:
        base = Path(os.path.expanduser(custom))
        roots.append((base / "skills", "opencode", "opencode ($OPENCODE_CONFIG_DIR)"))
        roots.append((base / "skill", "opencode", "opencode ($OPENCODE_CONFIG_DIR, legacy)"))
    return roots


def _project_roots(config: Config) -> list[tuple[Path, str, str]]:
    roots: list[tuple[Path, str, str]] = []
    for project in config.projects:
        base = Path(os.path.expanduser(project))
        for relative, kind in (
            (".agents/skills", "project"),
            (".claude/skills", "project"),
            (".opencode/skills", "project"),
        ):
            roots.append((base / relative, kind, f"project: {base.name}"))
    return roots


def _custom_roots(config: Config) -> list[tuple[Path, str, str]]:
    roots: list[tuple[Path, str, str]] = []
    for item in config.extra_roots:
        path = Path(os.path.expanduser(str(item["path"])))
        roots.append((path, "custom", str(item.get("label") or path.name)))
    return roots


def discover_roots(config: Config) -> list[HostRoot]:
    """Every candidate root, deduplicated by real path and ordered by priority."""
    disabled = {os.path.realpath(os.path.expanduser(item)) for item in config.disabled_roots}
    seen: set[str] = set()
    roots: list[HostRoot] = []
    candidates = _home_roots() + _project_roots(config) + _custom_roots(config)
    for path, kind, label in candidates:
        real = os.path.realpath(os.path.expanduser(str(path)))
        if real in seen or real in disabled:
            continue
        seen.add(real)
        roots.append(
            HostRoot(
                path=Path(real),
                kind=kind,
                label=label,
                priority=STORE_PRIORITY.get(kind, 9),
                exists=Path(real).is_dir(),
            )
        )
    roots.sort(key=lambda root: (root.priority, root.kind, str(root.path)))
    return roots
