from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable

from ..cancellation import CancellationController, CancellationToken, OperationCancelled
from ..database import Database
from ..models import ProjectRecord
from ..orchestrator import Orchestrator
from .base import AudioError, AudioPlayer, AudioRecorder, STTProvider, TTSProvider
from .hotkey import WindowsKeyChord
from .models import VoiceState, VoiceTurnMetrics, VoiceTurnResult


StateCallback = Callable[[VoiceState], None]
TextCallback = Callable[[str], None]


_ALLOWED_TRANSITIONS: dict[VoiceState, frozenset[VoiceState]] = {
    VoiceState.IDLE: frozenset({VoiceState.RECORDING, VoiceState.ERROR}),
    VoiceState.RECORDING: frozenset(
        {VoiceState.TRANSCRIBING, VoiceState.CANCELLING, VoiceState.ERROR}
    ),
    VoiceState.TRANSCRIBING: frozenset(
        {VoiceState.PROCESSING, VoiceState.CANCELLING, VoiceState.ERROR, VoiceState.IDLE}
    ),
    VoiceState.PROCESSING: frozenset(
        {VoiceState.SPEAKING, VoiceState.CANCELLING, VoiceState.ERROR}
    ),
    VoiceState.SPEAKING: frozenset(
        {VoiceState.IDLE, VoiceState.CANCELLING, VoiceState.ERROR}
    ),
    VoiceState.CANCELLING: frozenset({VoiceState.IDLE, VoiceState.ERROR}),
    VoiceState.ERROR: frozenset({VoiceState.IDLE}),
}


