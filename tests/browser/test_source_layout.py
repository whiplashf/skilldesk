import json
import re
import threading
import time

import pytest
from playwright.sync_api import expect
from skilldesk import upstream


@pytest.fixture
def two_sources(fake_home):
    root = fake_home / ".agents/skills"
    records = {}
    for i in range(6):
        name = f"tool-{i}"
        folder = root / name
        folder.mkdir()
        (folder / "SKILL.md").write_text(f"---\nname: {name}\n---\nBody for {name}.")
        records[name] = {"source": "team/review" if i % 3 == 0 else "team/design",
                         "sourceType": "github", "skillPath": f"{name}/SKILL.md"}
    (root.parent / ".skill-lock.json").write_text(json.dumps({"skills": records}))


@pytest.mark.usefixtures("two_sources")
@pytest.mark.parametrize("width", [1280, 390])
def test_group_in_place_fold_return_and_name_order(page, width):
    tab, _ = page
    tab.set_viewport_size({"width": width, "height": 844})
    tab.goto("/#/library?view=github&q=tool&agent=codex&layout=repository", wait_until="networkidle")
    switch = tab.get_by_role("switch", name="按来源分组")
    expect(switch).to_be_checked()
    expect(tab.locator(".pane-count")).to_have_text("共 6 个 skill · 2 个来源")
    design = tab.get_by_role("button", name="team/design")
    review = tab.get_by_role("button", name="team/review")
    expect(tab.locator(".row-name")).to_have_count(6)
    design.click()
    expect(design).to_have_attribute("aria-expanded", "false")
    expect(tab.locator(".row-name")).to_have_text(["tool-0", "tool-3"])
    review.click()
    expect(tab.locator(".row-name")).to_have_count(0)
    expect(tab.locator(".pane-count")).to_contain_text("共 6 个")
    expect(tab.get_by_text("没有匹配的 skill")).to_have_count(0)
    review.focus()
    tab.keyboard.press("Enter")
    tab.get_by_role("button", name=re.compile("^tool-3")).click()
    expect(tab.locator(".reader-heading h1")).to_have_text("tool-3")
    if width == 390:
        tab.get_by_role("link", name="← 返回列表").click()
    switch.uncheck()
    expect(tab.locator(".row-name")).to_have_text([f"tool-{i}" for i in range(6)])
    if width > 860:
        expect(tab.locator(".reader-heading h1")).to_have_text("tool-3")
    switch.check()
    expect(design).to_have_attribute("aria-expanded", "false")
    expect(review).to_have_attribute("aria-expanded", "true")
    assert "q=tool" in tab.url and "agent=codex" in tab.url
    assert tab.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    tab.get_by_role("searchbox").fill("tool-1")
    expect(switch).to_have_count(0)
    expect(tab.locator(".row-name")).to_have_text("tool-1")


@pytest.fixture
def large_sources(fake_home):
    root = fake_home / ".agents/skills"
    records = {}
    for prefix, count in (("left", 52), ("right", 3)):
        for i in range(count):
            name = f"{prefix}-{i:02d}"
            folder = root / name
            folder.mkdir()
            (folder / "SKILL.md").write_text(f"# {name}")
            records[name] = {"source": "team/" + prefix, "sourceType": "github", "skillPath": f"{name}/SKILL.md"}
    (root.parent / ".skill-lock.json").write_text(json.dumps({"skills": records}))


@pytest.mark.usefixtures("large_sources")
def test_repository_bookmark_paging(page):
    tab, _ = page
    tab.goto("/#/library?view=github&layout=repository&repo=github.com%2Fteam%2Fleft&page=2", wait_until="networkidle")
    expect(tab.locator(".row-name")).to_have_text(["left-50", "left-51"])
    opposite = tab.get_by_role("button", name="team/right")
    opposite.click()
    expect(tab.locator(".row-name")).to_have_count(5)
    tab.get_by_role("button", name="上一页").click()
    expect(tab.locator(".row-name")).to_have_count(53)
    tab.get_by_role("button", name="下一页").click()
    tab.get_by_role("button", name=re.compile("^left-51")).click()
    switch = tab.get_by_role("switch", name="按来源分组")
    switch.uncheck()
    expect(tab.locator(".pager-state")).to_have_text("第 2 / 2 页")
    expect(tab.locator(".reader-heading h1")).to_have_text("left-51")
    switch.check()
    expect(tab.locator(".source-heading")).to_have_count(2)
    expect(tab.locator(".row-name")).to_have_count(5)
    expect(tab.locator(".row[aria-current=true]")).to_contain_text("left-51")
    expect(tab.locator(".row[aria-current=true]")).to_be_in_viewport(ratio=1)
    source = tab.get_by_role("button", name="team/left")
    source.click()
    expect(tab.locator(".row-name")).to_have_count(3)
    source.click()
    expect(tab.locator(".pager-state")).to_have_text("第 2 / 2 页")
    expect(tab.locator(".row-name")).to_have_count(5)


