"""Health detection — structural problems in the local placements.

Health answers "is this copy sane", not "is this copy up to date": upstream
drift is a separate concept (see GLOSSARY.md) and arrives in M4.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass

from .scan import DanglingEntry, SkillRecord

KINDS: dict[str, dict] = {
    "dangling_link": {
        "label": "悬空软链",
        "severity": "error",
        "fixable": True,
        "description": "宿主根里的软链指向一个不存在的路径。",
    },
    "unclaimed_source": {
        "label": "待认领来源",
        "severity": "warning",
        "fixable": True,
        "description": "没有任何机器记录能确定上游来源，需要人工认领。",
    },
    "duplicate_content": {
        "label": "重复实体",
        "severity": "info",
        "fixable": False,
        "description": "多个 skill 实体的 SKILL.md 内容完全相同。",
    },
}


@dataclass(slots=True)
class Issue:
    id: str
    kind: str
    identity_key: str
    target: str
    detail: str
    fixable: bool

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "identity_key": self.identity_key,
            "target": self.target,
            "detail": self.detail,
            "fixable": self.fixable,
        }


def _issue_id(kind: str, target: str) -> str:
    return hashlib.sha256(f"{kind}\x00{target}".encode()).hexdigest()[:16]


def _issue(kind: str, identity_key: str, target: str, detail: str) -> Issue:
    return Issue(
        id=_issue_id(kind, target),
        kind=kind,
        identity_key=identity_key,
        target=target,
        detail=detail,
        fixable=bool(KINDS.get(kind, {}).get("fixable", False)),
    )


def detect(skills: list[SkillRecord], dangling: list[DanglingEntry]) -> list[Issue]:
    """All health issues for one scan, in a stable order."""
    issues: list[Issue] = []

    for entry in dangling:
        issues.append(
            _issue(
                "dangling_link",
                "",
                entry.entry_path,
                f"{entry.kind} 根里的 {entry.entry} 指向不存在的 {entry.target or '(未知目标)'}",
            )
        )

    for skill in skills:
        if skill.provenance.confidence == "none":
            issues.append(
                _issue(
                    "unclaimed_source",
                    skill.identity_key,
                    skill.identity_key,
                    f"{skill.dir_name} 没有可核实的上游记录",
                )
            )

    by_hash: dict[str, list[SkillRecord]] = defaultdict(list)
    for skill in skills:
        by_hash[skill.content_hash].append(skill)
    for content_hash, group in by_hash.items():
        if len(group) < 2:
            continue
        names = "、".join(sorted(skill.dir_name for skill in group))
        for skill in group:
            issues.append(
                _issue(
                    "duplicate_content",
                    skill.identity_key,
                    f"{content_hash}:{skill.identity_key}",
                    f"与 {names} 内容相同",
                )
            )

    issues.sort(key=lambda issue: (issue.kind, issue.target))
    return issues
