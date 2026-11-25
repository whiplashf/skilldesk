"""Browser regressions that depend on layout, focus or an actual user gesture."""

import json
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


@pytest.fixture
def source_inventory(fake_home):
    skills = fake_home / ".agents/skills"
    files = {
        "recorded": "---\nname: recorded\n---\nInstalled from a lockfile.",
        "declared": "---\nname: declared\nrepository: https://github.com/team/docs\n---\nA declared repository.",
        "other-host": "---\nname: other-host\nrepository: https://gitlab.com/team/docs\n---\nAnother Git host.",
    }
    for name, content in files.items():
        (skills / name).mkdir()
        (skills / name / "SKILL.md").write_text(content)
    (skills.parent / ".skill-lock.json").write_text(json.dumps({"skills": {"recorded": {
        "sourceType": "github", "source": "acme/pack", "skillPath": "skills/设计 #1/SKILL.md", "commit": "a" * 40,
    }}}))


@pytest.mark.usefixtures("source_inventory")
def test_recorded_source_opens_the_installed_file_and_distinguishes_tracking(page):
    tab, requests = page
    tab.goto("/#/library?q=recorded", wait_until="networkidle")
    reader = tab.get_by_role("article")
    repo = reader.get_by_role("link", name="在 GitHub 打开仓库 acme/pack")
    file = reader.get_by_role("link", name="在 GitHub 查看 skills/设计 #1/SKILL.md")
    file_url = "https://github.com/acme/pack/blob/" + "a" * 40 + "/skills/%E8%AE%BE%E8%AE%A1%20%231/SKILL.md"
    expect(repo).to_have_attribute("href", "https://github.com/acme/pack")
    expect(file).to_have_attribute("href", file_url)
    assert not any(url.startswith("https://github.com/") for url in requests)
    tab.context.route(file_url, lambda route: route.fulfill(body="Upstream skill"))
    before = tab.url
    with tab.expect_popup() as opened:
        file.click()
    expect(opened.value).to_have_url(file_url)
    opened.value.close()
    assert tab.url == before
    reader.get_by_text("来源与可用范围", exact=True).click()
    expect(reader.get_by_text("安装锁文件", exact=True)).to_be_visible()
    assert reader.inner_text().count("acme/pack") == 1
    expect(reader.get_by_role("checkbox", name="我写的")).to_have_count(0)

    reader.get_by_role("button", name="编辑 GitHub 来源").click()
    reader.get_by_label("GitHub 仓库", exact=True).fill("acme/fork")
    reader.get_by_label("仓库内路径", exact=True).fill("other/SKILL.md")
    reader.get_by_role("button", name="保存来源").click()
    expect(reader.get_by_role("link", name="在 GitHub 查看 other/SKILL.md")).to_have_attribute(
        "href", "https://github.com/acme/fork/blob/HEAD/other/SKILL.md")
    expect(reader.get_by_text("GitHub 跟踪来源")).to_be_visible()
    expect(reader.locator(".source-comparison")).to_contain_text("此副本安装自 github.com/acme/pack")
    assert reader.inner_text().count("acme/fork") == 1


@pytest.mark.usefixtures("source_inventory")
def test_repository_without_a_file_and_non_github_source(page):
    tab, _ = page
    tab.goto("/#/library?q=declared")
    reader = tab.get_by_role("article")
    expect(reader.locator(".reader-repo a")).to_have_count(1)
    expect(reader.get_by_role("link", name="在 GitHub 打开仓库 team/docs")).to_have_attribute("href", "https://github.com/team/docs")
    reader.get_by_text("来源与可用范围", exact=True).click()
    expect(reader.get_by_role("checkbox", name="我写的")).to_have_count(0)
    tab.goto("/#/library?q=other-host")
    expect(reader.locator(".reader-repo")).to_have_text("gitlab.com/team/docs")
    expect(reader.locator(".reader-repo a")).to_have_count(0)
    reader.get_by_text("来源与可用范围", exact=True).click()
    expect(reader.get_by_role("checkbox", name="我写的")).to_have_count(0)


def test_local_authorship_survives_linking_and_can_be_cleared(page):
    tab, _ = page
    tab.goto("/#/library?q=sample")
    reader = tab.get_by_role("article")
    reader.get_by_text("来源与可用范围", exact=True).click()
    mine = reader.get_by_role("checkbox", name="我写的")
    mine.check()
    expect(reader.locator(".reader-repo")).to_contain_text("本地自写")
    reader.get_by_role("button", name="关联 GitHub 来源").click()
    reader.get_by_label("GitHub 仓库", exact=True).fill("team/local")
    reader.get_by_role("button", name="保存来源").click()
    expect(reader.get_by_role("link", name="在 GitHub 查看 SKILL.md")).to_have_attribute(
        "href", "https://github.com/team/local/blob/HEAD/SKILL.md")
    expect(mine).to_have_count(0)
    reader.get_by_role("button", name="移除自写标记").click()
    expect(reader.get_by_role("button", name="移除自写标记")).to_have_count(0)
    reader.get_by_role("button", name="编辑 GitHub 来源").click()
    reader.get_by_role("button", name="恢复扫描来源").click()
    expect(mine).to_be_visible()
    expect(mine).not_to_be_checked()
    expect(reader.locator(".reader-repo a")).to_have_count(0)


def test_another_tabs_source_edit_preserves_both_the_saved_source_and_the_draft(page):
    tab, _ = page
    other = tab.context.new_page()
    for current, repo in [(tab, "team/draft"), (other, "team/saved")]:
        current.goto("/#/library?q=sample")
        current.get_by_text("来源与可用范围", exact=True).click()
        current.get_by_role("button", name="关联 GitHub 来源").click()
        current.get_by_label("GitHub 仓库", exact=True).fill(repo)
    other.get_by_role("button", name="保存来源").click()
    expect(other.get_by_role("link", name="在 GitHub 打开仓库 team/saved")).to_be_visible()
    tab.get_by_role("button", name="保存来源").click()
    expect(tab.get_by_role("alert")).to_contain_text("另一窗口")
    expect(tab.get_by_role("link", name="在 GitHub 打开仓库 team/saved")).to_be_visible()
    expect(tab.get_by_label("GitHub 仓库", exact=True)).to_have_value("team/draft")
