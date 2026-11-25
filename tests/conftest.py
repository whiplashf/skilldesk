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
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(prompt_catalog, "PROJECT", checkout)
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
def prompt_checkout(fake_home, tmp_path):
    """A checkout with an existing staged change and a separate, local-only origin."""
    repo = prompt_catalog.PROJECT
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / ".gitignore").write_bytes((Path(__file__).resolve().parents[1] / ".gitignore").read_bytes())
    subprocess.run(["git", "-C", str(repo), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Tests", "-c", "user.email=test@example.invalid",
                    "commit", "-qm", "Initial"], check=True)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(origin)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", origin.as_uri()], check=True)
    (repo / "unrelated.txt").write_text("Already staged")
    subprocess.run(["git", "-C", str(repo), "add", "unrelated.txt"], check=True)
    return repo, origin
