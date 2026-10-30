"""Tests for starting Ollama hidden from the Mark desktop app."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.core.config import JarvisConfig
from jarvis_local.model_providers import ollama_launcher as launcher


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


def test_release_loaded_models_unloads_each_resident_model():
    import json

    import httpx
    import respx

    with respx.mock(base_url="http://127.0.0.1:11434") as router:
        router.get("/api/ps").mock(
            return_value=httpx.Response(
                200, json={"models": [{"name": "qwen3:8b"}, {"name": "other:1b"}]}
            )
        )
        unload = router.post("/api/generate").mock(return_value=httpx.Response(200, json={}))
        released = launcher.release_loaded_models("http://127.0.0.1:11434")
    assert released == ["qwen3:8b", "other:1b"]
    bodies = [json.loads(call.request.content) for call in unload.calls]
    assert bodies == [
        {"model": "qwen3:8b", "keep_alive": 0},
        {"model": "other:1b", "keep_alive": 0},
    ]


def test_release_is_quiet_when_ollama_is_down():
    import httpx
    import respx

    with respx.mock(base_url="http://127.0.0.1:11434") as router:
        router.get("/api/ps").mock(side_effect=httpx.ConnectError("down"))
        assert launcher.release_loaded_models("http://127.0.0.1:11434") == []


@pytest.mark.parametrize(
    ("device", "provider", "expected_calls"),
    [("cuda", "openjarvis", 1), ("cpu", "openjarvis", 0), ("cuda", "llama_cpp", 0)],
)
def test_voice_releases_vram_only_for_cuda_with_ollama(
    monkeypatch, tmp_path, device, provider, expected_calls
):
    import asyncio

    from jarvis_local import cli
    from tests.mark.helpers import make_settings

    calls = []
    monkeypatch.setattr(launcher, "release_loaded_models", lambda host: calls.append(host) or [])
    settings = make_settings(tmp_path, model_provider=provider)
    monkeypatch.setattr(
        type(settings), "effective_tts", property(lambda self: ("qwen3_tts", device))
    )
    asyncio.run(cli._release_llm_vram_for_voice(settings))
    assert len(calls) == expected_calls
