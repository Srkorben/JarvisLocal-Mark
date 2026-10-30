"""Tests for starting Ollama hidden from the Mark desktop app."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.core.config import JarvisConfig
from openjarvis.mark_desktop import ollama_launcher as launcher


@pytest.mark.parametrize(
    ("configured", "env", "expected"),
    [
        ("", "", "http://127.0.0.1:11434"),
        ("", "127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("", "0.0.0.0", "http://127.0.0.1:11434"),
        ("", "http://gpu-box:11500/", "http://gpu-box:11500"),
        ("http://localhost:9999", "127.0.0.1:1", "http://localhost:9999"),
    ],
)
def test_ollama_host(monkeypatch, configured, env, expected):
    monkeypatch.setenv("OLLAMA_HOST", env)
    config = JarvisConfig()
    config.engine.ollama.host = configured
    assert launcher.ollama_host(config) == expected


def test_running_server_is_left_alone(monkeypatch):
    started = []
    monkeypatch.setattr(launcher, "ollama_running", lambda host, timeout=1.5: True)
    monkeypatch.setattr(launcher, "start_hidden", started.append)
    assert launcher.ensure_ollama(JarvisConfig()) is True
    assert started == []


def test_starts_hidden_and_waits_until_ready(monkeypatch):
    answers = iter([False, False, True])
    started, notes = [], []
    monkeypatch.setattr(
        launcher, "ollama_running", lambda host, timeout=1.5: next(answers)
    )
    monkeypatch.setattr(launcher, "find_ollama", lambda: Path("ollama.exe"))
    monkeypatch.setattr(launcher, "start_hidden", started.append)
    monkeypatch.setattr(launcher.time, "sleep", lambda _s: None)

    assert launcher.ensure_ollama(JarvisConfig(), notes.append) is True
    assert started == [Path("ollama.exe")]
    assert notes == ["Iniciando Ollama…"]


def test_missing_ollama_reports_false(monkeypatch):
    monkeypatch.setattr(launcher, "ollama_running", lambda host, timeout=1.5: False)
    monkeypatch.setattr(launcher, "find_ollama", lambda: None)
    assert launcher.ensure_ollama(JarvisConfig()) is False
