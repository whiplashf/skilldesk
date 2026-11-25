"""Browser regressions that depend on layout, focus or an actual user gesture."""

import socket
import threading

import pytest
import uvicorn
from playwright.sync_api import expect, sync_playwright
from skilldesk import translation
from skilldesk.server import FRONTEND_DIST, create_app


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright, playwright.chromium.launch() as chromium:
        yield chromium


@pytest.fixture
def page(browser, fake_home, monkeypatch):
    assert (FRONTEND_DIST / "index.html").is_file(), "Build the frontend before running the browser tests"
    folder = fake_home / ".agents/skills/sample"
    folder.mkdir()
    body = ("1. Run these commands\n   ~~~sh\n   cd sample\n   npm test\n   ~~~\n2. Continue\n\n"
            "See [guide](guide.md). ![badge](https://images.example.invalid/badge)")
    (folder / "SKILL.md").write_text("---\nname: sample\n---\n" + body)
    (folder / "guide.md").write_text(body)
    monkeypatch.setattr(translation, "_translate_batch", lambda _client, _cfg, texts: ["中文" for _ in texts])
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
        listener.listen()
        server = uvicorn.Server(uvicorn.Config(create_app(), log_level="error"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
        worker.start()
        try:
            with browser.new_context(base_url=origin) as context:
                requests = []

                def local_only(route):
                    requests.append(route.request.url)
                    if route.request.url.startswith(origin + "/"):
                        route.continue_()
                    else:
                        route.abort()

                context.route("**/*", local_only)
                yield context.new_page(), requests
        finally:
            server.should_exit = True
            worker.join(timeout=10)


def test_mobile_offline_reading_translation_and_favorite_undo(page):
    tab, requests = page
    tab.set_viewport_size({"width": 390, "height": 844})
    tab.goto("/#/library", wait_until="networkidle")
    row = tab.locator("button.row")
    expect(row).to_be_visible()
    assert not any("/api/skill/" in url for url in requests)
    row.click()
    code = tab.locator(".reader-body ol pre code")
    expect(code).to_have_count(1)
    assert code.text_content() == "cd sample\nnpm test"
    tab.get_by_role("button", name="设置中文翻译").click()
    tab.get_by_label("兼容 OpenAI 的服务地址").fill("http://local.invalid/v1")
    tab.get_by_label("模型", exact=True).fill("fixture")
    tab.get_by_role("button", name="保存并翻译这篇").click()
    expect(tab.get_by_role("button", name="查看原文")).to_be_visible()
    assert code.text_content() == "cd sample\nnpm test"
    assert not any("images.example.invalid" in url or url.endswith("/files") for url in requests)
    tab.locator(".star-action").click()
    expect(tab.locator(".star-action")).to_have_attribute("aria-pressed", "true")
    tab.goto("/#/library?view=favorites&agent=codex")
    tab.get_by_role("button", name="取消收藏 sample").click()
    expect(tab.get_by_text("还没有收藏", exact=True)).to_be_visible()
    tab.get_by_role("button", name="撤销").click()
    expect(tab.get_by_role("button", name="取消收藏 sample")).to_be_visible()
    assert "view=favorites&agent=codex" in tab.url


def test_search_shortcuts_leave_filters_and_document_focus_intact(page):
    tab, _ = page
    tab.goto("/#/library?agent=codex&q=sample", wait_until="networkidle")
    link = tab.get_by_role("link", name="guide", exact=True)
    link.focus()
    tab.keyboard.press("ArrowDown")
    expect(link).to_be_focused()
    search = tab.get_by_role("searchbox")
    search.press("Escape")
    expect(search).to_be_empty()
    assert "agent=codex" in tab.url and "q=" not in tab.url
    search.press("ArrowDown")
    expect(tab.locator("button.row")).to_be_focused()
