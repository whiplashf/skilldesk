import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from helpers import lock_entry, write_lockfile, write_skill
from skilldesk import upstream
from skilldesk.server import create_app


def test_global_run_uses_effective_sources_and_preserves_partial_results(fake_home, monkeypatch):
    root = fake_home / ".agents/skills"
    names = ["a-mine", "b-drift", "c-baseline", "d-unresolved", "e-quota", "f-later", "no-path", "offline"]
    for name in names:
        write_skill(root, name)
    (fake_home / ".claude/skills/alias-drift").symlink_to(root / "b-drift")
    locked = {name: lock_entry("example/source", name + "/SKILL.md") for name in names[1:6]}
    locked["no-path"] = lock_entry("example/incomplete", "")
    write_lockfile(fake_home, locked)
    calls = []

    def check(item, source, force, *, batch):
        assert force
        calls.append((item["name"], source["repo"]))
        if item["name"] == "d-unresolved":
            raise ValueError("仓库无法访问")
        if item["name"] == "e-quota":
            raise upstream.QuotaExhausted(int(time.time()) + 300)
        status = {"a-mine": "release", "b-drift": "changed", "c-baseline": "baseline"}[item["name"]]
        return {"status": status, "latest": "v2" if status == "release" else ""}

    monkeypatch.setattr(upstream, "check", check)
    with TestClient(create_app()) as client:
        headers = {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}
        mine = client.get("/api/index", params={"q": "a-mine"}).json()["items"][0]
        response = client.patch("/api/assets/" + mine["identity_key"], headers={**headers, "If-Match": "0"},
                                json={"mine": True, "github": {"repo": "me/project", "path": "SKILL.md"}})
        response.raise_for_status()
        assert client.post("/api/check-all", headers=headers).status_code == 202
        report = client.get("/api/check-all").json()
        assert calls == [(names[0], "me/project"), *((name, "example/source") for name in names[1:5])]
        assert (report["total"], report["untracked"], report["checked"], report["uncertain"]) == (6, 2, 3, 1)
        assert [(row["name"], row["status"]) for row in report["updates"]] == [("a-mine", "release"), ("b-drift", "changed")]
        assert [f["name"] for f in report["failures"]] == names[3:5]
        assert "额度已用完" in report["error"] and report["finishedAt"] > 0 and not report["running"]


def test_repeated_start_shares_the_running_check(fake_home, monkeypatch):
    root = fake_home / ".agents/skills"
    write_skill(root, "sample")
    write_lockfile(fake_home, {"sample": lock_entry("team/one", "SKILL.md")})
    enter, resume = threading.Event(), threading.Event()
    attempts = []

    def check(item, source, force, *, batch):
        attempts.append(item["identity_key"])
        enter.set()
        assert resume.wait(10)
        return {"status": "current", "latest": ""}

    monkeypatch.setattr(upstream, "check", check)
    with TestClient(create_app()) as client, ThreadPoolExecutor(max_workers=1) as pool:
        headers = {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}
        first = pool.submit(client.post, "/api/check-all", headers=headers)
        try:
            assert enter.wait(5)
            assert client.get("/api/check-all").json()["running"]
            assert client.post("/api/check-all", headers=headers).json()["running"]
        finally:
            resume.set()
        assert first.result(timeout=5).status_code == 202
        done = client.get("/api/check-all").json()
        assert len(attempts) == done["checked"] == 1 and not done["running"]


def test_global_check_empty_scope_stays_local(fake_home, monkeypatch):
    write_skill(fake_home / ".agents/skills", "only-local")

    def unexpected(*args, **kwargs):
        raise AssertionError("A local-only inventory should not contact GitHub")

    monkeypatch.setattr(upstream, "http_client", unexpected)
    with TestClient(create_app()) as client:
        headers = {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}
        client.post("/api/check-all", headers=headers).raise_for_status()
        report = client.get("/api/check-all").json()
        assert report["total"] == report["checked"] == 0 and report["untracked"] == 1 and not report["error"]
