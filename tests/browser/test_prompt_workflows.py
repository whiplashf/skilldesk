import re
import subprocess
from urllib.parse import urlsplit

from playwright.sync_api import expect


def test_explicit_publish_cancel_and_open_published_copy(page, publication_remote):
    tab, _ = page
    tab.set_viewport_size({"width": 390, "height": 844})
    tab.goto("/#/prompts")
    tab.get_by_role("button", name="新建提示词").click()
    body = "请检查表单状态。\n  保留空白。"
    tab.get_by_label("提示词正文").fill(body)
    tab.get_by_role("button", name="保存提示词").click()
    publish = tab.get_by_role("button", name="发布到 GitHub", exact=True)
    dialog = tab.get_by_role("dialog", name="发布到 GitHub")
    publish.click()
    expect(dialog).to_contain_text("test/library")
    dialog.get_by_role("button", name="取消").click()
    expect(dialog).to_have_count(0)
    assert subprocess.check_output(["git", "-C", str(publication_remote), "rev-list", "--count", "HEAD"]).strip() == b"1"
    publish.click()
    dialog.get_by_role("button", name="确认发布").click()
    link = dialog.get_by_role("link", name="在 GitHub 查看")
    expect(link).to_have_attribute("href", re.compile(r"^https://github\.com/test/library/blob/main/prompts/"))
    expect(dialog.get_by_role("heading", name="已发布到 GitHub")).to_be_visible()
    dialog.get_by_role("button", name="关闭").click()
    publish.click()
    expect(dialog.get_by_role("heading", name="与 GitHub 一致")).to_be_visible()
    expect(dialog.get_by_role("button", name="确认发布")).to_have_count(0)
    assert tab.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_save_find_copy_reclassify_and_undo_on_mobile(page):
    tab, requests = page
    tab.set_viewport_size({"width": 390, "height": 844})
    tab.goto("/#/library", wait_until="networkidle")
    requests.clear()  # Measure network access during the prompt workflow.
    tab.get_by_role("link", name="提示词库").click()
    tab.get_by_role("button", name="新建提示词").click()
    body = "审查表单\n\n  保留缩进和列表。\n- 核对输入反馈\n"
    tab.get_by_label("提示词正文").fill(body)
    tab.get_by_label("分类", exact=True).fill("产品设计")
    tab.get_by_role("button", name="稍后继续").click()
    tab.reload()
    tab.get_by_role("button", name="继续草稿").click()
    expect(tab.get_by_label("提示词正文")).to_have_value(body)
    tab.get_by_role("button", name="保存提示词").click()
    row = tab.get_by_role("listitem").filter(has=tab.get_by_role("button", name="审查表单", exact=True))
    expect(row.get_by_role("button", name="复制 审查表单")).to_be_visible()
    tab.reload()
    tab.get_by_role("button", name="产品设计 1").click()
    tab.keyboard.press("/")
    search = tab.get_by_role("searchbox", name="搜索提示词")
    expect(search).to_be_focused()
    search.fill("输入反馈")
    expect(row).to_be_visible()
    search.fill("没有这一段")
    expect(tab.get_by_text("没有匹配的提示词")).to_be_visible()
    search.press("Escape")
    expect(search).to_be_empty()
    origin = tab.url.split("/#")[0]
    tab.context.grant_permissions(["clipboard-write", "clipboard-read"], origin=origin)
    row.get_by_role("button", name="复制 审查表单").click()
    expect(row.get_by_text("已复制", exact=True)).to_be_visible()
    assert tab.evaluate("expected => navigator.clipboard.readText().then(text => text === expected)", body)
    tab.evaluate("navigator.clipboard.writeText('')")
    # A plain HTTP LAN origin has no async clipboard. Exercise the real selection-based copy and paste.
    tab.evaluate("Object.defineProperty(navigator, 'clipboard', {configurable: true, value: undefined})")
    row.get_by_role("button", name="复制 审查表单").click()
    expect(row.get_by_text("已复制", exact=True)).to_be_visible()
    tab.evaluate("() => { const t = document.createElement('textarea'); t.id='paste-check'; document.body.append(t); t.focus(); }")
    tab.keyboard.press("Control+v")
    expect(tab.locator("#paste-check")).to_have_value(body)
    tab.locator("#paste-check").evaluate("element => element.remove()")
    assert tab.evaluate("document.documentElement.scrollWidth <= innerWidth")
    row.get_by_role("button", name="编辑", exact=True).click()
    tab.get_by_label("分类", exact=True).fill("验收")
    tab.get_by_role("button", name="保存提示词").click()
    expect(tab.get_by_role("button", name="验收 1")).to_have_attribute("aria-pressed", "true")
    row.get_by_role("button", name="删除…").click()
    row.get_by_role("button", name="确认删除").click()
    expect(tab.get_by_text("还没有提示词", exact=True)).to_be_visible()
    tab.get_by_role("button", name="撤销").click()
    expect(row.locator("pre")).to_have_text(body)
    assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)


