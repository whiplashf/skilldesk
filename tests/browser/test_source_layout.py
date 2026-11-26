import json
import re

import pytest
from playwright.sync_api import expect


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
def test_repository_bookmark_paging_and_batch_check(page):
    tab, _ = page
    batches = []

    def checked(route):
        keys = route.request.post_data_json["keys"]
        batches.append(keys)
        route.fulfill(json={"items": [{"key": key} for key in keys]})

    tab.route("**/api/check-batch", checked)
    tab.goto("/#/library?view=github&layout=repository&repo=github.com%2Fteam%2Fleft&page=2", wait_until="networkidle")
    expect(tab.locator(".row-name")).to_have_text(["left-50", "left-51"])
    opposite = tab.get_by_role("button", name="team/right")
    opposite.click()
    expect(tab.locator(".row-name")).to_have_count(5)
    tab.get_by_role("button", name="上一页").click()
    expect(tab.locator(".row-name")).to_have_count(53)
    tab.get_by_role("button", name="检查已展开项的版本").click()
    expect(tab.get_by_text("已检查 53 项", exact=True)).to_be_visible()
    assert [len(batch) for batch in batches] == [50, 3]
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
