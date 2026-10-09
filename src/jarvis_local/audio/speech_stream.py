"""Habla progresiva: sintetiza frases mientras el LLM sigue generando.

Antes, el turno esperaba la respuesta completa y luego alternaba síntesis y
reproducción frase a frase. Aquí un productor corta frases según llegan los
deltas, un trabajador sintetiza la siguiente mientras otro reproduce la
actual, y todo responde al mismo token de cancelación del turno.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable

from ..cancellation import CancellationToken
from .base import AudioPlayer, TTSProvider


# Una frase termina en . ! ? … seguidos de espacio, o en salto de línea.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+")
# Frases largas retrasan el primer audio; se parten en una pausa natural.
MAX_CHUNK_CHARACTERS = 220
MIN_SPLIT_CHARACTERS = 60
_SOFT_BREAKS = (", ", "; ", ": ", " — ", " - ")
_SENTINEL = object()


def clean_for_speech(text: str) -> str:
    """Quita marcas de Markdown que el TTS leería literalmente."""

    plain = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    plain = re.sub(r"[`*_#>]", "", plain)
    return " ".join(plain.split())


class SentenceChunker:
    """Acumula deltas y entrega frases completas, listas para sintetizar."""

    def __init__(self, max_characters: int = MAX_CHUNK_CHARACTERS) -> None:
        self.max_characters = max_characters
        self._buffer = ""

    def feed(self, delta: str) -> list[str]:
        self._buffer += delta
        chunks: list[str] = []
        while True:
            match = _SENTENCE_END.search(self._buffer)
            if match is None:
                break
            chunks.append(self._buffer[: match.start()])
            self._buffer = self._buffer[match.end():]
        while len(self._buffer) > self.max_characters:
            cut = self._soft_cut(self._buffer)
            chunks.append(self._buffer[:cut])
            self._buffer = self._buffer[cut:]
        return [text for text in (clean_for_speech(chunk) for chunk in chunks) if text]

    def flush(self) -> list[str]:
        text = clean_for_speech(self._buffer)
        self._buffer = ""
        return [text] if text else []

    def _soft_cut(self, text: str) -> int:
        window = text[: self.max_characters]
        for marker in _SOFT_BREAKS:
            position = window.rfind(marker)
            if position >= MIN_SPLIT_CHARACTERS:
                return position + len(marker)
        position = window.rfind(" ")
        return position + 1 if position >= MIN_SPLIT_CHARACTERS else self.max_characters


class SpeechPipeline:
    """Cola productor/consumidor de síntesis y reproducción con cancelación."""

    def __init__(
        self,
        *,
        tts: TTSProvider,
        player: AudioPlayer,
        cancellation: CancellationToken,
        on_first_audio: Callable[[], None] | None = None,
        max_buffered_audio: int = 2,
    ) -> None:
        self.tts = tts
        self.player = player
        self.cancellation = cancellation
        self.on_first_audio = on_first_audio
        self._chunker = SentenceChunker()
        self._texts: asyncio.Queue = asyncio.Queue()
        # Acota la síntesis adelantada para no ocupar memoria ni GPU sin necesidad.
        self._audio: asyncio.Queue = asyncio.Queue(maxsize=max_buffered_audio)
        self._tasks: list[asyncio.Task] = []
        self._fed_text = ""
        self.sentences = 0
        self.synthesis_seconds = 0.0
        self.playback_seconds = 0.0
        self.first_audio_at: float | None = None

    @property
    def fed_text(self) -> str:
        return self._fed_text

    def feed(self, delta: str) -> None:
        """Recibe un delta del LLM. Es síncrono para usarse como callback."""

        if not delta or self.cancellation.is_cancelled:
            return
        self._fed_text += delta
        for sentence in self._chunker.feed(delta):
            self._enqueue(sentence)

    async def finish(self) -> None:
        """Pronuncia el resto y espera a que termine la reproducción."""

        for sentence in self._chunker.flush():
            self._enqueue(sentence)
        if not self._tasks:
            return
        await self._texts.put(_SENTINEL)
        try:
            await asyncio.gather(*self._tasks)
        except BaseException:
            await self.abort()
            raise

    async def abort(self) -> None:
        self.player.stop()
        for task in self._tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _enqueue(self, sentence: str) -> None:
        if not self._tasks:
            self._tasks = [
                asyncio.create_task(self._synthesize_loop(), name="jarvis-tts-synthesis"),
                asyncio.create_task(self._playback_loop(), name="jarvis-tts-playback"),
            ]
        self._texts.put_nowait(sentence)

    async def _synthesize_loop(self) -> None:
        try:
            while True:
                text = await self._texts.get()
                if text is _SENTINEL:
                    break
                self.cancellation.raise_if_cancelled()
                spoken = await self.tts.synthesize(text, self.cancellation)
                self.synthesis_seconds += spoken.synthesis_seconds
                self.sentences += 1
                await self._audio.put(spoken)
        finally:
            await _put_sentinel(self._audio)

    async def _playback_loop(self) -> None:
        while True:
            spoken = await self._audio.get()
            if spoken is _SENTINEL:
                return
            self.cancellation.raise_if_cancelled()
            if self.first_audio_at is None:
                self.first_audio_at = time.monotonic()
                if self.on_first_audio is not None:
                    self.on_first_audio()
            self.playback_seconds += await self.player.play(spoken, self.cancellation)


async def _put_sentinel(queue: asyncio.Queue) -> None:
    # Si la reproducción ya terminó por error, la cola puede seguir llena: se
    # descarta audio pendiente para que el centinela nunca bloquee el cierre.
    while True:
        try:
            queue.put_nowait(_SENTINEL)
            return
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(0)

