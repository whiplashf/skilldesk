"""A local-only browser and throwaway Skilldesk server for UI tests."""

import socket
import threading

import pytest
import uvicorn
from playwright.sync_api import sync_playwright
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
