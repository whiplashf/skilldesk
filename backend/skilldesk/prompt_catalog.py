"""The portable prompts/ directory shared by GitHub and fresh installations."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from html import escape
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from uuid import UUID

PROJECT = Path(__file__).resolve().parents[2]
ARTICLE = "https://mp.weixin.qq.com/s/NAdhdFrUq9-BKelqzqpwBQ"
INDEX_START = "<!-- skilldesk:entries -->"
INDEX_END = "<!-- /skilldesk:entries -->"


def segment(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    cleaned = "".join(c if c.isalnum() or c in "-_·" else " " for c in normalized)
    return " ".join(cleaned.split())[:52].strip() or "提示词"


def entry_path(category: str, title: str) -> str:
    return f"{segment(category or '未分类')}/{segment(title)}.txt"


def validate_path(value: str) -> None:
    parts = value.split("/")
    if (len(parts) != 2 or not parts[1].endswith(".txt")
            or any(not part or segment(part) != part for part in (parts[0], parts[1][:-4]))):
        raise ValueError("提示词文件路径无效")


def read_catalog(data: bytes) -> dict[str, dict]:
    catalog = json.loads(data)
    if not isinstance(catalog, dict) or catalog.get("version") != 1 or not isinstance(catalog.get("items"), dict):
        raise ValueError("提示词索引版本无效")
    seen = set()
    for key, info in catalog["items"].items():
        if (UUID(key).hex != key or not isinstance(info["title"], str) or not isinstance(info["category"], str)
                or not info["title"].strip()):
            raise ValueError("提示词索引条目无效")
        validate_path(info["path"])
        path = info["path"].casefold()
        if path in seen:
            raise ValueError("提示词文件路径重复")
        seen.add(path)
    return catalog["items"]


def catalog_bytes(items: dict[str, dict]) -> bytes:
    return (json.dumps({"version": 1, "items": items}, indent=2, ensure_ascii=False) + "\n").encode()


def label(text: str) -> str:
    return re.sub(r"([\\\[\]*_`])", r"\\\1", escape(" ".join(text.split()), quote=False))


def index_bytes(items: dict[str, dict], previous: bytes | None = None) -> bytes:
    groups: dict[str, list] = {}
    for item in items.values():
        groups.setdefault(item["category"] or "未分类", []).append(item)
    lines = ["", f"共 {len(items)} 条，分为 {len(groups)} 类。"]
    for category, group in groups.items():
        lines.extend(["", f"## {label(category)}", ""])
        for item in group:
            credit = " · 数字生命卡兹克" if item.get("source") == ARTICLE and "卡兹克" not in item["title"] else ""
            lines.append(f"- [{label(item['title'])}]({quote(item['path'])}){credit}")
    if any(item.get("source") == ARTICLE for item in items.values()):
        article = f"[《都 Agent 时代了，我还是想分享给你这 12 个我最常用的 Prompt》]({ARTICLE})"
        lines.extend(["", "## 出处", "", f"卡兹克的 12 个模板来自数字生命卡兹克分享的{article}。"])
    doc = (previous.decode() if previous is not None else "# 提示词库\n\n打开一条提示词，点击 GitHub 文件右上角的 "
           f"**Copy raw file** 即可复制完整正文。\n\n{INDEX_START}\n{INDEX_END}\n")
    if doc.count(INDEX_START) != 1 or doc.count(INDEX_END) != 1 or doc.index(INDEX_START) >= doc.index(INDEX_END):
        raise ValueError("README.md 缺少提示词索引标记")
    before, _, rest = doc.partition(INDEX_START)
    _, _, after = rest.partition(INDEX_END)
    return (before + INDEX_START + "\n".join(lines) + "\n" + INDEX_END + after).encode()


def public_version(repository: str, branch: str, key: str, info: dict | None, body: bytes) -> str:
    metadata = json.dumps([repository, branch, key, info], ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(metadata + b"\0" + body).hexdigest()


def checked_file(root: Path, relative: str) -> Path:
    path = root
    for part in PurePosixPath(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("提示词目录含符号链接")
    return path