class VoiceSessionManager:
    """Interfaz de voz semidúplex sobre una sesión y un Orchestrator existentes."""

    def __init__(
        self,
        *,
        database: Database,
        orchestrator: Orchestrator,
        project: ProjectRecord,
        session_id: str,
        cancellation: CancellationController,
        recorder: AudioRecorder,
        player: AudioPlayer,
        stt: STTProvider,
        tts: TTSProvider,
        min_record_seconds: float,
        min_rms: float,
        max_turn_seconds: float,
        max_record_seconds: float,
        on_state: StateCallback | None = None,
        on_transcript: TextCallback | None = None,
        on_text_delta: TextCallback | None = None,
        on_error: TextCallback | None = None,
    ) -> None:
        self.database = database
        self.orchestrator = orchestrator
        self.project = project
        self.session_id = session_id
        self.cancellation = cancellation
        self.recorder = recorder
        self.player = player
        self.stt = stt
        self.tts = tts
        self.min_record_seconds = min_record_seconds
        self.min_rms = min_rms
        self.max_turn_seconds = max_turn_seconds
        self.max_record_seconds = max_record_seconds
        self.on_state = on_state
        self.on_transcript = on_transcript
        self.on_text_delta = on_text_delta
        self.on_error = on_error
        self._state = VoiceState.IDLE
        self._lock = asyncio.Lock()
        self._token: CancellationToken | None = None
        self._turn_task: asyncio.Task[VoiceTurnResult] | None = None
        self._turn_started = 0.0
        self.last_result: VoiceTurnResult | None = None

    @property
    def state(self) -> VoiceState:
        return self._state

    async def warmup(self) -> None:
        await asyncio.gather(self.stt.warmup(), self.tts.warmup())

    async def start_recording(self) -> bool:
        async with self._lock:
            if self._state is not VoiceState.IDLE:
                return False
            active_project = self.database.get_active_project()
            if active_project is not None and active_project.id != self.project.id:
                self.project = active_project
                self.session_id = self.database.create_session(project_id=active_project.id)
            self._token = self.cancellation.begin_turn()
            self._turn_started = time.monotonic()
            try:
                self.recorder.start()
                self._transition(VoiceState.RECORDING)
                return True
            except Exception as exc:
                self._transition(VoiceState.ERROR)
                self._audit("error", error=exc)
                self._transition(VoiceState.IDLE)
                raise

    async def finish_recording(self) -> asyncio.Task[VoiceTurnResult] | None:
        async with self._lock:
            if self._state is not VoiceState.RECORDING:
                return None
            try:
                audio = self.recorder.stop()
            except Exception as exc:
                self._transition(VoiceState.ERROR)
                result = VoiceTurnResult(outcome="error", error=str(exc))
                self.last_result = result
                self._audit("error", error=exc)
                self._transition(VoiceState.IDLE)
                return None
            self._transition(VoiceState.TRANSCRIBING)
            pipeline_started = time.monotonic()
            self._turn_task = asyncio.create_task(
                self._run_turn(audio, pipeline_started), name="jarvis-voice-turn"
            )
            return self._turn_task

    async def cancel_active(self, reason: str = "Cancelación local de voz.") -> bool:
        async with self._lock:
            if self._state is VoiceState.IDLE:
                return False
            if self._state is not VoiceState.CANCELLING:
                self._transition(VoiceState.CANCELLING)
            if self._token is not None:
                self._token.cancel(reason)
            self.cancellation.cancel_current(reason)
            self.recorder.abort()
            self.player.stop()
            if self._turn_task is None:
                result = VoiceTurnResult(
                    outcome="cancelled",
                    error=reason,
                    metrics=VoiceTurnMetrics(
                        total_seconds=max(0.0, time.monotonic() - self._turn_started)
                    ),
                )
                self.last_result = result
                self._audit("cancelled", cancelled=True, metrics=result.metrics)
                self._transition(VoiceState.IDLE)
            return True

    async def wait_current(self) -> VoiceTurnResult | None:
        task = self._turn_task
        if task is None:
            return self.last_result
        return await task

    async def close(self) -> None:
        await self.cancel_active("Cierre de la interfaz de voz.")
        task = self._turn_task
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
            except (TimeoutError, asyncio.CancelledError):
                pass
        self.player.stop()
        self.recorder.abort()
        await self.stt.aclose()
        await self.tts.aclose()

    async def _run_turn(self, audio, pipeline_started: float) -> VoiceTurnResult:
        token = self._token or self.cancellation.current
        metrics = VoiceTurnMetrics(
            captured_audio_seconds=audio.duration_seconds,
            capture_close_seconds=audio.capture_close_seconds,
            input_rms=audio.rms,
        )
        try:
            async with asyncio.timeout(self.max_turn_seconds):
                token.raise_if_cancelled()
                if audio.duration_seconds < self.min_record_seconds:
                    return await self._finish_ignored(
                        "too_short", metrics, "Grabación demasiado corta."
                    )
                if audio.rms < self.min_rms:
                    return await self._finish_ignored(
                        "silence", metrics, "No se detectó voz suficiente."
                    )
                transcription = await self.stt.transcribe(audio, token)
                metrics.transcription_seconds = transcription.processing_seconds
                metrics.transcript_characters = len(transcription.text)
                token.raise_if_cancelled()
                if transcription.ambiguous:
                    return await self._finish_ignored(
                        "ambiguous",
                        metrics,
                        "Transcripción ambigua: "
                        + ", ".join(transcription.ambiguity_reasons),
                    )
                if self.on_transcript is not None:
                    self.on_transcript(transcription.text)
                self._transition(VoiceState.PROCESSING)

                first_delta_at: float | None = None

                def text_delta(delta: str) -> None:
                    nonlocal first_delta_at
                    if first_delta_at is None:
                        first_delta_at = time.monotonic()
                    if self.on_text_delta is not None:
                        self.on_text_delta(delta)

                model_started = time.monotonic()
                response = await self.orchestrator.chat(
                    self.session_id,
                    self.project,
                    transcription.text,
                    token,
                    on_text_delta=text_delta,
                )
                metrics.model_response_seconds = time.monotonic() - model_started
                metrics.first_token_seconds = (
                    None if first_delta_at is None else first_delta_at - pipeline_started
                )
                metrics.response_characters = len(response)
                token.raise_if_cancelled()
                self._transition(VoiceState.SPEAKING)
                for sentence in _speech_sentences(response):
                    spoken = await self.tts.synthesize(sentence, token)
                    metrics.synthesis_seconds += spoken.synthesis_seconds
                    if metrics.first_audio_seconds is None:
                        metrics.first_audio_seconds = time.monotonic() - pipeline_started
                    metrics.playback_seconds += await self.player.play(spoken, token)
                metrics.total_seconds = time.monotonic() - self._turn_started
                result = VoiceTurnResult(
                    outcome="success",
                    transcript=transcription.text,
                    response=response,
                    metrics=metrics,
                )
                self.last_result = result
                self._audit("success", metrics=metrics, transcription=transcription)
                self._transition(VoiceState.IDLE)
                return result
        except OperationCancelled as exc:
            metrics.total_seconds = time.monotonic() - self._turn_started
            result = VoiceTurnResult(
                outcome="cancelled", error=str(exc), metrics=metrics
            )
            self.last_result = result
            self._audit("cancelled", cancelled=True, metrics=metrics, error=exc)
            if self._state is not VoiceState.CANCELLING:
                self._transition(VoiceState.CANCELLING)
            self._transition(VoiceState.IDLE)
            return result
        except TimeoutError as exc:
            token.cancel("El turno de voz excedió su tiempo máximo.")
            self.player.stop()
            return await self._finish_error(exc, metrics, "timeout")
        except Exception as exc:
            self.player.stop()
            return await self._finish_error(exc, metrics, "error")
        finally:
            self._turn_task = None

    async def _finish_ignored(
        self, outcome: str, metrics: VoiceTurnMetrics, error: str
    ) -> VoiceTurnResult:
        metrics.total_seconds = time.monotonic() - self._turn_started
        result = VoiceTurnResult(outcome=outcome, error=error, metrics=metrics)
        self.last_result = result
        self._audit(outcome, metrics=metrics)
        self._transition(VoiceState.IDLE)
        return result

    async def _finish_error(
        self,
        exc: Exception,
        metrics: VoiceTurnMetrics,
        outcome: str,
    ) -> VoiceTurnResult:
        metrics.total_seconds = time.monotonic() - self._turn_started
        if self._state is not VoiceState.ERROR:
            self._transition(VoiceState.ERROR)
        result = VoiceTurnResult(outcome=outcome, error=str(exc), metrics=metrics)
        self.last_result = result
        self._audit(outcome, error=exc, metrics=metrics)
        if self.on_error is not None:
            self.on_error(str(exc))
        self._transition(VoiceState.IDLE)
        return result

    def _transition(self, state: VoiceState) -> None:
        if state is self._state:
            return
        if state not in _ALLOWED_TRANSITIONS[self._state]:
            raise RuntimeError(f"Transición de voz inválida: {self._state.value} → {state.value}")
        self._state = state
        if self.on_state is not None:
            self.on_state(state)

    def _audit(
        self,
        outcome: str,
        *,
        metrics: VoiceTurnMetrics | None = None,
        transcription=None,
        error: Exception | None = None,
        cancelled: bool = False,
    ) -> None:
        detail: dict = {
            "interface": "push_to_talk",
            "state": self._state.value,
            "metrics": {} if metrics is None else metrics.model_dump(mode="json"),
        }
        if transcription is not None:
            detail["transcription"] = {
                "language": transcription.language,
                "language_probability": transcription.language_probability,
                "average_log_probability": transcription.average_log_probability,
                "ambiguous": transcription.ambiguous,
                "segment_count": len(transcription.segments),
            }
        if error is not None:
            detail["error"] = (
                error.as_dict() if isinstance(error, AudioError) else str(error)
            )
        self.database.record_audit(
            session_id=self.session_id,
            project_id=self.project.id,
            event_type="voice_turn",
            outcome=outcome,
            detail=detail,
            cancelled=cancelled,
        )


