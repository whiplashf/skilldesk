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

from .config import Config, load_config
from .hosts import HostRoot, discover_roots
from .identity import (
    CONFIDENCE_ORDER,
    Provenance,
    identity_key,
    infer_provenance,
    load_lockfile,
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
    by_real: dict[str, SkillRecord] = {}
    dangling: list[DanglingEntry] = []

    for root in roots:
        if not root.enabled or not root.exists:
            continue
        try:
            entries = sorted(os.listdir(root.path))
        except OSError:
            continue
        for entry in entries:
            entry_path = os.path.join(str(root.path), entry)
            if os.path.islink(entry_path) and not os.path.exists(entry_path):
                try:
                    target = os.readlink(entry_path)
                except OSError:
                    target = ""
                dangling.append(
                    DanglingEntry(
                        host_root=str(root.path),
                        kind=root.kind,
                        entry=entry,
                        entry_path=entry_path,
                        target=target,
                    )
                )
                continue
            md_path = os.path.join(entry_path, "SKILL.md")
            if not os.path.isfile(md_path):
                continue
            real_md = os.path.realpath(md_path)
            real_dir = os.path.dirname(real_md)
            record = by_real.get(real_dir)
            if record is None:
                record = _read_entity(entry, real_dir, real_md, lock)
                if record is None:
                    continue
                by_real[real_dir] = record
            record.placements.append(
                Placement(
                    host_root=str(root.path),
                    kind=root.kind,
                    entry=entry,
                    entry_path=entry_path,
                    realpath=real_dir,
                    is_symlink=os.path.islink(entry_path),
                )
            )

    skills = _merge_by_identity(list(by_real.values()))
    return ScanResult(roots=roots, skills=skills, dangling=dangling, lockfile_entries=len(lock))


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
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
