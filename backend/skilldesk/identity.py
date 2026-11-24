"""Provenance inference and identity keys.

A skill's identity has to survive reinstalls, renames, and being reachable
through several host roots at once. We therefore key on the upstream identity
when it is known — ``src:<host>/<repo>@<path>`` — and fall back to a fingerprint
of the real path, ``loc:<sha256[:16]>``.

Confidence is never guessed: ``recorded`` comes from a machine record (the
``skills`` CLI lockfile), ``declared`` from the skill itself (``skill-release.json``
or frontmatter), and everything else stays ``none`` so the UI can ask the user to
claim it instead of inventing an upstream.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import home

RECORDED = "recorded"
DECLARED = "declared"
NONE = "none"

CONFIDENCE_LABEL = {RECORDED: "已记录", DECLARED: "已声明", NONE: "待认领"}
CONFIDENCE_ORDER = {RECORDED: 0, DECLARED: 1, NONE: 2}

_HOST_RE = re.compile(r"^[a-z0-9-]+(?:\.[a-z0-9-]+)+(?::\d+)?$", re.IGNORECASE)
_METADATA_KEYS = ("repository", "repo", "homepage", "url", "source")


@dataclass(slots=True)
class Provenance:
    """Where a skill came from, and how sure we are about it."""

    host: str = ""
    repo: str = ""
    path: str = ""
    ref: str = ""
    confidence: str = NONE
    evidence: str = ""
    tree: str = ""
    local_root: str = ""
    checkout_remote: str = ""
    provider: str = ""

    @property
    def label(self) -> str:
        """Human facing ``host/repo`` (``repo`` alone when the host is unknown)."""
        if not self.host and not self.repo:
            return ""
        return f"{self.host}/{self.repo}" if self.host else self.repo

    @property
    def is_known(self) -> bool:
        return bool(self.host and self.repo)


def clean_path(value: str) -> str:
    """Normalise a repo-relative path: posix separators, no leading ``./`` or ``/``."""
    text = (value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def normalize_source(value: str) -> tuple[str, str] | None:
    """Split a git URL or ``host/path`` label into ``(host, repo_path)``.

    Nested groups matter: ``https://git.example.com/group/subgroup/plugin.git``
    has the repo path ``group/subgroup/plugin`` — taking only two
    segments would silently merge five distinct plugins into one repository.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.startswith("git@") and ":" in raw:
        host_part, _, rest = raw[4:].partition(":")
        raw = f"https://{host_part}/{rest}"

    if "://" in raw:
        try:
            parsed = urlparse(raw)
            host = (parsed.hostname or "").lower()
            if parsed.port and (parsed.scheme, parsed.port) not in {("https", 443), ("http", 80), ("ssh", 22)}:
                host = f"{host}:{parsed.port}"
        except ValueError:
            return None
        candidate = parsed.path
    else:
        parts = [part for part in raw.strip("/").split("/") if part]
        if len(parts) < 2 or not _HOST_RE.match(parts[0]):
            return None
        host = parts[0].lower()
        candidate = "/".join(parts[1:])

    segments = [segment for segment in candidate.strip("/").split("/") if segment]
    if not host or len(segments) < 2:
        return None
    segments[-1] = segments[-1].removesuffix(".git")
    if not segments[-1]:
        return None
    return host, "/".join(segments)


def lockfile_paths() -> list[Path]:
    """Candidate locations of the ``skills`` CLI lockfile, most specific first."""
    override = os.environ.get("SKILLDESK_LOCKFILE", "").strip()
    if override:
        return [Path(os.path.expanduser(override))]
    paths = [home() / ".agents" / ".skill-lock.json"]
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    if state_home:
        paths.append(Path(os.path.expanduser(state_home)) / "skills" / ".skill-lock.json")
    paths.append(home() / ".local" / "state" / "skills" / ".skill-lock.json")
    return paths


def load_lockfile(paths: list[Path] | None = None) -> dict[str, dict]:
    """Installed skill name → lock entry. Missing or unreadable means ``{}``."""
    for path in lockfile_paths() if paths is None else paths:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        skills = payload.get("skills") if isinstance(payload, dict) else None
        if isinstance(skills, dict):
            return {str(name): entry for name, entry in skills.items() if isinstance(entry, dict)}
    return {}


def _from_frontmatter(frontmatter: dict) -> str:
    for key in ("source", "repository", "homepage"):
        value = (frontmatter.get(key) or "").strip()
        if value.startswith(("http://", "https://", "git@")):
            return value
    metadata = frontmatter.get("metadata") or ""
    if isinstance(metadata, str) and metadata:
        for key in _METADATA_KEYS:
            match = re.search(rf"(?m)^\s*{key}\s*:\s*[\"']?([^\s\"']+)", metadata)
            if match and match.group(1).startswith(("http://", "https://", "git@")):
                return match.group(1)
    return ""


