"""Servicios de audio que no se cargan hasta que un turno los necesita.

El chat escrito del panel comparte sesión, autoridad y presencia con la voz,
pero la mayoría de sus turnos no hablan. Estos envoltorios permiten construir
el mismo VoiceSessionManager sin cargar STT, TTS ni dispositivos de audio: el
proveedor real se crea en el primer uso y se cierra solo si llegó a existir.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from ..cancellation import CancellationToken
from .base import AudioError, AudioPlayer, AudioRecorder, STTProvider, TTSProvider
from .models import AudioBuffer, SynthesizedAudio, TranscriptionResult


class LazyTTSProvider(TTSProvider):
    def __init__(self, factory: Callable[[], TTSProvider], *, name: str = "lazy") -> None:
        self._factory = factory
        self._provider: TTSProvider | None = None
        self._lock = asyncio.Lock()
        self.name = name

    @property
    def loaded(self) -> bool:
        return self._provider is not None

    async def _get(self) -> TTSProvider:
        async with self._lock:
            if self._provider is None:
                provider = self._factory()
                await provider.warmup()
                self._provider = provider
            return self._provider

    async def warmup(self) -> None:
        await self._get()

    async def synthesize(
        self, text: str, cancellation: CancellationToken
    ) -> SynthesizedAudio:
        cancellation.raise_if_cancelled()
        provider = await self._get()
        return await provider.synthesize(text, cancellation)

    async def aclose(self) -> None:
        async with self._lock:
            provider, self._provider = self._provider, None
        if provider is not None:
            await provider.aclose()


class LazySTTProvider(STTProvider):
    def __init__(self, factory: Callable[[], STTProvider], *, name: str = "lazy") -> None:
        self._factory = factory
        self._provider: STTProvider | None = None
        self._lock = asyncio.Lock()
        self.name = name

    @property
    def loaded(self) -> bool:
        return self._provider is not None

    async def _get(self) -> STTProvider:
        async with self._lock:
            if self._provider is None:
                provider = self._factory()
                await provider.warmup()
                self._provider = provider
            return self._provider

    async def warmup(self) -> None:
        await self._get()

    async def transcribe(
        self, audio: AudioBuffer, cancellation: CancellationToken
    ) -> TranscriptionResult:
        cancellation.raise_if_cancelled()
        provider = await self._get()
        return await provider.transcribe(audio, cancellation)

    async def aclose(self) -> None:
        async with self._lock:
            provider, self._provider = self._provider, None
        if provider is not None:
            await provider.aclose()


class LazyAudioPlayer(AudioPlayer):
    """Abre el dispositivo de salida solo cuando hay audio que reproducir."""

    def __init__(self, factory: Callable[[], AudioPlayer]) -> None:
        self._factory = factory
        self._player: AudioPlayer | None = None

    @property
    def loaded(self) -> bool:
        return self._player is not None

    async def play(
        self, audio: SynthesizedAudio, cancellation: CancellationToken
    ) -> float:
        cancellation.raise_if_cancelled()
        if self._player is None:
            self._player = self._factory()
        return await self._player.play(audio, cancellation)

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()


class NoMicrophoneRecorder(AudioRecorder):
    """Grabador del runtime de texto: no abre el micrófono."""

    def start(self) -> None:
        raise AudioError(
            "microphone_disabled",
            "El chat escrito no usa el micrófono; inicia la conversación por voz.",
            component="recorder",
        )

    def stop(self) -> AudioBuffer:
        raise AudioError(
            "microphone_disabled",
            "No hay ninguna grabación activa.",
            component="recorder",
        )

    def abort(self) -> None:
        return None

    @property
    def elapsed_seconds(self) -> float:
        return 0.0
