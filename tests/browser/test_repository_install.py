import re
import subprocess
import threading

import pytest
from playwright.sync_api import expect
from skilldesk import packages


@pytest.fixture
def repository(tmp_path, fake_home, monkeypatch):
    repo = tmp_path / "remote"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)

    def add_skill(path, name):
        folder = repo / path
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\nlicense: MIT\n---\n# {name}\n")

    def commit():
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "Skills"], check=True)

    add_skill("agent_reach/skill", "agent-reach")
    commit()
    subprocess.run(["git", "-C", str(repo), "switch", "-qc", "collection"], check=True)
    for n in range(9):
        add_skill(f"skills/tool-{n}", f"tool-{n}")
    commit()
    subprocess.run(["git", "-C", str(repo), "switch", "-q", "main"], check=True)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "url." + repo.as_uri() + ".insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://github.com/example/tools.git")
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    return "https://github.com/example/tools"


@pytest.mark.parametrize("width", [1280, 390])
def test_discover_choose_preview_and_install(page, repository, fake_home, width):
    tab, requests = page
    tab.set_viewport_size({"width": width, "height": 850})
    tab.goto("/#/settings")
    address = tab.get_by_role("textbox", name="仓库地址")
    find = tab.get_by_role("button", name="查找技能")
    expect(address).to_be_in_viewport()
    expect(find).to_be_in_viewport()
    expect(tab.get_by_label("仓库内的文档路径")).to_have_count(0)
    expect(tab.get_by_role("button", name="查询 GitHub 额度")).to_be_hidden()
    address.fill(repository + "/tree/main")
    assert not any("install-preview" in url or "upstream/quota" in url for url in requests)
    address.press("Enter")
    dialog = tab.get_by_role("dialog", name="安装预览")
    expect(dialog.get_by_text("agent-reach", exact=True)).to_be_visible()
    expect(dialog.get_by_text("agent_reach/skill/SKILL.md", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="取消").click()
    assert not (fake_home / ".agents/skills/agent-reach").exists()
    expect(address).to_have_value(repository + "/tree/main")

    address.fill(repository + "/tree/collection")
    find.click()
    expect(tab.get_by_role("heading", name="找到 10 个技能，选择一个预览")).to_be_visible()
    search = tab.get_by_role("searchbox", name="筛选技能")
    search.fill("none")
    expect(tab.get_by_text("没有匹配的技能。请试试其他名称或路径。")).to_be_visible()
    search.fill("tool-8")
    choice = tab.get_by_role("button", name=re.compile("tool-8"))
    expect(tab.locator(".install-choice")).to_have_count(1)
    choice.click()
    expect(dialog.get_by_text("collection", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="确认安装").click()
    expect(tab.get_by_role("link", name="在技能库查看")).to_be_visible()
    assert (fake_home / ".agents/skills/tool-8/SKILL.md").is_file()
    expect(tab.get_by_role("searchbox", name="筛选技能")).to_have_count(0)

    address.fill(repository + "/tree/main/missing")
    find.click()
    expect(tab.get_by_role("alert")).to_contain_text("没有找到 SKILL.md")
    address.fill(repository)
    expect(tab.get_by_role("alert")).to_have_count(0)
    tab.locator(".settings-diagnostics > summary").click()
    expect(tab.get_by_role("button", name="查询 GitHub 额度")).to_be_visible()
    assert not any("upstream/quota" in url for url in requests)
    assert tab.locator(".settings-page").evaluate("el => el.scrollWidth <= el.clientWidth")
    tab.evaluate("location.hash = '#/settings?section=projects'")
    expect(tab.get_by_label("项目绝对路径")).to_be_focused()
    tab.evaluate("location.hash = '#/settings?section=install'")
    expect(address).to_be_focused()
    expect(address).to_have_value(repository)


def test_cancel_discards_a_late_result_and_keeps_the_new_address(page, repository, monkeypatch):
    entered, resume = threading.Event(), threading.Event()
    original = packages.install_source

    def delayed(url, path):
        entered.set()
        assert resume.wait(10)
        return original(url, path)

    monkeypatch.setattr(packages, "install_source", delayed)
    tab, _ = page
    tab.expose_function("lookupStarted", entered.is_set)
    tab.goto("/#/settings?section=install")
    address = tab.get_by_label("仓库地址")
    address.fill(repository + "/tree/collection")
    tab.get_by_role("button", name="查找技能").click()
    try:
        tab.wait_for_function("() => window.lookupStarted()")
        tab.get_by_role("button", name="取消", exact=True).click()
        address.fill(repository + "/tree/main")
    finally:
        resume.set()
    tab.get_by_role("button", name="查找技能").click()
    expect(tab.get_by_role("dialog", name="安装预览")).to_be_visible()
    expect(tab.get_by_role("heading", name=re.compile("找到 .* 个技能"))).to_have_count(0)
    expect(address).to_have_value(repository + "/tree/main")
