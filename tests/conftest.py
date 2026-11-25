"""Shared fixtures: a throwaway HOME with host roots, skills and a lockfile."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from skilldesk import prompt_catalog

ENV_VARS_TO_CLEAR = (
    "SKILLDESK_CONFIG_DIR",
    "SKILLDESK_STATE_DIR",
    "SKILLDESK_CACHE_DIR",
    "SKILLDESK_INDEX",
    "SKILLDESK_LOCKFILE",
    "SKILLDESK_PROJECTS",
    "OPENCODE_CONFIG_DIR",
    "CODEX_HOME",
    "SKILLDESK_AI_BASE_URL",
    "SKILLDESK_AI_MODEL",
    "SKILLDESK_AI_API_KEY",
    "LUCY_HOME",
)


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    monkeypatch.setattr(prompt_catalog, "PROJECT", tmp_path / "checkout")
    for relative in (".agents/skills", ".claude/skills", ".config/opencode/skills"):
        (home / relative).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    for name in ENV_VARS_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)
    # keep the real machine's roots out of the scan
    assert os.path.expanduser("~") == str(home)
    return home


@pytest.fixture
def publication_remote(tmp_path, monkeypatch):
    """A real branch and push destination, entirely on the test machine."""
    from skilldesk import prompt_publish

    repo = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "README.md").write_text("Project")
    subprocess.run(["git", "-C", str(seed), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(seed), "-c", "user.name=Tests", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "Initial"], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "-q", str(repo), "HEAD:main"], check=True)
    monkeypatch.setattr(prompt_publish, "destination", lambda: prompt_publish.Target("test/library", repo.as_uri()))
    return repo