def test_concurrent_edit_keeps_draft_and_clipboard_failure_exposes_original(page):
    tab, _ = page
    tab.goto("/#/prompts")
    tab.get_by_role("button", name="新建提示词").click()
    tab.get_by_label("标题", exact=True).fill("发布检查")
    tab.get_by_label("提示词正文").fill("保留换行\n  校对标题")
    tab.get_by_role("button", name="保存提示词").click()
    tab.get_by_role("button", name="编辑", exact=True).click()
    tab.get_by_label("提示词正文").fill("我的草稿\n  第二行")
    other = tab.context.new_page()
    other.goto("/#/prompts")
    other.get_by_role("button", name="编辑", exact=True).click()
    other.get_by_label("提示词正文").fill("另一窗口的改动")
    other.get_by_role("button", name="保存提示词").click()
    expect(other.get_by_text("另一窗口的改动", exact=True)).to_be_visible()
    tab.get_by_role("button", name="保存提示词").click()
    expect(tab.get_by_role("dialog").get_by_role("alert")).to_contain_text("其他窗口")
    tab.get_by_role("button", name="另存为副本").click()
    expect(tab.get_by_role("listitem")).to_have_count(2)
    row = tab.get_by_role("listitem").filter(has_text="我的草稿")
    tab.evaluate("Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: () => Promise.reject()}})")
    tab.evaluate("document.execCommand = () => false")
    row.get_by_role("button", name="复制 发布检查").click()
    field = row.get_by_role("textbox")
    expect(field).to_be_focused()
    expect(field).to_have_value("我的草稿\n  第二行")
    assert field.evaluate("f => f.selectionStart === 0 && f.selectionEnd === f.value.length")
    expect(row.get_by_text("已复制", exact=True)).to_have_count(0)


def test_find_across_categories_and_create_in_the_selected_category(page):
    tab, requests = page
    tab.goto("/#/prompts", wait_until="networkidle")
    assert not any("/api/health" in url or "/api/index" in url for url in requests)
    for body, category in [("界面审查\n核对反馈", "设计"), ("发布前整理\n核对交付", "")]:
        tab.get_by_role("button", name="新建提示词").click()
        tab.get_by_label("提示词正文").fill(body)
        tab.get_by_label("分类", exact=True).fill(category)
        tab.get_by_role("button", name="保存提示词").click()
        expect(tab.get_by_role("dialog")).to_have_count(0)
    expect(tab.get_by_role("listitem")).to_have_count(2)
    tab.get_by_role("button", name="未分类 1").click()
    expect(tab.get_by_role("listitem")).to_have_count(1)
    expect(tab.get_by_role("button", name="发布前整理", exact=True)).to_be_visible()
    tab.get_by_role("button", name="设计 1").click()
    expect(tab.get_by_role("button", name="发布前整理", exact=True)).to_have_count(0)
    tab.get_by_role("button", name="新建提示词").click()
    expect(tab.get_by_label("分类", exact=True)).to_have_value("设计")
    tab.get_by_role("button", name="取消", exact=True).click()
    tab.get_by_role("button", name="全部 2").click()
    tab.get_by_role("searchbox").fill("核对")
    expect(tab.get_by_role("listitem")).to_have_count(2)
    tab.get_by_role("searchbox").fill("交付")
    expect(tab.get_by_role("listitem")).to_have_count(1)
    expect(tab.get_by_role("button", name="复制 发布前整理")).to_be_visible()
