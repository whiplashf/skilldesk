"""Personal prompt text is durable config. The skill scanner never rebuilds this file."""
from __future__ import annotations

import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import prompt_catalog, prompt_publish
from .config import config_dir
from .library import write_json, writing

router = APIRouter(prefix="/api/prompts", tags=["prompts"])
FILENAME = "prompts.json"


class PromptText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=200_000)
    title: str = Field(default="", max_length=120)
    category: str = Field(default="", max_length=80)


class Prompt(PromptText):
    id: str
    revision: int = Field(ge=1)
    updatedAt: float


class PromptBook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    items: dict[str, Prompt]
    # Keep only the revision after deletion so stale writes cannot recreate a prompt.
    deleted: dict[str, int] = Field(default_factory=dict)


def load_book() -> PromptBook:
    try:
        path = config_dir() / FILENAME
        if path.exists():
            return PromptBook.model_validate_json(path.read_bytes())
        root = prompt_catalog.PROJECT
        catalog = prompt_catalog.checked_file(root, "prompts/catalog.json")
        items = {}
        if catalog.is_file():
            for key, info in prompt_catalog.read_catalog(catalog.read_bytes()).items():
                file = prompt_catalog.checked_file(root / "prompts", info["path"])
                items[key] = Prompt(id=key, revision=1, updatedAt=0, title=info["title"],
                                    category=info["category"], body=file.read_bytes().decode())
        return PromptBook(version=1, items=items)
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(500, "无法读取本机提示词库，请检查 prompts.json") from exc


def conflict() -> HTTPException:
    return HTTPException(409, "这条提示词已在其他窗口更改或删除")


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base: str = Field(pattern=r"^[a-f0-9]{64}$")


def saved_revision(prompt_id: UUID, revision: int) -> Prompt:
    prompt = load_book().items.get(prompt_id.hex)
    if not prompt or prompt.revision != revision:
        raise conflict()
    return prompt


@router.post("/{prompt_id}/publication/preview")
def preview_publication(prompt_id: UUID, if_match: int = Header(ge=1)):
    return prompt_publish.publication(saved_revision(prompt_id, if_match))


@router.post("/{prompt_id}/publication")
def publish_prompt(prompt_id: UUID, request: PublishRequest, if_match: int = Header(ge=1)):
    return prompt_publish.publication(saved_revision(prompt_id, if_match), request.base)


@router.get("")
def list_prompts():
    response = {"items": sorted(load_book().items.values(), key=lambda p: (p.updatedAt, p.id), reverse=True)}
    if (prompt_catalog.PROJECT / "prompts/catalog.json").is_file():
        try:
            target = prompt_publish.destination()
        except HTTPException:
            return response
        response["catalogUrl"] = f"https://github.com/{target.name}/tree/HEAD/prompts"
    return response


@router.put("/{prompt_id}")
def save_prompt(prompt_id: UUID, draft: PromptText, if_match: int = Header(ge=0)) -> Prompt:
    key = prompt_id.hex
    if not draft.body.strip():
        raise HTTPException(400, "请先填写提示词正文")
    first_line = draft.body.strip().splitlines()[0]
    title = draft.title.strip() or (first_line if len(first_line) <= 36 else first_line[:35] + "…")
    category = draft.category.strip()
    with writing(FILENAME) as path:
        book = load_book()
        category = next((p.category for p in book.items.values() if p.category.casefold() == category.casefold()), category)
        if category == "未分类":
            category = ""
        current = book.items.get(key)
        revision = current.revision if current else book.deleted.get(key, 0)
        if (current and if_match in (revision, revision - 1)
                and (current.title, current.category, current.body) == (title, category, draft.body)):
            return current
        if if_match != revision:
            raise conflict()
        entry = Prompt(id=key, revision=revision + 1, updatedAt=time.time(), title=title, category=category, body=draft.body)
        book.items[key] = entry
        book.deleted.pop(key, None)
        write_json(path, book.model_dump())
        return entry


@router.delete("/{prompt_id}")
def delete_prompt(prompt_id: UUID, if_match: int = Header(ge=1)) -> dict[str, int]:
    key = prompt_id.hex
    with writing(FILENAME) as path:
        book = load_book()
        current = book.items.get(key)
        if not current and book.deleted.get(key) == if_match + 1:
            return {"revision": if_match + 1}
        if not current or current.revision != if_match:
            raise conflict()
        del book.items[key]
        book.deleted[key] = if_match + 1
        write_json(path, book.model_dump())
        return {"revision": if_match + 1}
