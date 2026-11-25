"""Manage prompts in the current checkout's prompts/ directory."""
from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from typing import Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import prompt_catalog as catalog
from .config import config_dir
from .library import read_json, write_json, writing
from .prompt_files import PromptFiles, working_files

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class PromptText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=200_000)
    title: str = Field(default="", max_length=120)
    category: str = Field(default="", max_length=80)


class Prompt(PromptText):
    id: str
    revision: int = Field(ge=1)
    updatedAt: float


class LegacyBook(BaseModel):
    version: Literal[1]
    items: dict[str, Prompt]
    deleted: dict[str, int] = Field(default_factory=dict)


def fingerprint(info: dict, body: str) -> str:
    return hashlib.sha256(json.dumps([info, body], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class PromptRepository:
    def __init__(self, files: PromptFiles):
        self.files = files
        manifest = files.get("catalog.json")
        self.entries = catalog.read_catalog(manifest.encode()) if manifest is not None else {}
        self.history = read_json(files.history, {})
        self.items: dict[str, Prompt] = {}
        self.index_changed = False
        for key, info in self.entries.items():
            body = files.get(info["path"])
            if body is None:
                raise ValueError("索引中的正文文件缺失")
            record = self.history.get(key, {})
            digest = fingerprint(info, body)
            if record.get("digest") != digest:
                record = {"revision": record.get("revision", 0) + 1, "digest": digest,
                          "updatedAt": files.path(info["path"]).stat().st_mtime}
                self.history[key] = record
            self.items[key] = Prompt(id=key, title=info["title"], category=info["category"], body=body,
                                     revision=record["revision"], updatedAt=record["updatedAt"])
        for key, record in self.history.items():
            if key not in self.items and record.get("digest") is not None:
                self.history[key] = {"revision": record["revision"] + 1, "digest": None}

    def revision(self, key: str) -> int:
        return self.history.get(key, {}).get("revision", 0)

    def destination(self, item: Prompt, prior: dict | None) -> str:
        path = catalog.entry_path(item.category, item.title)
        if prior and (prior["title"], prior["category"]) == (item.title, item.category):
            path = prior["path"]
        folder, filename = path.split("/")
        occupied = {entry["path"].casefold() for key, entry in self.entries.items() if key != item.id}
        for candidate in (path, f"{folder}/{filename[:-4][:42].rstrip()}-{item.id[:8]}.txt",
                          f"{folder}/{item.id}.txt"):
            if candidate.casefold() in occupied:
                continue
            if candidate == self.entries.get(item.id, {}).get("path") or not self.files.path(candidate).exists():
                return candidate
        raise ValueError("提示词文件名已被占用")

    def save(self, item: Prompt, *, source: dict | None = None) -> None:
        key = item.id
        old = self.entries.get(key)
        record = self.history.get(key, {})
        prior = old or record.get("removed") or source
        path = self.destination(item, prior)
        info = {**(prior or {}), "title": item.title, "category": item.category, "path": path}
        self.files.put(path, item.body)
        if old and old["path"] != path:
            self.files.put(old["path"], None)
        if old != info:
            if old is None and "position" in record:
                entries = list(self.entries.items())
                entries.insert(record["position"], (key, info))
                self.entries = dict(entries)
            else:
                self.entries[key] = info
            self.index_changed = True
        self.history[key] = {"revision": item.revision, "updatedAt": item.updatedAt, "digest": fingerprint(info, item.body)}
        self.items[key] = item

    def delete(self, key: str) -> int:
        position = list(self.entries).index(key)
        info = self.entries.pop(key)
        revision = self.items.pop(key).revision + 1
        self.files.put(info["path"], None)
        self.history[key] = {"revision": revision, "digest": None, "removed": info, "position": position}
        self.index_changed = True
        return revision

    def finish(self) -> None:
        if self.index_changed:
            previous = self.files.get("README.md")
            readme = catalog.index_bytes(self.entries, previous.encode() if previous is not None else None)
            self.files.put("README.md", readme.decode())
            self.files.put("catalog.json", catalog.catalog_bytes(self.entries).decode())
        self.files.finish(self.history)
        self.files.original.update(self.files.edits)
        self.files.edits.clear()
        self.index_changed = False


def import_legacy(repo: PromptRepository) -> None:
    legacy = config_dir() / "prompts.json"
    marker = legacy.with_name("prompts.migrated.json")
    if marker.exists() or not legacy.is_file():
        return
    # A user can open several checkouts with a single old config. Import that file once.
    with writing():
        if marker.exists():
            return
        try:
            book = LegacyBook.model_validate_json(legacy.read_bytes())
            for key, item in book.items.items():
                if UUID(key).hex != key or item.id != key:
                    raise ValueError("提示词 ID 不匹配")
                existing = repo.items.get(key)
                if existing and (item.title, item.category, item.body) == (existing.title, existing.category, existing.body):
                    record = repo.history[key]
                    record["revision"] = max(item.revision, existing.revision)
                    record["updatedAt"] = item.updatedAt
                    repo.items[key] = existing.model_copy(update={"revision": record["revision"], "updatedAt": item.updatedAt})
                    continue
                if existing:
                    # Keep both versions if the checkout has been edited since the private library was last used.
                    copy_title = item.title[:116] + "（旧库）"
                    seed = fingerprint({"title": item.title, "category": item.category}, item.body)
                    copy_id = uuid5(UUID(key), seed).hex
                    while copy_id in repo.items:
                        copy = repo.items[copy_id]
                        if (copy.title, copy.category, copy.body) == (copy_title, item.category, item.body):
                            break
                        copy_id = uuid5(UUID(copy_id), seed).hex
                    else:
                        copy = item.model_copy(update={"id": copy_id, "title": copy_title})
                        repo.save(copy, source=repo.entries[key])
                else:
                    repo.save(item)
            for key, revision in book.deleted.items():
                if key not in repo.history:
                    repo.history[key] = {"revision": revision, "digest": None}
        except (ValueError, TypeError) as exc:
            raise HTTPException(500, "旧提示词库无法导入，请检查配置目录里的 prompts.json。") from exc
        repo.finish()
        write_json(marker, {"repository": str(repo.files.project)})


@contextmanager
def repository():
    with working_files() as files:
        repo = PromptRepository(files)
        import_legacy(repo)
        yield repo
        repo.finish()


def conflict() -> HTTPException:
    return HTTPException(409, "这条提示词已在其他窗口或仓库中更改或删除")


@router.get("")
def list_prompts():
    with repository() as repo:
        response = {"items": sorted(repo.items.values(), key=lambda p: (p.updatedAt, p.id), reverse=True)}
    if url := catalog.github_catalog_url():
        response["catalogUrl"] = url
    return response


@router.put("/{prompt_id}")
def save_prompt(prompt_id: UUID, draft: PromptText, if_match: int = Header(ge=0)) -> Prompt:
    key = prompt_id.hex
    if not draft.body.strip():
        raise HTTPException(400, "请先填写提示词正文")
    first_line = draft.body.strip().splitlines()[0]
    title = draft.title.strip() or (first_line if len(first_line) <= 36 else first_line[:35] + "…")
    category = draft.category.strip()
    with repository() as repo:
        category = next((p.category for p in repo.items.values() if p.category.casefold() == category.casefold()), category)
        if category == "未分类":
            category = ""
        current = repo.items.get(key)
        revision = repo.revision(key)
        if (current and if_match in (revision, revision - 1)
                and (current.title, current.category, current.body) == (title, category, draft.body)):
            return current
        if if_match != revision:
            raise conflict()
        item = Prompt(id=key, revision=revision + 1, updatedAt=time.time(), title=title, category=category, body=draft.body)
        repo.save(item)
        return item


@router.delete("/{prompt_id}")
def delete_prompt(prompt_id: UUID, if_match: int = Header(ge=1)) -> dict[str, int]:
    key = prompt_id.hex
    with repository() as repo:
        revision = repo.revision(key)
        if key not in repo.items and revision == if_match + 1:
            return {"revision": revision}
        if key not in repo.items or revision != if_match:
            raise conflict()
        return {"revision": repo.delete(key)}
