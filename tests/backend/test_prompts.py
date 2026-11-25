from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from skilldesk.server import create_app


@pytest.fixture
def client(fake_home):
    with TestClient(create_app()) as http:
        http.headers["X-Skilldesk-Token"] = http.get("/api/session").json()["token"]
        yield http


def test_prompt_text_and_categories_survive_reindex_and_restart(client):
    url = "/api/prompts/" + uuid4().hex
    assert client.get("/api/prompts").json() == {"items": []}
    body = "\n  分步说明\n\n    keep indentation\n"
    draft = {"body": body, "category": "  Design  "}
    created = client.put(url, headers={"If-Match": "0"}, json=draft).json()
    assert (created["title"], created["category"], created["body"]) == ("分步说明", "Design", body)
    assert client.put(url, headers={"If-Match": "0"}, json=draft).json() == created
    second = client.put("/api/prompts/" + uuid4().hex, headers={"If-Match": "0"},
                        json={"body": "Another", "category": "design"}).json()
    assert second["category"] == "Design"
    client.post("/api/scan").raise_for_status()
    with TestClient(create_app()) as reopened:
        assert reopened.get("/api/prompts").json()["items"] == [second, created]


def test_prompt_writes_validation_and_unreadable_storage(client, fake_home):
    url = "/api/prompts/" + uuid4().hex
    assert client.put(url, json={"body": "Text"}, headers={"If-Match": "0", "X-Skilldesk-Token": ""}).status_code == 403
    assert client.put(url, json={"body": "  \n "}, headers={"If-Match": "0"}).status_code == 400
    assert client.put(url, json={"body": "x" * 200_001}, headers={"If-Match": "0"}).status_code == 422
    storage = fake_home / ".config/skilldesk/prompts.json"
    storage.parent.mkdir(parents=True, exist_ok=True)
    storage.write_text("{damaged")
    assert client.get("/api/prompts").status_code == 500
    assert client.put(url, json={"body": "Text"}, headers={"If-Match": "0"}).status_code == 500
    assert storage.read_text() == "{damaged"


def test_conflicts_delete_retry_and_undo_keep_later_edits(client):
    url = "/api/prompts/" + uuid4().hex
    client.put(url, headers={"If-Match": "0"}, json={"body": "Original"}).raise_for_status()
    with ThreadPoolExecutor(2) as pool:
        edits = list(pool.map(lambda text: client.put(url, headers={"If-Match": "1"}, json={"body": text}), ["A", "B"]))
    assert sorted(response.status_code for response in edits) == [200, 409]
    latest = next(response.json() for response in edits if response.status_code == 200)
    assert client.delete(url, headers={"If-Match": "1"}).status_code == 409
    deleted = client.delete(url, headers={"If-Match": "2"}).json()
    assert client.delete(url, headers={"If-Match": "2"}).json() == deleted
    assert not client.get("/api/prompts").json()["items"]
    assert client.put(url, headers={"If-Match": "0"}, json={"body": "Original"}).status_code == 409
    restored = client.put(url, headers={"If-Match": str(deleted["revision"])}, json={"body": latest["body"]}).json()
    assert (restored["id"], restored["body"], restored["revision"]) == (latest["id"], latest["body"], 4)
    assert client.delete(url, headers={"If-Match": "2"}).status_code == 409