@pytest.mark.usefixtures("large_sources")
@pytest.mark.parametrize(("width", "query", "visible"), [
    (1280, "view=github&layout=repository&repo=github.com%2Fteam%2Fleft&page=2", 2),
    (390, "view=favorites&q=missing&agent=codex&category=other", 0),
])
def test_global_updates_include_hidden_skills_and_preserve_library_position(page, monkeypatch, width, query, visible):
    calls = []

    def check(item, source, force, *, batch):
        calls.append(item["name"])
        status = {"left-01": "no_release", "right-00": "release"}.get(item["name"], "current")
        return {"status": status, "latest": "v2.0" if status == "release" else "", "release": {
            "tag": "v2.0", "commit": "a" * 40, "publishedAt": "2026-04-01T01:02:03Z", "title": "Better setup",
            "url": "https://github.com/team/right/releases/tag/v2.0", "body": "The guide now covers Windows."}}

    monkeypatch.setattr(upstream, "check", check)
    tab, _ = page
    tab.set_viewport_size({"width": width, "height": 844})
    tab.goto("/#/library?" + query, wait_until="networkidle")
    expect(tab.locator(".row-name")).to_have_count(visible)
    assert calls == []
    tab.get_by_role("button", name="检查全部更新").click()
    panel = tab.get_by_role("region", name="全库版本检查")
    expect(panel.get_by_role("heading", name="1 个技能有更新")).to_be_visible()
    expect(panel).to_contain_text("已检查 55 / 55 项")
    expect(panel).to_contain_text("1 个技能缺少可检查的 GitHub 来源")
    expect(panel.get_by_role("link", name=re.compile("^left-01"))).to_have_count(0)
    expect(panel).to_contain_text("1 项暂无正式版")
    expect(panel).to_contain_text("The guide now covers Windows.")
    expect(panel.get_by_role("link", name=re.compile("^right-00"))).to_contain_text("有新版本")
    assert len(calls) == len(set(calls)) == 55
    assert tab.url.endswith(query) and tab.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    tab.reload(wait_until="networkidle")
    tab.get_by_role("button", name="查看全库检查结果").click()
    panel.get_by_role("link", name=re.compile("^right-00")).click()
    expect(tab.locator(".reader-heading h1")).to_have_text("right-00")
    assert query in tab.url and len(calls) == 55


@pytest.mark.usefixtures("two_sources")
def test_global_check_keeps_running_while_browsing_and_reports_quota(page, monkeypatch):
    resume = threading.Event()
    calls = []

    def check(item, source, force, *, batch):
        calls.append(item["name"])
        if len(calls) == 1:
            assert resume.wait(15)
            return {"status": "release", "latest": "v2", "release": {"tag": "v2", "commit": "a" * 40, "body": "",
                    "title": "", "publishedAt": "", "url": "https://github.com/team/design/releases/tag/v2"}}
        raise upstream.QuotaExhausted(int(time.time()) + 300)

    monkeypatch.setattr(upstream, "check", check)
    tab, _ = page
    tab.goto("/#/library")
    tab.get_by_role("button", name="检查全部更新").click()
    panel = tab.get_by_role("region", name="全库版本检查")
    try:
        expect(panel.get_by_role("heading", name="正在检查全库…")).to_be_visible()
        tab.get_by_role("link", name="设置", exact=True).click()
        tab.get_by_role("link", name="本机技能库", exact=True).click()
        tab.get_by_role("button", name="查看全库检查结果").click()
    finally:
        resume.set()
    expect(panel.get_by_role("heading", name="1 个技能有更新")).to_be_visible()
    expect(panel.get_by_role("alert")).to_contain_text("额度已用完")
    expect(panel).to_contain_text("1 项失败 · 4 项尚未检查")
    panel.locator("summary").click()
    expect(panel.get_by_role("link", name=calls[1], exact=True)).to_be_visible()
    assert len(calls) == 2
