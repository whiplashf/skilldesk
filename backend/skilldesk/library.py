"""Durable user annotations, separate from the rebuildable inventory.

A claim (``mine`` or a GitHub coordinate) is an annotation that answers a
question the scanner cannot: "I know where this came from, or that nobody does".
Readers therefore treat claims as a source of truth about *unrecorded* skills;
the scanner keeps saying what the machine can prove.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .config import config_dir


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", delete=False) as stream:
        tmp = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def stored() -> dict:
    value = read_json(config_dir() / "library.json", {"version": 1, "revision": 0, "assets": {}})
    if value.get("version") != 1 or not isinstance(value.get("assets"), dict):
        raise ValueError("用户库格式无法识别")
    return value


def resolved(library: dict, conn: sqlite3.Connection) -> dict:
    """Recover an annotation after a single unambiguous move or change in provenance."""
    if not library["assets"]:
        return library
    inventory = {
        r["identity_key"]: r for r in conn.execute("SELECT identity_key, realpath, content_hash FROM skill")
    }
    paths = {r["realpath"]: key for key, r in inventory.items()}
    hashes: dict[str, list[str]] = {}
    for key, row in inventory.items():
        hashes.setdefault(row["content_hash"], []).append(key)
    assets = dict(library["assets"])
    missing_hashes: dict[str, int] = {}
    for key, asset in assets.items():
        if key not in inventory and asset.get("contentHash"):
            digest = asset["contentHash"]
            missing_hashes[digest] = missing_hashes.get(digest, 0) + 1
    for old, asset in library["assets"].items():
        if old in inventory:
            continue
        new = paths.get(asset.get("realpath"))
        digest = asset.get("contentHash", "")
        if not new and old.startswith("loc:") and missing_hashes.get(digest) == 1:
            matches = hashes.get(digest, [])
            new = matches[0] if len(matches) == 1 else None
        if new and new not in assets and (new.startswith("loc:") or old.startswith("loc:")):
            assets[new] = assets.pop(old)
    for key in assets.keys() & inventory.keys():
        row = inventory[key]
        assets[key] = {**assets[key], "realpath": row["realpath"], "contentHash": row["content_hash"]}
    return {**library, "assets": assets}


MINE_LABEL = "本地自写"


def claim_of(asset: dict) -> dict[str, str]:
    """The user's own attribution of one asset, if they made one.

    A GitHub coordinate is more specific than "I wrote it", so it wins when both
    are set. An empty dict means the user has not answered the question.
    """
    github = asset.get("github") or {}
    repo = str(github.get("repo") or "").strip()
    if repo:
        return {
            "kind": "github",
            "repo": repo,
            "path": str(github.get("path") or "").strip(),
            "label": "github.com/" + repo,
        }
    if asset.get("mine"):
        return {"kind": "mine", "repo": "", "path": "", "label": MINE_LABEL}
    return {}


def apply_claim(item: dict, claim: dict[str, str]) -> dict:
    """Report a claim in place of an empty scan verdict, on any skill payload.

    Shared by the HTTP API and the CLI so both tell the same story: the claim
    becomes the source, the "unclaimed" warning disappears, and a machine record
    is never overwritten.
    """
    if not claim or item["provenance"]["confidence"] != "none":
        return item
    item["provenance"].update(
        confidence="claimed",
        label=claim["label"],
        sourceLabel=claim["label"],
        path=claim["path"],
        evidence="我写的" if claim["kind"] == "mine" else "用户关联",
    )
    item["health"] = [kind for kind in item.get("health", []) if kind != "unclaimed_source"]
    if "issues" in item:
        item["issues"] = [issue for issue in item["issues"] if issue["kind"] != "unclaimed_source"]
    return item


def claims(assets: dict) -> dict[str, dict[str, str]]:
    """One claim per identity key; assets without a claim are left out."""
    found: dict[str, dict[str, str]] = {}
    for key, asset in assets.items():
        claim = claim_of(asset)
        if claim:
            found[key] = claim
    return found


class RevisionConflict(Exception):
    pass


@contextmanager
def writing():
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = sqlite3.connect(directory / "library.lock", timeout=10)
    try:
        lock.execute("BEGIN IMMEDIATE")
        yield directory / "library.json"
    finally:
        lock.close()


def reconcile(conn: sqlite3.Connection) -> None:
    if not (config_dir() / "library.json").exists():
        return
    with writing() as path:
        old = stored()
        current = resolved(old, conn)
        if old != current:
            current["revision"] += 1
            write_json(path, current)


def update(conn: sqlite3.Connection, skill: dict, changes: dict, revision: int) -> dict:
    with writing() as path:
        library = resolved(stored(), conn)
        if library["revision"] != revision:
            raise RevisionConflict
        key = skill["identity_key"]
        asset = {**library["assets"].get(key, {}), **changes}
        if (
            asset.get("favorite")
            or asset.get("mine")
            or asset.get("github")
            or set(asset) - {"favorite", "mine", "github", "realpath", "contentHash"}
        ):
            asset.update(realpath=skill["realpath"], contentHash=skill["content_hash"])
            library["assets"][key] = asset
        else:
            library["assets"].pop(key, None)
        library["revision"] += 1
        write_json(path, library)
        return library
