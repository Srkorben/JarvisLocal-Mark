"""Mark's own voice (Qwen3-TTS zero-shot clone), registered as ``mark_voice``."""

from openjarvis.speech.mark_voice.backend import (
    MarkVoiceSettings,
    MarkVoiceTTSBackend,
    mark_voice_home,
)

__all__ = ["MarkVoiceSettings", "MarkVoiceTTSBackend", "mark_voice_home"]
