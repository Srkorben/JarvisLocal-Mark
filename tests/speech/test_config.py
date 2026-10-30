"""Tests for speech configuration."""

from openjarvis.core.config import JarvisConfig, SpeechConfig


def test_speech_config_defaults():
    cfg = SpeechConfig()
    assert cfg.backend == "auto"
    assert cfg.model == "small"
    assert cfg.language == "es"
    assert cfg.device == "auto"
    assert cfg.compute_type == "float16"
    assert cfg.tts_backend == "mark_voice"
    assert cfg.voice_id == "mark"


def test_mark_voice_section_loads_from_toml(tmp_path):
    from openjarvis.core.config import load_config

    path = tmp_path / "config.toml"
    path.write_text('[speech.mark_voice]\ndevice = "cpu"\nseed = 7\n', encoding="utf-8")
    cfg = load_config(path)
    assert cfg.speech.mark_voice.device == "cpu"
    assert cfg.speech.mark_voice.seed == 7


def test_jarvis_config_has_speech():
    cfg = JarvisConfig()
    assert hasattr(cfg, "speech")
    assert isinstance(cfg.speech, SpeechConfig)
    assert cfg.speech.backend == "auto"


def test_jarvis_system_has_speech_backend():
    """JarvisSystem has a speech_backend attribute."""
    from openjarvis.system import JarvisSystem

    assert "speech_backend" in JarvisSystem.__dataclass_fields__
