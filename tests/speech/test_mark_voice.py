"""Tests for Mark's own voice backend (``mark_voice``)."""

from __future__ import annotations

import io
import json
import sys
import textwrap
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from openjarvis.speech.mark_voice.backend import (
    MODEL_FILES,
    MarkVoiceSettings,
    MarkVoiceTTSBackend,
    split_for_synthesis,
)
from openjarvis.speech.mark_voice.consent import (
    VoiceConsentError,
    create_own_voice_consent,
    validate_own_voice_consent,
)

FAKE_WORKER = textwrap.dedent(
    """
    import base64, json, sys
    print(json.dumps({"type": "ready", "sample_rate": 24000}), flush=True)
    for line in sys.stdin:
        req = json.loads(line)
        if req.get("command") == "close":
            print(json.dumps({"id": req.get("id"), "ok": True}), flush=True)
            break
        pcm = b"\\x01\\x00" * len(req["text"])
        print(json.dumps({
            "id": req["id"], "ok": True, "sample_rate": 24000,
            "pcm16_base64": base64.b64encode(pcm).decode("ascii"),
        }), flush=True)
    """
)


def _ready_settings(tmp_path: Path) -> MarkVoiceSettings:
    model_dir = tmp_path / "model"
    for name in MODEL_FILES:
        (model_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (model_dir / name).write_bytes(b"x")
    reference = tmp_path / "reference.mp3"
    reference.write_bytes(b"voice sample")
    reference_text = tmp_path / "reference.txt"
    reference_text.write_text("Hola, soy Mark.", encoding="utf-8")
    consent = tmp_path / "consent.json"
    create_own_voice_consent(reference_path=reference, consent_path=consent)
    return MarkVoiceSettings(
        python=Path(sys.executable),
        model_dir=model_dir,
        reference_path=reference,
        reference_text_path=reference_text,
        consent_path=consent,
        log_path=tmp_path / "logs" / "worker.log",
        timeout_seconds=30,
    )


def test_registered_and_preferred_first():
    from openjarvis.core.registry import TTSRegistry
    from openjarvis.speech._tts_discovery import TTS_BACKEND_ORDER, default_voice_for

    # conftest clears registries between tests; re-register as other TTS tests do.
    TTSRegistry.register_value("mark_voice", MarkVoiceTTSBackend)
    assert TTSRegistry.get("mark_voice") is MarkVoiceTTSBackend
    assert TTS_BACKEND_ORDER[0] == "mark_voice"
    assert default_voice_for("mark_voice") == "mark"


def test_health_fails_closed_without_setup(tmp_path):
    settings = MarkVoiceSettings(
        python=tmp_path / "missing-python",
        model_dir=tmp_path / "model",
        reference_path=tmp_path / "reference.mp3",
        reference_text_path=tmp_path / "reference.txt",
        consent_path=tmp_path / "consent.json",
        log_path=tmp_path / "worker.log",
    )
    backend = MarkVoiceTTSBackend(settings=settings)
    assert backend.health() is False
    with pytest.raises(RuntimeError, match="Voz de Mark no disponible"):
        backend.synthesize("Hola")


def test_health_ok_when_ready(tmp_path):
    assert MarkVoiceTTSBackend(settings=_ready_settings(tmp_path)).health() is True


def test_changed_reference_invalidates_consent(tmp_path):
    settings = _ready_settings(tmp_path)
    settings.reference_path.write_bytes(b"someone else")
    with pytest.raises(VoiceConsentError) as excinfo:
        validate_own_voice_consent(settings.reference_path, settings.consent_path)
    assert excinfo.value.code == "reference_changed"
    assert MarkVoiceTTSBackend(settings=settings).health() is False


def test_untrusted_consent_rejected(tmp_path):
    settings = _ready_settings(tmp_path)
    record = json.loads(settings.consent_path.read_text(encoding="utf-8"))
    record["source"] = "downloaded"
    settings.consent_path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(VoiceConsentError):
        validate_own_voice_consent(settings.reference_path, settings.consent_path)


def test_synthesize_through_worker_returns_wav(tmp_path, monkeypatch):
    settings = _ready_settings(tmp_path)
    worker = tmp_path / "fake_worker.py"
    worker.write_text(FAKE_WORKER, encoding="utf-8")
    monkeypatch.setattr(
        MarkVoiceSettings, "command", lambda self: [sys.executable, str(worker)]
    )
    backend = MarkVoiceTTSBackend(settings=settings)
    try:
        first = backend.synthesize("Hola. ¿Cómo estás?", output_format="mp3")
        second = backend.synthesize("Otra vez")
    finally:
        backend.close()

    assert first.format == "wav"
    assert first.voice_id == "mark"
    with wave.open(io.BytesIO(first.audio)) as wav:
        assert wav.getframerate() == 24000
        assert wav.getnchannels() == 1
        assert wav.getnframes() == len("Hola. ¿Cómo estás?")
    assert second.duration_seconds == pytest.approx(len("Otra vez") / 24000)


def test_split_respects_worker_limit():
    text = ("Esta es una frase de prueba para Mark. " * 80).strip()
    chunks = split_for_synthesis(text, limit=200)
    assert all(0 < len(chunk) <= 200 for chunk in chunks)
    assert " ".join(chunks) == text
    assert split_for_synthesis("   ") == []
    long_word = "a" * 450
    assert [len(c) for c in split_for_synthesis(long_word, limit=200)] == [
        200,
        200,
        50,
    ]


def test_settings_default_paths_live_under_config_dir(tmp_path, monkeypatch):
    from openjarvis.core.config import MarkVoiceConfig

    monkeypatch.setattr(
        "openjarvis.speech.mark_voice.backend.mark_voice_home",
        lambda: tmp_path / "mark-voice",
    )
    settings = MarkVoiceSettings.from_config(MarkVoiceConfig())
    assert settings.model_dir == (
        tmp_path / "mark-voice" / "models" / "qwen3-tts-12hz-0.6b-base"
    )
    assert settings.consent_path == tmp_path / "mark-voice" / "consent.json"
    custom = MarkVoiceSettings.from_config(
        replace(MarkVoiceConfig(), device="cpu", seed=7)
    )
    assert (custom.device, custom.seed) == ("cpu", 7)
