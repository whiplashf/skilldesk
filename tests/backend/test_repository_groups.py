"""The repository directory is computed across the filtered inventory, before paging."""

import json
import subprocess

from fastapi.testclient import TestClient
from helpers import lock_entry, write_lockfile, write_skill
from skilldesk.config import config_dir
from skilldesk.server import create_app


def test_groups_count_full_results_and_page_inside_repository(fake_home):
    store = fake_home / ".agents/skills"
    records = {}
    for i in range(54):
        name = f"topic-{i:02d}"
        write_skill(store, name)
        records[name] = lock_entry("Owner/Pack" if i % 2 else "owner/pack", f"skills/{name}/SKILL.md")
    write_skill(store, "alpha")
    records["alpha"] = lock_entry("another/pack", "alpha/SKILL.md")
    write_lockfile(fake_home, records)
    with TestClient(create_app()) as client:

        def index(**params):
            response = client.get("/api/index", params={"view": "github", "by_repository": True, **params})
            response.raise_for_status()
            return response.json()

        first = index()
        assert [(g["key"], g["count"]) for g in first["repositories"]] == [
            ("github.com/another/pack", 1),
            ("github.com/owner/pack", 54),
        ]
        assert first["matchedTotal"] == 55 and first["total"] == 1
        group = "github.com/owner/pack"
        last = index(repository=group, offset=50)
        assert [item["name"] for item in last["items"]] == [f"topic-{i}" for i in range(50, 54)]
        assert last["total"] == 54 and last["offset"] == 50
        deep = index(focus=last["items"][-1]["identity_key"])
        assert (deep["activeRepository"], deep["offset"]) == (group, 50)
        assert index(q="alpha", repository=group, offset=50)["items"][0]["name"] == "alpha"
        assert index(agent="claude")["repositories"] == []
        assert index(by_repository=False)["total"] == 55

        def layout(name, **params):
            response = client.get("/api/index", params={"view": "github", "layout": name, **params})
            response.raise_for_status()
            return response.json()

        directory = layout("sources")
        assert directory["total"] == 55 and not directory["items"]
        assert [g["page"] for g in directory["repositories"]] == [0, 0]
        other = "github.com/another/pack"
        both = layout("sources", group_pages=json.dumps({group: 2, other: 1}))
        assert [i["name"] for i in both["items"]] == ["alpha", *[f"topic-{i}" for i in range(50, 54)]]
        assert both["total"] == 55
        linked = layout("sources", repository=group, offset=50)
        assert [i["name"] for i in linked["items"]] == [i["name"] for i in last["items"]]
        key = linked["items"][-1]["identity_key"]
        assert layout("flat", focus=key)["offset"] == 50
        assert layout("sources", focus=key)["repositories"][1]["page"] == 2
        folded = layout("sources", focus=key, group_pages=json.dumps({group: 0, other: 1}))
        assert folded["total"] == 55 and [i["name"] for i in folded["items"]] == ["alpha"]
        single = layout("sources", q="alpha", group_pages=json.dumps({other: 0}))
        assert single["total"] == 1 and single["items"][0]["name"] == "alpha"
        assert client.get("/api/index", params={"layout": "sources", "group_pages": '{"bad":-1}'}).status_code == 422


def test_effective_source_and_local_checkouts_in_mine(fake_home, tmp_path):
    project = tmp_path / "workspace"
    store = fake_home / ".agents/skills"
    for prefix in ("a", "b"):
        checkout = project / prefix / "my-skills"
        checkout.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        folder = write_skill(checkout, prefix + "-private")
        (store / folder.name).symlink_to(folder)
    write_skill(store, "loose")
    write_skill(store, "mapped")
    write_skill(store, "copy")
    write_lockfile(
        fake_home,
        {
            "mapped": lock_entry("old/pack", "skills/mapped/SKILL.md"),
            "copy": {"sourceType": "local", "source": str(project / "a/my-skills/a-private")},
        },
    )
    with TestClient(create_app()) as client:
        headers = {"X-Skilldesk-Token": client.get("/api/session").json()["token"]}
        items = client.get("/api/index").json()["items"]
        for item in items:
            revision = client.get("/api/library").json()["revision"]
            changes = {"mine": True, "favorite": item["name"] == "mapped"}
            if item["name"] == "mapped":
                changes["github"] = {"repo": "my-team/new-source", "path": "mapped/SKILL.md"}
            client.patch(
                "/api/assets/" + item["identity_key"],
                headers={**headers, "If-Match": str(revision)},
                json=changes,
            ).raise_for_status()

        def index(view, **params):
            return client.get("/api/index", params={"by_repository": True, "view": view, **params}).json()

        mine = index("mine")
        counts = {group["key"]: group["count"] for group in mine["repositories"]}
        assert counts == {
            "github.com/my-team/new-source": 1,
            f"local:{project}/a/my-skills": 2,
            f"local:{project}/b/my-skills": 1,
            "unassigned": 1,
        }
        assert mine["repositories"][-1]["key"] == "unassigned"
        assert index("mine", repository="unassigned")["items"][0]["name"] == "loose"
        assert index("github")["matchedTotal"] == 0
        favorites = index("favorites")
        assert (
            favorites["items"][0]["repository"]["key"]
            == favorites["activeRepository"]
            == "github.com/my-team/new-source"
        )
        assert json.loads((config_dir() / "library.json").read_text())["revision"] == len(items)


def test_local_copies_and_unpublished_files_share_their_checkout_repository(fake_home, tmp_path):
    checkout = tmp_path / "my tools"
    checkout.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(checkout), *args], check=True, capture_output=True)

    git("init", "-q")
    git("remote", "add", "origin", "git@github.com:example/my-tools.git")
    store = fake_home / ".agents/skills"
    published = write_skill(checkout, "published")
    git("add", "published")
    git("-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "first")
    draft = write_skill(checkout, "draft")
    for folder in (published, draft):
        (store / folder.name).symlink_to(folder)
    write_skill(store, "copied-draft")
    write_skill(store, "docs-package")
    write_lockfile(
        fake_home,
        {
            "copied-draft": {"sourceType": "local", "sourceUrl": draft.as_uri()},
            "docs-package": {
                "sourceType": "well-known",
                "sourceUrl": "https://example.org/docs/skills/package",
            },
        },
    )

    with TestClient(create_app()) as client:
        result = client.get("/api/index", params={"by_repository": True}).json()
        assert [(g["key"], g["count"]) for g in result["repositories"]] == [
            ("github.com/example/my-tools", 3),
            ("provider:example.org", 1),
        ]
        assert {item["name"] for item in result["items"]} == {"published", "draft", "copied-draft"}
        for item in result["items"]:
            assert item["repository"]["key"] == result["activeRepository"]
            assert item["provenance"]["localRoot"] == str(checkout)
            assert bool(item["upstream"]) == (item["name"] == "published")
        provided = client.get(
            "/api/index", params={"by_repository": True, "repository": "provider:example.org"}
        ).json()
        assert provided["items"][0]["repository"] == {
            "key": "provider:example.org", "name": "example.org", "location": "提供方",
        }