def infer_provenance(dir_name: str, real_dir: str, frontmatter: dict, lock: dict[str, dict]) -> Provenance:
    """Best-effort, confidence-tagged upstream identity for one installed skill."""
    names = [dir_name]
    declared = (frontmatter.get("name") or "").strip()
    if declared and declared != dir_name:
        names.append(declared)

    local_source = None
    for name in names:
        entry = lock.get(name)
        if not entry:
            continue
        source = str(entry.get("sourceUrl") or entry.get("source") or "")
        if entry.get("sourceType") == "local":
            local_source = _local_source_root(source)
            continue
        if entry.get("sourceType") == "github" and re.fullmatch(r"[\w.-]+/[\w.-]+", source):
            source = "https://github.com/" + source
        normalized = normalize_source(source)
        if not normalized:
            continue
        host, repo = normalized
        digest = str(entry.get("skillFolderHash", "")).lower()
        return Provenance(
            host=host,
            repo=repo,
            path=clean_path(str(entry.get("skillPath") or "")),
            ref=str(entry.get("commit") or ""),
            confidence=RECORDED,
            evidence="lockfile",
            tree=digest if re.fullmatch(r"[0-9a-f]{40}", digest) else "",
            provider=str(entry.get("sourceType") or ""),
        )

    # A checked-out skill supplies both a repository and its exact folder.
    directory = Path(real_dir)
    checkout = _checkout_root(directory)
    if checkout and (not local_source or checkout == local_source):
        try:
            tracked_path = (directory / "SKILL.md").relative_to(checkout).as_posix()
            _git(checkout, "cat-file", "-e", "HEAD:" + tracked_path)
            origin = normalize_source(_git(checkout, "config", "--get", "remote.origin.url"))
            if origin:
                return Provenance(origin[0], origin[1], tracked_path,
                                  _git(checkout, "rev-parse", "HEAD"), RECORDED, "git checkout", local_root=str(checkout))
        except (OSError, subprocess.SubprocessError):
            pass

    release = directory / "skill-release.json"
    if release.is_file():
        try:
            payload = json.loads(release.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        source = payload.get("source") if isinstance(payload, dict) else None
        repository = str((source or {}).get("repository") or "") if isinstance(source, dict) else ""
        normalized = normalize_source(repository)
        if normalized:
            path = clean_path(str(source.get("skillPath") or source.get("path") or ""))
            return Provenance(normalized[0], normalized[1], path, str(source.get("commit") or ""),
                              DECLARED, "skill-release.json")

    declared_source = _from_frontmatter(frontmatter)
    normalized = normalize_source(declared_source)
    if normalized:
        return Provenance(host=normalized[0], repo=normalized[1], confidence=DECLARED, evidence="frontmatter")

    root = local_source or checkout
    if root:
        # An untracked document belongs to the checkout, but has no published revision to compare.
        try:
            remote = normalize_source(_git(root, "config", "--get", "remote.origin.url"))
        except (OSError, subprocess.SubprocessError):
            remote = None
        return Provenance(local_root=str(root), checkout_remote="/".join(remote) if remote else "")
    return Provenance()


def _checkout_root(directory: Path) -> Path | None:
    return next((parent for parent in (directory, *directory.parents) if (parent / ".git").exists()), None)


def _local_source_root(source: str) -> Path | None:
    if source.startswith("file://"):
        try:
            url = urlparse(source)
        except ValueError:
            return None
        if url.netloc not in {"", "localhost"}:
            return None
        source = unquote(url.path)
    path = Path(os.path.expanduser(source))
    if path.is_absolute() and path.exists():
        return _checkout_root(path.resolve())
    return None


def _git(checkout: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(checkout), *args], text=True,
                                   stderr=subprocess.DEVNULL, timeout=2).strip()


def placement_fingerprint(real_dir: str) -> str:
    return hashlib.sha256(os.path.realpath(real_dir).encode("utf-8")).hexdigest()[:16]


def identity_key(provenance: Provenance, real_dir: str) -> str:
    if provenance.host and provenance.repo and provenance.path:
        return f"src:{provenance.host}/{provenance.repo}@{provenance.path}"
    return f"loc:{placement_fingerprint(real_dir)}"


def parse_identity_key(key: str) -> dict[str, str]:
    """Inverse of :func:`identity_key`, for display and debugging."""
    if key.startswith("src:"):
        rest = key[len("src:") :]
        location, _, path = rest.partition("@")
        host, _, repo = location.partition("/")
        return {"kind": "src", "host": host, "repo": repo, "path": path}
    if key.startswith("loc:"):
        return {"kind": "loc", "fingerprint": key[len("loc:") :]}
    return {"kind": "unknown"}
