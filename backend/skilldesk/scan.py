"""Local discovery: walk host roots, dedupe entities by real path.

One entity is one real directory containing ``SKILL.md``. The same entity can be
reached through several roots (the store directory plus symlinks in each agent
root), which is recorded as several *placements*, not several skills. Symlinks
that no longer resolve are collected separately — they are health problems, not
skills.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, config_path, load_config
from .hosts import HostRoot, codex_config, discover_roots, enabled_codex_packages
from .identity import (
    CONFIDENCE_ORDER,
    Provenance,
    identity_key,
    infer_provenance,
    load_lockfile,
    lockfile_paths,
)
from .markdown import clean_description, split_frontmatter

MAX_SKILL_BYTES = 8 * 1024 * 1024


@dataclass(slots=True)
class Placement:
    """One way of reaching an entity: a root plus the entry name inside it."""

    host_root: str
    kind: str
    entry: str
    entry_path: str
    realpath: str
    is_symlink: bool


@dataclass(slots=True)
class DanglingEntry:
    """An entry in a host root that is a symlink to something that does not exist."""

    host_root: str
    kind: str
    entry: str
    entry_path: str
    target: str


@dataclass(slots=True)
class SkillRecord:
    identity_key: str
    name: str
    dir_name: str
    description: str
    license: str
    content_hash: str
    nbytes: int
    lines: int
    mtime: int
    realpath: str
    provenance: Provenance
    placements: list[Placement] = field(default_factory=list)

    @property
    def primary_kind(self) -> str:
        if not self.placements:
            return ""
        return min(self.placements, key=lambda placement: placement.kind).kind


@dataclass(slots=True)
class ScanResult:
    roots: list[HostRoot]
    skills: list[SkillRecord]
    dangling: list[DanglingEntry]
    lockfile_entries: int = 0
    inputs: dict[str, str] = field(default_factory=dict)


def _read_entity(dir_name: str, real_dir: str, real_md: str, lock: dict[str, dict]) -> SkillRecord | None:
    try:
        size = os.path.getsize(real_md)
        if size > MAX_SKILL_BYTES:
            return None
        with open(real_md, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return None

    frontmatter, _body = split_frontmatter(text)
    provenance = infer_provenance(dir_name, real_dir, frontmatter, lock)
    description = clean_description(" ".join(str(frontmatter.get("description", "")).split()))
    return SkillRecord(
        identity_key=identity_key(provenance, real_dir),
        name=(frontmatter.get("name") or dir_name).strip() or dir_name,
        dir_name=dir_name,
        description=description,
        license=str(frontmatter.get("license") or "").strip(),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        nbytes=size,
        lines=text.count("\n") + 1,
        mtime=int(os.path.getmtime(real_md)),
        realpath=real_dir,
        provenance=provenance,
    )


def _merge_by_identity(entities: list[SkillRecord]) -> list[SkillRecord]:
    """Collapse entities that resolve to the same identity key into one skill."""
    merged: dict[str, SkillRecord] = {}
    for record in entities:
        existing = merged.get(record.identity_key)
        if existing is None:
            merged[record.identity_key] = record
            continue
        existing.placements.extend(record.placements)
        # Prefer the placement in the store: its file is the one that would be edited.
        if CONFIDENCE_ORDER.get(record.provenance.confidence, 9) < CONFIDENCE_ORDER.get(
            existing.provenance.confidence, 9
        ):
            existing.provenance = record.provenance
        if record.primary_kind == "agents" and existing.primary_kind != "agents":
            existing.realpath = record.realpath
            existing.dir_name = record.dir_name
    for record in merged.values():
        record.placements.sort(key=lambda placement: (placement.kind, placement.entry_path))
    return sorted(merged.values(), key=lambda record: (record.name.lower(), record.identity_key))


def scan(config: Config | None = None) -> ScanResult:
    """Discover every skill reachable from the configured host roots."""
    config = config or load_config()
    roots = discover_roots(config)
    lock = load_lockfile()
    locks_by_root = {root.path: lock for root in roots if root.kind == "agents"}
    by_real: dict[str, SkillRecord] = {}
    dangling: list[DanglingEntry] = []

    inputs: dict[str, str] = {}

    def watch(path: Path) -> None:
        inputs[str(path)] = input_stamp(path)

    lock_count = len(lock)
    for project in config.projects:
        project_dir = Path(project).expanduser()
        project_lock = project_dir / "skills-lock.json"
        watch(project_lock)
        entries = load_lockfile([project_lock])
        locks_by_root.setdefault((project_dir / ".agents/skills").resolve(), entries)
        lock_count += len(entries)

    def visit(root: HostRoot, directory: Path, ancestors: set[Path]) -> None:
        watch(directory)
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for path in entries:
            if path.name in {"node_modules", "__pycache__"} or (
                path.name.startswith(".") and not (root.kind == "codex" and path.name == ".system")
            ):
                continue
            relative = path.relative_to(root.path).as_posix()
            if path.is_symlink():
                watch(path)
                if not path.exists():
                    try:
                        target = os.readlink(path)
                    except OSError:
                        target = ""
                    dangling.append(DanglingEntry(str(root.path), root.kind, relative, str(path), target))
                    continue
            if not path.is_dir():
                continue
            try:
                real_dir = path.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if real_dir in ancestors:
                continue
            md_path = real_dir / "SKILL.md"
            if not md_path.is_file():
                if not path.is_symlink() or real_dir.is_relative_to(root.path):
                    visit(root, path, ancestors | {real_dir})
                continue
            if md_path.is_symlink() and not md_path.resolve().is_relative_to(real_dir):
                continue
            watch(md_path)
            watch(real_dir / "skill-release.json")
            key = str(real_dir)
            if key not in by_real:
                # Installer records belong to direct entries in their corresponding store.
                entries_in_lock = locks_by_root.get(root.path, {})
                local_lock = {path.name: entries_in_lock[path.name]} if (
                    path.parent == root.path and path.name in entries_in_lock
                ) else {}
                record = _read_entity(path.name, key, str(md_path), local_lock)
                if record is None:
                    continue
                by_real[key] = record
            by_real[key].placements.append(Placement(
                str(root.path), root.kind, relative, str(path), key, path.is_symlink(),
            ))

    for path in [config_path(), codex_config(), *enabled_codex_packages(), *lockfile_paths()]:
        watch(path)
    for root in roots:
        visit(root, root.path, {root.path})

    skills = _merge_by_identity(list(by_real.values()))
    return ScanResult(roots, skills, dangling, lock_count, inputs)


def input_stamp(path: Path) -> str:
    try:
        stat = path.stat()
        return f"{stat.st_dev}:{stat.st_ino}:{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return "-"


def count_root_entries(roots: list[HostRoot]) -> int:
    total = 0
    for root in roots:
        if not root.exists:
            continue
        try:
            total += len(os.listdir(root.path))
        except OSError:
            continue
    return total


def read_body(realpath: str) -> str | None:
    """Raw SKILL.md text of an entity, read at request time (never cached stale)."""
    path = Path(realpath) / "SKILL.md"
    try:
        path = path.resolve(strict=True)
        if not path.is_relative_to(Path(realpath)) or path.stat().st_size > MAX_SKILL_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except (OSError, RuntimeError):
        return None
