import json
import subprocess
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from skilldesk import prompt_catalog as catalog
from skilldesk import prompt_files, prompts
from skilldesk.config import config_dir
from skilldesk.server import create_app


@pytest.fixture
def http(fake_home):
    with TestClient(create_app()) as client:
        client.headers["X-Skilldesk-Token"] = client.get("/api/session").json()["token"]
        yield client


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def seed(items):
    root = catalog.PROJECT / "prompts"
    entries = {}
    for key, title, body in items:
        path = catalog.entry_path("学习", title)
        entries[key] = {"title": title, "category": "学习", "path": path, "author": "原作者", "source": catalog.ARTICLE}
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(body.encode())
    (root / "catalog.json").write_bytes(catalog.catalog_bytes(entries))
    (root / "README.md").write_bytes(catalog.index_bytes(entries) + b"\nEditorial note.\n")
    return root


def test_working_tree_only_and_same_titles(http, prompt_checkout):
    repo, origin = prompt_checkout
    initial, staged = git(repo, "rev-parse", "HEAD"), git(repo, "diff", "--cached")
    for title, body in [("A/B", "\r\n 首条  \n"), ("A B", "第二条")]:
        url = "/api/prompts/" + uuid4().hex
        http.put(url, headers={"If-Match": "0"}, json={"title": title, "category": "cache", "body": body}).raise_for_status()
    root = repo / "prompts"
    items = catalog.read_catalog((root / "catalog.json").read_bytes())
    assert {v["title"]: (root / v["path"]).read_bytes() for v in items.values()} == {
        "A/B": "\r\n 首条  \n".encode(), "A B": "第二条".encode(),
    }
    paths = set(git(repo, "ls-files", "-z", "--others", "--exclude-standard").decode().strip("\0").split("\0"))
    assert paths == {"prompts/catalog.json", "prompts/README.md", *("prompts/" + v["path"] for v in items.values())}
    assert git(repo, "diff", "--cached") == staged
    assert git(repo, "rev-parse", "HEAD") == git(origin, "rev-parse", "HEAD") == initial
    assert not (config_dir() / "prompts.json").exists()
    assert http.post(url + "/publication", json={}).status_code in (404, 405)


def test_direct_edit_move_delete_and_undo_preserve_file_and_credits(http):
    key = uuid4().hex
    root = seed([(key, "阅读", "原正文"), (uuid4().hex, "另一条", "另一条正文")])
    url = "/api/prompts/" + key
    original_index = (root / "catalog.json").read_bytes()
    original_readme = (root / "README.md").read_bytes()
    current = next(item for item in http.get("/api/prompts").json()["items"] if item["id"] == key)
    file = root / "学习/阅读.txt"
    file.write_bytes(b"Edit from Git\r\n")
    assert http.put(url, headers={"If-Match": str(current["revision"])}, json={"body": "stale"}).status_code == 409
    updated = next(item for item in http.get("/api/prompts").json()["items"] if item["id"] == key)
    assert updated["body"] == "Edit from Git\r\n"
    draft = {"title": "阅读", "category": "学习", "body": "保留\n  精确换行\n"}
    changed = http.put(url, headers={"If-Match": str(updated["revision"])}, json=draft).json()
    assert file.read_bytes() == draft["body"].encode()
    assert (root / "catalog.json").read_bytes() == original_index
    assert (root / "README.md").read_bytes() == original_readme
    deleted = http.delete(url, headers={"If-Match": str(changed["revision"])}).json()
    assert not file.exists()
    restored = http.put(url, headers={"If-Match": str(deleted["revision"])}, json=draft).json()
    assert (root / "catalog.json").read_bytes() == original_index
    assert (root / "README.md").read_bytes() == original_readme
    assert file.read_bytes() == draft["body"].encode()
    http.put(url, headers={"If-Match": str(restored["revision"])}, json={**draft, "category": "验收", "title": "复核"}).raise_for_status()
    moved = catalog.read_catalog((root / "catalog.json").read_bytes())[key]
    assert not file.exists() and moved["path"] == "验收/复核.txt" and moved["source"] == catalog.ARTICLE
    assert (root / moved["path"]).read_bytes() == draft["body"].encode()
    assert (root / "README.md").read_bytes().endswith(b"Editorial note.\n")


