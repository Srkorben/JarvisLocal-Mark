from __future__ import annotations

from abc import ABC, abstractmethod

from ..cancellation import CancellationToken
from .models import AudioBuffer, SynthesizedAudio, TranscriptionResult


class AudioError(RuntimeError):
    def __init__(self, code: str, message: str, *, component: str):
        super().__init__(message)
        self.code = code
        self.component = component

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self), "component": self.component}


class AudioRecorder(ABC):
    @abstractmethod
    def start(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> AudioBuffer:
        raise NotImplementedError

    @abstractmethod
    def abort(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def elapsed_seconds(self) -> float:
        raise NotImplementedError

    @property
    def recent_rms(self) -> float:
        """Nivel normalizado del bloque más reciente, si el backend lo ofrece."""

        return 0.0

    def retain_recent(self, seconds: float) -> None:
        """Descarta silencio anterior conservando un pequeño preroll."""

        return None


class AudioPlayer(ABC):
    @abstractmethod
    async def play(
        self, audio: SynthesizedAudio, cancellation: CancellationToken
    ) -> float:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError


class STTProvider(ABC):
    name: str

    @abstractmethod
    async def warmup(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def transcribe(
        self, audio: AudioBuffer, cancellation: CancellationToken
    ) -> TranscriptionResult:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class TTSProvider(ABC):
    name: str
    # Algunos clonadores necesitan una unidad prosódica completa para conservar
    # el timbre; el texto puede seguir mostrándose por streaming en la UI.
    prefer_complete_utterance: bool = False

    @abstractmethod
    async def warmup(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def synthesize(
        self, text: str, cancellation: CancellationToken
    ) -> SynthesizedAudio:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None
