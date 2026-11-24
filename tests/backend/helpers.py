"""Helpers for building fake skill installations on disk."""
from __future__ import annotations

import json
from pathlib import Path


def write_skill(
    root: Path,
    name: str,
    *,
    description: str = "",
    body: str = "# Title\n\nBody paragraph.\n",
    extra_frontmatter: str = "",
) -> Path:
    """Create ``<root>/<name>/SKILL.md`` and return the directory."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    frontmatter = (
        "---\n"
        f"name: {name}\n"
        f"description: {description or f'about {name}'}\n"
        f"{extra_frontmatter}"
        "---\n\n"
        f"{body}"
    )
    (directory / "SKILL.md").write_text(frontmatter, encoding="utf-8")
    return directory


def write_lockfile(home: Path, entries: dict[str, dict]) -> Path:
    path = home / ".agents" / ".skill-lock.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 3, "skills": entries, "dismissed": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def lock_entry(repo: str, skill_path: str, host: str = "github.com", *, commit: str = "") -> dict:
    entry = {
        "source": repo,
        "sourceType": "github",
        "sourceUrl": f"https://{host}/{repo}.git",
        "skillPath": skill_path,
        "installedAt": "2026-01-01T00:00:00.000Z",
        "updatedAt": "2026-01-01T00:00:00.000Z",
    }
    if commit:
        entry["commit"] = commit
    return entry
