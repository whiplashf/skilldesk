"""Install baselines: what the upstream looked like when we last observed it.

The GitHub API can tell what the upstream folder looks like *now*; only a
baseline can tell whether that is different from what is installed. Two numbers
are recorded per skill:

* ``dirTree``  — git tree SHA of the skill folder upstream at first observation
* ``localTree`` — git tree SHA of the installed folder at the same moment

With both, a later check answers "did the upstream move" and "was the installed
copy edited by hand" without downloading anything again. This is machine-derived
state (never authored by the user), so it lives in the state directory: deleting
it only loses history, never data.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .config import state_dir
from .library import read_json, write_json

VERSION = 1


def baseline_path() -> Path:
    return state_dir() / "baselines.json"


@contextmanager
def _writing():
    """Serialise read-modify-write across processes (same trick as the library)."""
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = sqlite3.connect(directory / "baselines.lock", timeout=10)
    try:
        lock.execute("BEGIN IMMEDIATE")
        yield baseline_path()
    finally:
        lock.close()


def load() -> dict:
    payload = read_json(baseline_path(), {})
    if not isinstance(payload, dict) or payload.get("version") != VERSION:
        return {"version": VERSION, "entries": {}}
    if not isinstance(payload.get("entries"), dict):
        return {"version": VERSION, "entries": {}}
    return payload


def get(identity_key: str, repo: str, dir_path: str) -> dict | None:
    """The baseline for this skill, but only if it still points at the same folder."""
    entry = load()["entries"].get(identity_key)
    if not isinstance(entry, dict):
        return None
    if entry.get("repo", "").lower() != repo.lower() or entry.get("dirPath", "") != dir_path:
        return None
    return entry


def record(
    identity_key: str,
    *,
    repo: str,
    dir_path: str,
    dir_tree: str,
    head_ref: str,
    local_tree: str,
) -> dict:
    entry = {
        "repo": repo,
        "dirPath": dir_path,
        "dirTree": dir_tree,
        "headRef": head_ref,
        "localTree": local_tree,
        "recordedAt": int(time.time()),
    }
    with _writing() as path:
        payload = load()
        payload["entries"][identity_key] = entry
        write_json(path, payload)
    return entry


def forget(identity_key: str) -> bool:
    with _writing() as path:
        payload = load()
        removed = payload["entries"].pop(identity_key, None) is not None
        if removed:
            write_json(path, payload)
    return removed
