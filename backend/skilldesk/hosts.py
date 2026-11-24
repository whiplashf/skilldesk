"""Host roots — the directories different agent clients read skills from.

A root is a container: ``<root>/<entry>/SKILL.md``. Entries may be real
directories or symlinks into a store; both are recorded, and the entities they
point at are deduplicated by real path (see :mod:`skilldesk.scan`).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

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
    access: list[tuple[str, str]] = field(default_factory=list)

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
        (Path("/etc/codex/skills"), "codex", "codex (admin)"),
        (config_home / "opencode" / "skills", "opencode", "opencode"),
        (config_home / "opencode" / "skill", "opencode", "opencode (legacy)"),
        (h / ".opencode" / "skills", "opencode", "opencode (home)"),
        (h / ".opencode" / "skill", "opencode", "opencode (home, legacy)"),
    ]
    if codex_home := os.environ.get("CODEX_HOME"):
        roots.append((Path(codex_home).expanduser() / "skills", "codex", "codex ($CODEX_HOME)"))
    custom = os.environ.get("OPENCODE_CONFIG_DIR", "").strip()
    if custom:
        base = Path(os.path.expanduser(custom))
        roots.append((base / "skills", "opencode", "opencode ($OPENCODE_CONFIG_DIR)"))
        roots.append((base / "skill", "opencode", "opencode ($OPENCODE_CONFIG_DIR, legacy)"))
    return roots


def codex_config() -> Path:
    return Path(os.environ.get("CODEX_HOME") or home() / ".codex").expanduser() / "config.toml"


def enabled_codex_packages() -> list[Path]:
    config = codex_config()
    try:
        with config.open("rb") as stream:
            plugins = tomllib.load(stream).get("plugins", {})
    except (OSError, ValueError):
        return []
    if not isinstance(plugins, dict):
        return []
    packages = []
    for key, settings in plugins.items():
        match = re.fullmatch(r"([\w.-]+)@([\w.-]+)", key)
        if (
            match
            and all(part not in {".", ".."} for part in match.groups())
            and isinstance(settings, dict)
            and settings.get("enabled") is True
        ):
            name, market = match.groups()
            packages.append(config.parent / "plugins/cache" / market / name)
    return packages


def _codex_plugin_roots() -> list[tuple[Path, str, str]]:
    roots = []
    for package in enabled_codex_packages():
        manifests = list(package.glob("*/.codex-plugin/plugin.json"))
        # Multiple cached versions alone cannot identify the active one.
        if len(manifests) != 1:
            continue
        version_dir = manifests[0].parent.parent
        try:
            manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        declared = manifest.get("skills", "./skills") if isinstance(manifest, dict) else []
        if isinstance(declared, str):
            declared = [declared]
        if not isinstance(declared, list):
            continue
        for value in declared:
            if not isinstance(value, str):
                continue
            root = (version_dir / value).resolve()
            if root.is_relative_to(version_dir.resolve()) and root.is_dir():
                roots.append((root, "codex", f"Codex · {package.name}"))
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
    by_path: dict[str, HostRoot] = {}
    clients = {
        "agents": ("codex", "opencode"),
        "claude": ("claude", "opencode"),
        "opencode": ("opencode",),
        "codex": ("codex",),
    }
    candidates = _home_roots() + _codex_plugin_roots() + _project_roots(config) + _custom_roots(config)
    for path, kind, label in candidates:
        real = os.path.realpath(os.path.expanduser(str(path)))
        if real in disabled:
            continue
        root = by_path.setdefault(
            real, HostRoot(Path(real), kind, label, STORE_PRIORITY.get(kind, 9), exists=Path(real).is_dir())
        )
        location = path.parent.name.lstrip(".") if kind == "project" else kind
        scope = str(path.parent.parent.absolute()) if kind == "project" else ""
        agents = clients.get(location, ())
        if kind == "custom":
            agents = next(
                (
                    tuple(item.get("agents", ()))
                    for item in config.extra_roots
                    if Path(str(item["path"])).expanduser() == path and isinstance(item.get("agents"), list)
                ),
                (),
            )
        for agent in agents:
            if isinstance(agent, str) and agent and (agent, scope) not in root.access:
                root.access.append((agent, scope))
    roots = list(by_path.values())
    roots.sort(key=lambda root: (root.priority, root.kind, str(root.path)))
    return roots
