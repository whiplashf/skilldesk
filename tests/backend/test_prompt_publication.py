import json
import subprocess
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from skilldesk import prompt_catalog, prompts
from skilldesk.server import create_app


def remote(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def test_publish_only_selected_revision_and_keep_other_drafts_private(fake_home, publication_remote):
    repo = publication_remote
    start = remote(repo, "rev-parse", "HEAD")
    url = "/api/prompts/" + uuid4().hex
    body = "\n 第一行\r\n  第二行  \n"
    with TestClient(create_app()) as http:
        session = {"X-Skilldesk-Token": http.get("/api/session").json()["token"]}
        http.headers.update(session)
        http.put("/api/prompts/" + uuid4().hex, json={"body": "私有草稿"}, headers={"If-Match": "0"}).raise_for_status()
        draft = {"body": body, "category": "设计", "title": "阅读"}
        http.put(url, headers={"If-Match": "0"}, json=draft).raise_for_status()
        pub = url + "/publication"
        rev = {"If-Match": "1"}
        preview = http.post(pub + "/preview", headers=rev).json()
        assert preview["state"] == "new" and preview["repository"] == "test/library"
        assert remote(repo, "rev-parse", "HEAD") == start
        assert http.post(pub, headers={**rev, "X-Skilldesk-Token": ""}, json={"base": preview["base"]}).status_code == 403
        assert http.post(pub, headers={"If-Match": "2"}, json={"base": preview["base"]}).status_code == 409
        published = http.post(pub, headers=rev, json={"base": preview["base"]}).json()
        assert published["state"] == "current"
        assert http.post(pub, headers=rev, json={"base": preview["base"]}).json() == published
        assert remote(repo, "rev-list", "--count", "HEAD").strip() == b"2"
        assert remote(repo, "show", "HEAD:prompts/设计/阅读.txt") == body.encode()
        manifest = json.loads(remote(repo, "show", "HEAD:prompts/catalog.json"))["items"]
        assert list(manifest) == [url.split("/")[-1]]
        assert remote(repo, "show", "HEAD:README.md") == b"Project"
        assert http.post(pub + "/preview", headers=rev).json()["state"] == "current"

        http.put(url, headers=rev, json={**draft, "title": "复核", "category": "验收"}).raise_for_status()
        rev = {"If-Match": "2"}
        changed = http.post(pub + "/preview", headers=rev).json()
        assert changed["state"] == "update" and changed["previous"] == draft
        # Simulate a second device updating this prompt directly on the default branch.
        other = fake_home / "other"
        subprocess.run(["git", "clone", "-q", str(repo), str(other)], check=True)
        (other / "prompts/设计/阅读.txt").write_text("来自另一台电脑")
        readme = other / "prompts/README.md"
        readme.write_bytes(readme.read_bytes() + b"\nLocal editorial note.\n")
        remote(other, "-c", "user.name=Second", "-c", "user.email=second@example.invalid", "commit", "-qam", "Edit")
        remote(other, "push", "-q")
        assert http.post(pub, headers=rev, json={"base": changed["base"]}).status_code == 409
        retry = http.post(pub + "/preview", headers=rev).json()
        assert retry["previous"]["body"] == "来自另一台电脑"
        http.post(pub, headers=rev, json={"base": retry["base"]}).raise_for_status()
        assert remote(repo, "ls-tree", "HEAD", "--", "prompts/设计/阅读.txt") == b""
        assert remote(repo, "show", "HEAD:prompts/验收/复核.txt") == body.encode()
        assert remote(repo, "show", "HEAD:prompts/README.md").endswith(b"Local editorial note.\n")
        head = remote(repo, "rev-parse", "HEAD")
        http.delete(url, headers=rev).raise_for_status()
        assert remote(repo, "rev-parse", "HEAD") == head


def test_fresh_checkout_uses_catalog_once_and_keeps_local_deletion(fake_home):
    root = prompt_catalog.PROJECT / "prompts"
    source = {"title": "读书", "category": "", "path": "未分类/读书.txt"}
    key = uuid4().hex
    body = b"\r\nkeep newlines\r\n"
    path = root / source["path"]
    path.parent.mkdir(parents=True)
    path.write_bytes(body)
    (root / "catalog.json").write_bytes(prompt_catalog.catalog_bytes({key: source}))
    assert prompts.load_book().items[key].body.encode() == body
    with TestClient(create_app()) as http:
        token = http.get("/api/session").json()["token"]
        http.delete("/api/prompts/" + key, headers={"X-Skilldesk-Token": token, "If-Match": "1"}).raise_for_status()
    assert not prompts.load_book().items


def test_same_titles_and_equivalent_filenames_keep_both_prompts(fake_home, publication_remote):
    repo = publication_remote
    with TestClient(create_app()) as http:
        http.headers["X-Skilldesk-Token"] = http.get("/api/session").json()["token"]
        for title, body in [("A/B", "first"), ("A B", "second")]:
            url = "/api/prompts/" + uuid4().hex
            http.put(url, headers={"If-Match": "0"}, json={"title": title, "body": body}).raise_for_status()
            rev = {"If-Match": "1"}
            preview = http.post(url + "/publication/preview", headers=rev).json()
            http.post(url + "/publication", headers=rev, json={"base": preview["base"]}).raise_for_status()
    items = prompt_catalog.read_catalog(remote(repo, "show", "HEAD:prompts/catalog.json"))
    assert {info["title"]: remote(repo, "show", "HEAD:prompts/" + info["path"]) for info in items.values()} == {
        "A/B": b"first", "A B": b"second",
    }


@pytest.mark.parametrize("path", ["../drafts.txt", "/root/file.txt", "设计/a/b.txt", ".git/config"])
def test_catalog_rejects_paths_outside_prompt_folders(path):
    info = {"title": "示例", "category": "测试", "path": path}
    with pytest.raises(ValueError):
        prompt_catalog.read_catalog(prompt_catalog.catalog_bytes({uuid4().hex: info}))
