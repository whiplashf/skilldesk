import json

import httpx
import pytest
from fastapi.testclient import TestClient
from helpers import lock_entry, write_lockfile, write_skill
from skilldesk import categories
from skilldesk.server import create_app


def write_headers(client):
    return {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}


def provider(monkeypatch, respond):
    def handle(_transport, request):
        assert str(request.url) == "https://ai.example.invalid/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer example-key"
        data = json.loads(request.content)
        assert data["model"] == "example-model" and data["messages"][0]["role"] == "system"
        payload = json.loads(data["messages"][1]["content"])
        result = respond(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}}]})

    monkeypatch.setenv("SKILLDESK_AI_BASE_URL", "https://ai.example.invalid/v1")
    monkeypatch.setenv("SKILLDESK_AI_MODEL", "example-model")
    monkeypatch.setenv("SKILLDESK_AI_API_KEY", "example-key")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)


def test_classify_validates_description_and_resumes_after_failed_batch(fake_home, monkeypatch):
    store = fake_home / ".agents/skills"
    write_skill(store, "alpha", description="Review existing code", body="Omit this body entirely.")
    fallback = write_skill(store, "bravo")
    (fallback / "SKILL.md").write_text("---\nname: bravo\n---\n" + "界" * 700)
    write_skill(store, "charlie")
    monkeypatch.setattr(categories, "BATCH_SIZE", 2)
    calls = []

    def respond(items):
        calls.append(items)
        assert all(set(item) == {"id", "name", "description"} for item in items)
        if len(calls) == 1:
            assert [i["description"] for i in items] == ["Review existing code", "界" * 600]
            return [{"id": 1, "category": "web-design"}, {"id": 0, "category": "code-review"}]
        assert [item["name"] for item in items] == ["charlie"]
        return [] if len(calls) == 2 else [{"id": 0, "category": "development"}]

    with TestClient(create_app()) as client:
        headers = write_headers(client)
        path = "/api/ai/classify"
        assert client.get("/api/index").json()["pendingCategories"] == 3
        assert client.post(path).status_code == 403
        assert client.post(path, headers=headers).status_code == 501
        provider(monkeypatch, respond)
        assert client.post(path, headers=headers).json() == {"classified": 2, "remaining": 1}
        assert client.post(path, headers=headers).status_code == 502
        assert client.get("/api/index", params={"category": "pending"}).json()["total"] == 1
        assert client.post(path, headers=headers).json() == {"classified": 1, "remaining": 0}
        assert client.post(path, headers=headers).json() == {"classified": 0, "remaining": 0}
    with TestClient(create_app()) as reopened:
        headers = write_headers(reopened)
        assert reopened.get("/api/index").json()["pendingCategories"] == 0
        alpha = reopened.get("/api/index", params={"q": "alpha"}).json()["items"][0]
        assert alpha["category"] == {"key": "code-review", "name": "代码评审", "manual": False}
        file = store / "alpha/SKILL.md"
        file.write_text(file.read_text() + "\nChanged purpose.")
        reopened.post("/api/scan", headers=headers).raise_for_status()
        assert reopened.get("/api/index", params={"category": "pending"}).json()["items"][0]["name"] == "alpha"
    assert len(calls) == 3


@pytest.mark.parametrize("reply", [
    [{"id": 0, "category": "other"}, {"id": 0, "category": "visual"}],
    [{"id": True, "category": "other"}, {"id": 0, "category": "visual"}],
    [{"id": 2, "category": "other"}, {"id": 0, "category": "visual"}],
    [{"id": 0, "category": "pending"}, {"id": 1, "category": "visual"}],
])
def test_invalid_response_leaves_whole_batch_pending(fake_home, monkeypatch, reply):
    for name in ("one", "two"):
        write_skill(fake_home / ".agents/skills", name)
    provider(monkeypatch, lambda _items: reply)
    with TestClient(create_app()) as client:
        headers = write_headers(client)
        assert client.post("/api/ai/classify", headers=headers).status_code == 502
        assert client.get("/api/index").json()["pendingCategories"] == 2
        with categories._classifying:
            assert client.post("/api/ai/classify", headers=headers).status_code == 409
        assert not categories.stored()


def test_category_counts_compose_with_repositories_agents_and_paging(fake_home):
    store = fake_home / ".agents/skills"
    records = {}
    for i in range(55):
        name = f"sample-{i:02d}"
        write_skill(store, name)
        records[name] = lock_entry("example/design" if i < 53 else "example/review", name + "/SKILL.md")
    write_lockfile(fake_home, records)
    write_skill(fake_home / ".claude/skills", "separate")
    with TestClient(create_app()) as client:
        def index(**params):
            return client.get("/api/index", params=params).json()

        groups = {"web-design": 52, "code-review": 3}
        items = index(limit=100)["items"]
        categories.save_results({
            categories.fingerprint(i): "web-design" if i["name"] < "sample-52" else "code-review"
            for i in items if i["name"].startswith("sample")
        }, "fixture")
        result = index(category="web-design", view="github", agent="codex", by_repository=True, offset=50)
        assert {g["key"]: g["count"] for g in result["categories"]} == groups
        assert result["total"] == result["matchedTotal"] == result["repositories"][0]["count"] == 52
        assert result["pendingCategories"] == 1 and len(result["items"]) == 2
        assert index(category="code-review", q="sample-5", by_repository=True)["matchedTotal"] == 3
        empty = index(category="web-design", agent="claude")
        assert empty["total"] == 0
        assert {g["key"]: g["count"] for g in empty["categories"]} == {"web-design": 0, "pending": 1}


def test_manual_choice_survives_rescan_and_can_revert_to_ai(fake_home):
    folder = write_skill(fake_home / ".agents/skills", "sample")
    with TestClient(create_app()) as client:
        headers = write_headers(client)
        item = client.get("/api/index").json()["items"][0]
        path = "/api/assets/" + item["identity_key"]
        detail = "/api/skill/" + item["identity_key"]

        def patch(revision, **changes):
            return client.patch(path, json=changes, headers={**headers, "If-Match": str(revision)})

        assert patch(0, category="invalid").status_code == 400
        categories.save_results({categories.fingerprint(item): "development"}, "fixture")
        assert patch(0, category="testing", favorite=True).json()["category"]["manual"]
        assert patch(0, category=None).status_code == 409
        assert client.get("/api/index?category=testing&view=favorites").json()["total"] == 1
        assert patch(1, category=None).json()["category"]["key"] == "development"
        patch(2, category="testing").raise_for_status()
        (folder / "SKILL.md").write_text("# New purpose")
        client.post("/api/scan", headers=headers).raise_for_status()
        rescanned = client.get(detail).json()
        assert rescanned["category"] == {"key": "testing", "name": "测试调试", "manual": True}
        assert client.post("/api/ai/classify", headers=headers).json()["remaining"] == 0
        updated = patch(rescanned["libraryRevision"], category=None).json()
        assert updated["category"]["key"] == "pending" and updated["favorite"]