def test_one_time_upgrade_preserves_existing_files_and_local_edits(http):
    same, different, extra = (uuid4().hex for _ in range(3))
    root = seed([(same, "相同", "正文"), (different, "有改动", "仓库版本")])
    def legacy(key, title, body):
        return {"id": key, "title": title, "category": "学习", "body": body, "revision": 7, "updatedAt": 123.0}
    rows = [legacy(same, "相同", "正文"), legacy(different, "有改动", "本机版本"), legacy(extra, "旧库新增", "添加")]
    archive = config_dir() / "prompts.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(json.dumps({"version": 1, "items": {row["id"]: row for row in rows}}))
    before = archive.read_bytes()
    migrated = http.get("/api/prompts").json()["items"]
    assert {item["body"] for item in migrated} == {"正文", "仓库版本", "本机版本", "添加"}
    assert next(item for item in migrated if item["id"] == same)["revision"] == 7
    assert (root / "学习/有改动.txt").read_text() == "仓库版本"
    assert any(item["title"].endswith("（旧库）") for item in migrated)
    http.delete("/api/prompts/" + extra, headers={"If-Match": "7"}).raise_for_status()
    assert len(http.get("/api/prompts").json()["items"]) == 3
    assert not (root / "学习/旧库新增.txt").exists()
    copy = next(item for item in migrated if item["body"] == "本机版本")
    assert catalog.read_catalog((root / "catalog.json").read_bytes())[copy["id"]]["author"] == "原作者"
    assert archive.read_bytes() == before


def test_failed_write_rolls_back_and_retries_without_duplicate(http, monkeypatch):
    replace = prompt_files.replace_text
    failed = False
    def interrupt(path, text):
        nonlocal failed
        if path.name == "catalog.json" and not failed:
            failed = True
            raise OSError("interrupted")
        replace(path, text)
    monkeypatch.setattr(prompt_files, "replace_text", interrupt)
    url = "/api/prompts/" + uuid4().hex
    draft = {"body": "一次保存"}
    assert http.put(url, json=draft, headers={"If-Match": "0"}).status_code == 500
    assert http.get("/api/prompts").json()["items"] == []
    assert not (catalog.PROJECT / "prompts/未分类/一次保存.txt").exists()
    saved = http.put(url, json=draft, headers={"If-Match": "0"}).json()
    assert saved["body"] == "一次保存"
    assert http.put(url, json=draft, headers={"If-Match": "0"}).json() == saved


def test_reopen_finishes_interrupted_working_tree_write(http, monkeypatch):
    original = prompt_files.replace_text
    def stop(path, text):
        if path.name == "catalog.json":
            raise SystemExit()
        original(path, text)
    key = uuid4()
    with monkeypatch.context() as patch:
        patch.setattr(prompt_files, "replace_text", stop)
        with pytest.raises(SystemExit):
            prompts.save_prompt(key, prompts.PromptText(body="重启后恢复"), 0)
    [saved] = http.get("/api/prompts").json()["items"]
    assert (saved["id"], saved["revision"], saved["body"]) == (key.hex, 1, "重启后恢复")
    assert (catalog.PROJECT / "prompts/未分类/重启后恢复.txt").read_text() == saved["body"]


@pytest.mark.parametrize("path", ["../drafts.txt", "/root/file.txt", "设计/a/b.txt", ".git/config"])
def test_catalog_rejects_paths_outside_prompt_folders(path):
    info = {"title": "示例", "category": "测试", "path": path}
    with pytest.raises(ValueError):
        catalog.read_catalog(catalog.catalog_bytes({uuid4().hex: info}))