async def run_push_to_talk_loop(
    manager: VoiceSessionManager,
    *,
    ptt: WindowsKeyChord,
    cancel: WindowsKeyChord,
    poll_seconds: float = 0.02,
) -> None:
    ptt_was_pressed = False
    cancel_was_pressed = False
    try:
        while True:
            ptt_pressed = ptt.is_pressed()
            cancel_pressed = cancel.is_pressed()
            if cancel_pressed and not cancel_was_pressed:
                await manager.cancel_active("Hotkey de emergencia de voz.")
            if ptt_pressed and not ptt_was_pressed:
                await manager.start_recording()
            if not ptt_pressed and ptt_was_pressed and manager.state is VoiceState.RECORDING:
                await manager.finish_recording()
            if (
                manager.state is VoiceState.RECORDING
                and manager.recorder.elapsed_seconds >= manager.max_record_seconds
            ):
                await manager.finish_recording()
            ptt_was_pressed = ptt_pressed
            cancel_was_pressed = cancel_pressed
            await asyncio.sleep(poll_seconds)
    finally:
        await manager.close()


def _speech_sentences(text: str) -> tuple[str, ...]:
    plain = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    plain = re.sub(r"[`*_#>]", "", plain)
    pieces = [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", plain)]
    return tuple(item for item in pieces if item)
