from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
from pydantic import ConfigDict, Field

from ..models import StrictModel


class VoiceState(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    CANCELLING = "cancelling"
    ERROR = "error"


class AudioDeviceInfo(StrictModel):
    index: int
    name: str
    host_api: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: int
    is_default_input: bool = False
    is_default_output: bool = False


@dataclass(frozen=True)
class AudioBuffer:
    samples: np.ndarray
    sample_rate: int
    duration_seconds: float
    rms: float
    capture_close_seconds: float = 0.0
    overflowed: bool = False


@dataclass(frozen=True)
class SynthesizedAudio:
    samples: np.ndarray
    sample_rate: int
    channels: int
    synthesis_seconds: float

    @property
    def duration_seconds(self) -> float:
        if self.sample_rate <= 0 or self.channels <= 0:
            return 0.0
        return len(self.samples) / self.sample_rate


class TranscriptionSegment(StrictModel):
    start: float
    end: float
    text: str
    average_log_probability: float | None = None
    no_speech_probability: float | None = None


class TranscriptionResult(StrictModel):
    text: str
    language: str
    language_probability: float | None = None
    average_log_probability: float | None = None
    ambiguous: bool = False
    ambiguity_reasons: tuple[str, ...] = ()
    processing_seconds: float
    segments: tuple[TranscriptionSegment, ...] = ()


class VoiceTurnMetrics(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    captured_audio_seconds: float = 0.0
    capture_close_seconds: float = 0.0
    transcription_seconds: float | None = None
    first_token_seconds: float | None = None
    model_response_seconds: float | None = None
    first_audio_seconds: float | None = None
    synthesis_seconds: float = 0.0
    playback_seconds: float = 0.0
    total_seconds: float = 0.0
    input_rms: float = 0.0
    transcript_characters: int = 0
    response_characters: int = 0


class VoiceTurnResult(StrictModel):
    outcome: str
    transcript: str = ""
    response: str = ""
    error: str | None = None
    metrics: VoiceTurnMetrics = Field(default_factory=VoiceTurnMetrics)
