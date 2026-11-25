"""Serialize working-tree edits and recover a partially written catalog after a restart."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from . import prompt_catalog as catalog
from .config import state_dir
from .library import read_json, write_json


def read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"{path.name} 必须是普通文件")
    return path.read_bytes().decode("utf-8")


def replace_text(path: Path, text: str | None) -> None:
    if text is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".skilldesk-{uuid4().hex}.tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(text.encode())
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_file():
            temp.chmod(stat.S_IMODE(path.stat().st_mode))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class PromptFiles:
    def __init__(self, project: Path, runtime: Path):
        self.project = project
        self.journal = catalog.checked_file(runtime, "pending.json")
        self.history = catalog.checked_file(runtime, "revisions.json")
        self.original: dict[str, str | None] = {}
        self.edits: dict[str, str | None] = {}

    def path(self, name: str) -> Path:
        if name not in {"catalog.json", "README.md"}:
            catalog.validate_path(name)
        return catalog.checked_file(self.project, "prompts/" + name)

    def get(self, name: str) -> str | None:
        if name in self.edits:
            return self.edits[name]
        if name not in self.original:
            self.original[name] = read_text(self.path(name))
        return self.original[name]

    def put(self, name: str, text: str | None) -> None:
        self.get(name)
        self.edits[name] = text

    def rollback(self, changes: dict) -> None:
        for name, (before, after) in reversed(changes.items()):
            path = self.path(name)
            if read_text(path) == after:
                replace_text(path, before)
        self.journal.unlink()

    def recover(self, pending: dict) -> None:
        changes = pending["files"]
        # Neither Git nor a text editor holds our lock. Keep edits made outside Skilldesk.
        for name, (before, after) in changes.items():
            if read_text(self.path(name)) not in (before, after):
                self.rollback(changes)
                raise HTTPException(409, "仓库文件在保存时发生变化，请刷新后重试。")
        for name, (_, after) in changes.items():
            path = self.path(name)
            if read_text(path) != after:
                replace_text(path, after)
        write_json(self.history, pending["history"])
        self.journal.unlink()

    def finish(self, history: dict) -> None:
        files = {name: [self.original[name], text] for name, text in self.edits.items()
                 if self.original[name] != text}
        if not files:
            if history != read_json(self.history, {}):
                write_json(self.history, history)
            return
        if any(read_text(self.path(name)) != before for name, (before, _) in files.items()):
            raise HTTPException(409, "仓库文件在保存时发生变化，请刷新后重试。")
        pending = {"files": files, "history": history}
        write_json(self.journal, pending)
        try:
            self.recover(pending)
        except OSError:
            # Return a usable original library on an ordinary write failure. A process
            # interruption leaves the journal intact for the next request to finish.
            self.rollback(files)
            raise


@contextmanager
def checkout_lock(project: Path, runtime: Path):
    if os.name == "posix":
        import fcntl

        # All service profiles editing this directory share the same lock.
        descriptor = os.open(project, os.O_RDONLY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)
    else:
        with closing(sqlite3.connect(catalog.checked_file(runtime, "lock.sqlite"), timeout=10)) as lock:
            lock.execute("BEGIN IMMEDIATE")
            yield


@contextmanager
def working_files():
    project = catalog.PROJECT
    if project is None:
        raise HTTPException(503, "请在 Skilldesk 代码仓库中启动服务，以便保存提示词。")
    try:
        # Keep recovery data outside Git and isolate independently checked-out branches.
        worktree_id = hashlib.sha256(os.fsencode(project.resolve())).hexdigest()
        runtime = state_dir() / "prompt-worktrees" / worktree_id
        runtime.mkdir(parents=True, exist_ok=True)
        with checkout_lock(project, runtime):
            files = PromptFiles(project, runtime)
            if files.journal.exists():
                files.recover(read_json(files.journal, {}))
            yield files
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(500, "无法读写当前仓库的提示词，请检查目录权限和磁盘空间。") from exc
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(500, "提示词目录格式异常，请检查 prompts/catalog.json 和对应的正文文件。") from exc
