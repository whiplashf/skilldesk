import re
import threading

from playwright.sync_api import expect
from skilldesk import categories


def test_setup_filter_correct_and_return_on_mobile(page, monkeypatch):
    tab, _ = page
    monkeypatch.setattr(categories, "chat_json", lambda *_: [{"id": 0, "category": "web-design"}])
    tab.goto("/#/library?agent=codex", wait_until="networkidle")
    start = tab.get_by_role("button", name=re.compile("AI 分类 · 全库 1 项待处理"))
    start.click()
    dialog = tab.get_by_role("dialog", name="设置 AI 功能分类")
    expect(dialog).to_be_visible()
    tab.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    start.click()
    dialog.get_by_label("兼容 OpenAI 的服务地址").fill("http://local.invalid/v1")
    dialog.get_by_label("模型", exact=True).fill("fixture")
    dialog.get_by_role("button", name="保存并开始分类").click()
    expect(dialog).to_have_count(0)
    expect(tab.get_by_text("已完成 1 项分类")).to_be_visible()
    expect(start).to_have_count(0)
    design = tab.get_by_role("button", name=re.compile("^页面设计"))
    design.click()
    expect(design).to_have_attribute("aria-pressed", "true")
    expect(tab.locator(".row-name")).to_have_text("sample")
    tab.get_by_text("功能分类 页面设计", exact=True).click()
    tab.get_by_label("调整分类").select_option("code-review")
    expect(tab.locator(".row-name")).to_have_count(0)
    expect(design).to_have_text("页面设计0")
    tab.get_by_role("button", name="撤销", exact=True).click()
    expect(tab.locator(".row-name")).to_have_text("sample")
    expect(design).to_have_text("页面设计1")
    tab.set_viewport_size({"width": 390, "height": 844})
    select = tab.get_by_role("combobox", name="按功能筛选", exact=True)
    expect(select).to_have_value("web-design")
    select.select_option("")
    select.select_option("web-design")
    tab.locator("button.row").click()
    tab.get_by_role("link", name="← 返回列表").click()
    expect(select).to_have_value("web-design")
    assert "agent=codex" in tab.url and "category=web-design" in tab.url
    tab.reload()
    expect(select).to_have_value("web-design")
    assert tab.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_pause_finishes_one_batch_and_resume_skips_it(page, fake_home, monkeypatch):
    tab, _ = page
    extra = fake_home / ".agents/skills/second"
    extra.mkdir()
    (extra / "SKILL.md").write_text("# Second skill")
    monkeypatch.setenv("SKILLDESK_AI_BASE_URL", "http://local.invalid/v1")
    monkeypatch.setenv("SKILLDESK_AI_MODEL", "fixture")
    monkeypatch.setattr(categories, "BATCH_SIZE", 1)
    release = threading.Event()
    calls = []

    def classify(_client, _settings, _instruction, items):
        calls.append(items[0]["name"])
        assert release.wait(timeout=15)
        return [{"id": 0, "category": "testing"}]

    monkeypatch.setattr(categories, "chat_json", classify)
    tab.goto("/#/library", wait_until="networkidle")
    tab.get_by_role("button", name="重新扫描本机").click()
    tab.get_by_role("button", name=re.compile("全库 2 项待处理")).click()
    try:
        tab.get_by_role("button", name="暂停分类").click()
        expect(tab.get_by_role("button", name="将在本批完成后暂停")).to_be_disabled()
    finally:
        release.set()
    expect(tab.get_by_text("已暂停，已完成 1 项分类")).to_be_visible()
    assert calls == ["sample"]
    tab.get_by_role("button", name=re.compile("全库 1 项待处理")).click()
    expect(tab.get_by_text("已完成 1 项分类", exact=True)).to_be_visible()
    assert calls == ["sample", "second"]
