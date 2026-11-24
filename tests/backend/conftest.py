"""Shared fixtures: a throwaway HOME with host roots, skills and a lockfile."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ENV_VARS_TO_CLEAR = (
    "SKILLDESK_CONFIG_DIR",
    "SKILLDESK_STATE_DIR",
    "SKILLDESK_CACHE_DIR",
    "SKILLDESK_INDEX",
    "SKILLDESK_LOCKFILE",
    "SKILLDESK_PROJECTS",
    "OPENCODE_CONFIG_DIR",
    "LUCY_HOME",
)


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
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
