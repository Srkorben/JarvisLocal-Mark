from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from collections.abc import Awaitable, Callable

from ..cancellation import CancellationController, CancellationToken, OperationCancelled
from ..database import Database
from ..latency import LatencyLog, TurnTrace
from ..models import ProjectRecord
from ..orchestrator import Orchestrator
from .base import AudioError, AudioPlayer, AudioRecorder, STTProvider, TTSProvider
from .speech_stream import SpeechPipeline
from .models import VoiceState, VoiceTurnMetrics, VoiceTurnResult


StateCallback = Callable[[VoiceState], None]
TextCallback = Callable[[str], None]
VoiceSessionCallback = Callable[[str, str, bool, bool], None]


_ALLOWED_TRANSITIONS: dict[VoiceState, frozenset[VoiceState]] = {
    VoiceState.IDLE: frozenset(
        {VoiceState.RECORDING, VoiceState.PROCESSING, VoiceState.ERROR}
    ),
    VoiceState.RECORDING: frozenset(
        {VoiceState.IDLE, VoiceState.TRANSCRIBING, VoiceState.CANCELLING, VoiceState.ERROR}
    ),
    VoiceState.TRANSCRIBING: frozenset(
        {VoiceState.PROCESSING, VoiceState.CANCELLING, VoiceState.ERROR, VoiceState.IDLE}
    ),
    VoiceState.PROCESSING: frozenset(
        {VoiceState.SPEAKING, VoiceState.IDLE, VoiceState.CANCELLING, VoiceState.ERROR}
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
        latency_log: LatencyLog | None = None,
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
        self.latency_log = latency_log or getattr(
            orchestrator, "latency_log", None
        ) or LatencyLog(None)
        self._state = VoiceState.IDLE
        self._lock = asyncio.Lock()
        self._token: CancellationToken | None = None
        self._turn_task: asyncio.Task[VoiceTurnResult] | None = None
        self._turn_started = 0.0
        self.last_result: VoiceTurnResult | None = None
        self._voice_interface = "push_to_talk"

    @property
    def state(self) -> VoiceState:
        return self._state

    async def warmup(self) -> None:
        await asyncio.gather(self.stt.warmup(), self.tts.warmup())

    async def start_recording(self, *, interface: str = "push_to_talk") -> bool:
        async with self._lock:
            if self._state is not VoiceState.IDLE:
                return False
            active_project = self.database.get_active_project()
            if active_project is not None and active_project.id != self.project.id:
                self.project = active_project
                self.session_id = self.database.create_session(project_id=active_project.id)
            self._token = self.cancellation.begin_turn()
            self._turn_started = time.monotonic()
            self._voice_interface = interface
            try:
                self.recorder.start()
                self._transition(VoiceState.RECORDING)
                return True
            except Exception as exc:
                self._transition(VoiceState.ERROR)
                self._audit("error", error=exc)
                self._transition(VoiceState.IDLE)
                raise

    async def refresh_recording(self) -> bool:
        """Renueva el búfer de escucha continua sin cerrar la sesión de llamada."""

        async with self._lock:
            if self._state is not VoiceState.RECORDING:
                return False
            self.recorder.abort()
            self.recorder.start()
            self._turn_started = time.monotonic()
            return True

    async def discard_recording(self, reason: str) -> bool:
        """Cierra una escucha sin crear un turno ni persistir un evento de voz."""

        async with self._lock:
            if self._state is not VoiceState.RECORDING:
                return False
            self.recorder.abort()
            if self._token is not None:
                self._token.cancel(reason)
            self.cancellation.cancel_current(reason)
            self._transition(VoiceState.IDLE)
            return True

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

    async def submit_text(
        self, text: str, *, speak: bool = True, queued_seconds: float | None = None
    ) -> asyncio.Task[VoiceTurnResult] | None:
        """Procesa texto de la UI con la misma sesión, autoridad y voz local."""

        normalized = " ".join(text.split())
        if not normalized or len(normalized) > 4000:
            raise AudioError(
                "invalid_text",
                "El mensaje escrito debe contener entre 1 y 4000 caracteres.",
                component="conversation",
            )
        async with self._lock:
            if self._state is not VoiceState.IDLE:
                return None
            active_project = self.database.get_active_project()
            if active_project is not None and active_project.id != self.project.id:
                self.project = active_project
                self.session_id = self.database.create_session(project_id=active_project.id)
            self._token = self.cancellation.begin_turn()
            self._turn_started = time.monotonic()
            if self.on_transcript is not None:
                self.on_transcript(normalized)
            self._transition(VoiceState.PROCESSING)
            self._turn_task = asyncio.create_task(
                self._run_text_turn(normalized, speak=speak, queued_seconds=queued_seconds),
                name="jarvis-text-ui-turn",
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
        trace = TurnTrace(interface=self._voice_interface)
        trace.set(captured_audio_seconds=round(audio.duration_seconds, 3))
        try:
            return await self._run_voice_turn(audio, pipeline_started, trace)
        finally:
            self._write_trace(trace)

    async def _run_voice_turn(
        self, audio, pipeline_started: float, trace: TurnTrace
    ) -> VoiceTurnResult:
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
                trace.mark("stt_done")
                response = await self._respond(
                    transcription.text,
                    token,
                    metrics,
                    pipeline_started,
                    trace,
                    speak=True,
                )
                metrics.total_seconds = time.monotonic() - self._turn_started
                result = VoiceTurnResult(
                    outcome="success",
                    transcript=transcription.text,
                    response=response,
                    metrics=metrics,
                )
                self.last_result = result
                self._audit(
                    "success",
                    metrics=metrics,
                    transcription=transcription,
                    interface=self._voice_interface,
                )
                self._transition(VoiceState.IDLE)
                return result
        except OperationCancelled as exc:
            metrics.total_seconds = time.monotonic() - self._turn_started
            result = VoiceTurnResult(
                outcome="cancelled", error=str(exc), metrics=metrics
            )
            self.last_result = result
            self._audit(
                "cancelled",
                cancelled=True,
                metrics=metrics,
                error=exc,
                interface=self._voice_interface,
            )
            if self._state is not VoiceState.CANCELLING:
                self._transition(VoiceState.CANCELLING)
            self._transition(VoiceState.IDLE)
            return result
        except TimeoutError as exc:
            token.cancel("El turno de voz excedió su tiempo máximo.")
            self.player.stop()
            return await self._finish_error(
                exc, metrics, "timeout", interface=self._voice_interface
            )
        except Exception as exc:
            self.player.stop()
            return await self._finish_error(
                exc, metrics, "error", interface=self._voice_interface
            )
        finally:
            self._turn_task = None

    async def _run_text_turn(
        self, text: str, *, speak: bool, queued_seconds: float | None = None
    ) -> VoiceTurnResult:
        trace = TurnTrace(interface="control_center_text")
        trace.set(
            speak=speak,
            queue_wait_seconds=None if queued_seconds is None else round(queued_seconds, 3),
        )
        try:
            return await self._run_text_turn_traced(text, speak=speak, trace=trace)
        finally:
            self._write_trace(trace)

    async def _run_text_turn_traced(
        self, text: str, *, speak: bool, trace: TurnTrace
    ) -> VoiceTurnResult:
        token = self._token or self.cancellation.current
        pipeline_started = time.monotonic()
        metrics = VoiceTurnMetrics(transcript_characters=len(text))
        try:
            async with asyncio.timeout(self.max_turn_seconds):
                response = await self._respond(
                    text, token, metrics, pipeline_started, trace, speak=speak
                )
                metrics.total_seconds = time.monotonic() - self._turn_started
                result = VoiceTurnResult(
                    outcome="success",
                    transcript=text,
                    response=response,
                    metrics=metrics,
                )
                self.last_result = result
                self._audit("success", metrics=metrics, interface="control_center_text")
                self._transition(VoiceState.IDLE)
                return result
        except OperationCancelled as exc:
            metrics.total_seconds = time.monotonic() - self._turn_started
            result = VoiceTurnResult(outcome="cancelled", error=str(exc), metrics=metrics)
            self.last_result = result
            self._audit(
                "cancelled",
                cancelled=True,
                metrics=metrics,
                error=exc,
                interface="control_center_text",
            )
            if self._state is not VoiceState.CANCELLING:
                self._transition(VoiceState.CANCELLING)
            self._transition(VoiceState.IDLE)
            return result
        except TimeoutError as exc:
            token.cancel("El turno escrito excedió su tiempo máximo.")
            self.player.stop()
            return await self._finish_error(
                exc, metrics, "timeout", interface="control_center_text"
            )
        except Exception as exc:
            self.player.stop()
            return await self._finish_error(
                exc, metrics, "error", interface="control_center_text"
            )
        finally:
            self._turn_task = None

    async def _respond(
        self,
        text: str,
        token: CancellationToken,
        metrics: VoiceTurnMetrics,
        pipeline_started: float,
        trace: TurnTrace,
        *,
        speak: bool,
    ) -> str:
        """Ejecuta el LLM y, si procede, habla mientras genera.

        La primera frase completa se sintetiza sin esperar al resto de la
        respuesta, y la síntesis de la siguiente se solapa con la reproducción
        de la actual. Un fallo o una cancelación detienen ambas colas.
        """

        def first_audio() -> None:
            trace.mark("first_audio")
            if self._state is VoiceState.PROCESSING and not token.is_cancelled:
                self._transition(VoiceState.SPEAKING)

        pipeline = (
            SpeechPipeline(
                tts=self.tts,
                player=self.player,
                cancellation=token,
                on_first_audio=first_audio,
            )
            if speak
            else None
        )
        first_delta_at: float | None = None

        def text_delta(delta: str) -> None:
            nonlocal first_delta_at
            if first_delta_at is None:
                first_delta_at = time.monotonic()
            if self.on_text_delta is not None:
                self.on_text_delta(delta)
            if pipeline is not None:
                pipeline.feed(delta)

        model_started = time.monotonic()
        try:
            response = await self.orchestrator.chat(
                self.session_id,
                self.project,
                text,
                token,
                on_text_delta=text_delta,
                trace=trace,
            )
            metrics.model_response_seconds = time.monotonic() - model_started
            metrics.first_token_seconds = (
                None if first_delta_at is None else first_delta_at - pipeline_started
            )
            metrics.response_characters = len(response)
            token.raise_if_cancelled()
            if pipeline is not None:
                final = response.strip()
                # Mensajes del orquestador que no pasaron por streaming (límite
                # de rondas, respuesta vacía) también deben pronunciarse.
                if final and final not in pipeline.fed_text:
                    pipeline.feed(("\n" if pipeline.fed_text else "") + final)
                await pipeline.finish()
        except BaseException:
            if pipeline is not None:
                await pipeline.abort()
            raise
        finally:
            if pipeline is not None:
                metrics.synthesis_seconds = pipeline.synthesis_seconds
                metrics.playback_seconds = pipeline.playback_seconds
                if pipeline.first_audio_at is not None:
                    metrics.first_audio_seconds = pipeline.first_audio_at - pipeline_started
                trace.set(
                    sentences_spoken=pipeline.sentences,
                    synthesis_seconds=round(pipeline.synthesis_seconds, 3),
                    playback_seconds=round(pipeline.playback_seconds, 3),
                )
        return response

    def _write_trace(self, trace: TurnTrace) -> None:
        trace.mark("done")
        if self.last_result is not None:
            trace.set(
                outcome=self.last_result.outcome,
                stt_seconds=self.last_result.metrics.transcription_seconds,
            )
        self.latency_log.write(trace)

    async def _finish_ignored(
        self, outcome: str, metrics: VoiceTurnMetrics, error: str
    ) -> VoiceTurnResult:
        metrics.total_seconds = time.monotonic() - self._turn_started
        result = VoiceTurnResult(outcome=outcome, error=error, metrics=metrics)
        self.last_result = result
        self._audit(outcome, metrics=metrics, interface=self._voice_interface)
        self._transition(VoiceState.IDLE)
        return result

    async def _finish_error(
        self,
        exc: Exception,
        metrics: VoiceTurnMetrics,
        outcome: str,
        interface: str = "push_to_talk",
    ) -> VoiceTurnResult:
        metrics.total_seconds = time.monotonic() - self._turn_started
        if self._state is not VoiceState.ERROR:
            self._transition(VoiceState.ERROR)
        result = VoiceTurnResult(outcome=outcome, error=str(exc), metrics=metrics)
        self.last_result = result
        self._audit(outcome, error=exc, metrics=metrics, interface=interface)
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
        interface: str = "push_to_talk",
    ) -> None:
        detail: dict = {
            "interface": interface,
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


_PANEL_CANCEL_REASON = "Cancelado desde el panel."


async def run_panel_voice_loop(
    manager: VoiceSessionManager,
    *,
    voice_command_source: Callable[[], Awaitable[dict | None]],
    text_request_source: Callable[[], Awaitable[dict | None]] | None = None,
    on_session_state: VoiceSessionCallback | None = None,
    speech_rms: float = 0.008,
    voice_start_seconds: float = 0.12,
    end_silence_seconds: float = 0.8,
    listen_rollover_seconds: float = 8.0,
    poll_seconds: float = 0.02,
) -> None:
    """Atiende llamada semidúplex automática y PTT desde el panel local."""

    text_request_task: asyncio.Task[dict | None] | None = None
    voice_command_task: asyncio.Task[dict | None] | None = None
    pending_text: dict | None = None
    call_active = False
    muted = False
    voice_detected = False
    voice_candidate_at: float | None = None
    silence_at: float | None = None
    last_session_snapshot: tuple[str, str, bool, bool] | None = None
    last_manager_state = manager.state

    def publish(state: str, mode: str = "call", *, force: bool = False) -> None:
        nonlocal last_session_snapshot
        snapshot = (state, mode, call_active, muted)
        if snapshot == last_session_snapshot and not force:
            return
        last_session_snapshot = snapshot
        if on_session_state is not None:
            on_session_state(state, mode, call_active, muted)

    def reset_detector() -> None:
        nonlocal voice_detected, voice_candidate_at, silence_at
        voice_detected = False
        voice_candidate_at = None
        silence_at = None

    async def begin_listening() -> None:
        if not call_active or muted or manager.state is not VoiceState.IDLE:
            return
        if await manager.start_recording(interface="continuous_call"):
            reset_detector()
            publish("listening")

    try:
        while True:
            manager_state_changed = manager.state is not last_manager_state
            last_manager_state = manager.state
            if voice_command_task is None:
                voice_command_task = asyncio.create_task(voice_command_source())
            if voice_command_task.done():
                try:
                    command = voice_command_task.result()
                except Exception:
                    command = None
                voice_command_task = None
                action = command.get("action") if isinstance(command, dict) else None
                if action == "start_call":
                    call_active = True
                    muted = False
                    publish("idle")
                    await begin_listening()
                elif action == "end_call":
                    call_active = False
                    muted = False
                    publish("ending")
                    if not await manager.discard_recording(
                        "Llamada finalizada desde la interfaz."
                    ):
                        await manager.cancel_active("Llamada finalizada desde la interfaz.")
                    reset_detector()
                    publish("idle")
                elif action == "mute" and call_active:
                    muted = True
                    if not await manager.discard_recording(
                        "Micrófono silenciado desde la interfaz."
                    ):
                        await manager.cancel_active("Micrófono silenciado desde la interfaz.")
                    reset_detector()
                    publish("muted")
                elif action == "unmute" and call_active:
                    muted = False
                    publish("idle")
                    await begin_listening()
                elif (
                    action == "start_recording"
                    and not call_active
                    and manager.state is VoiceState.IDLE
                ):
                    await manager.start_recording(interface="push_to_talk")
                    publish("recording", "ptt")
                elif action == "finish_recording" and manager.state is VoiceState.RECORDING:
                    await manager.finish_recording()
                elif action == "cancel":
                    await manager.cancel_active(_PANEL_CANCEL_REASON)
                    reset_detector()
                    publish("muted" if call_active and muted else "idle")
            if call_active and not muted:
                await begin_listening()
                if manager.state is VoiceState.RECORDING:
                    now = time.monotonic()
                    level = manager.recorder.recent_rms
                    if not voice_detected:
                        if level >= speech_rms:
                            voice_candidate_at = voice_candidate_at or now
                            if now - voice_candidate_at >= voice_start_seconds:
                                voice_detected = True
                                manager.recorder.retain_recent(0.5)
                                publish("voice_detected")
                        else:
                            voice_candidate_at = None
                        if (
                            not voice_detected
                            and voice_candidate_at is None
                            and manager.recorder.elapsed_seconds >= listen_rollover_seconds
                        ):
                            await manager.refresh_recording()
                            reset_detector()
                            publish("listening")
                    else:
                        end_threshold = max(manager.min_rms, speech_rms * 0.65)
                        if level < end_threshold:
                            silence_at = silence_at or now
                            if now - silence_at >= end_silence_seconds:
                                await manager.finish_recording()
                                reset_detector()
                        else:
                            silence_at = None
                        if manager.recorder.elapsed_seconds >= manager.max_record_seconds:
                            await manager.finish_recording()
                            reset_detector()
            elif call_active and muted:
                publish("muted", force=manager_state_changed)
            elif (
                not call_active
                and manager.state is VoiceState.RECORDING
                and manager.recorder.elapsed_seconds >= manager.max_record_seconds
            ):
                await manager.finish_recording()
            if (
                text_request_source is not None
                and text_request_task is None
                and pending_text is None
            ):
                text_request_task = asyncio.create_task(text_request_source())
            if text_request_task is not None and text_request_task.done():
                try:
                    pending_text = text_request_task.result() or pending_text
                except Exception:
                    pending_text = pending_text
                text_request_task = None
            if pending_text is not None and pending_text.get("cancel"):
                pending_text = None
                await manager.cancel_active(_PANEL_CANCEL_REASON)
            if (
                pending_text is not None
                and call_active
                and manager.state is VoiceState.RECORDING
                and not voice_detected
            ):
                await manager.discard_recording(
                    "Escucha pausada temporalmente por mensaje escrito."
                )
                reset_detector()
            if pending_text is not None and manager.state is VoiceState.IDLE:
                accepted = await manager.submit_text(
                    str(pending_text["text"]),
                    speak=pending_text.get("speak") is not False,
                    queued_seconds=_seconds_since(pending_text.get("submitted_at")),
                )
                if accepted is not None:
                    pending_text = None
            await asyncio.sleep(poll_seconds)
    finally:
        if voice_command_task is not None:
            voice_command_task.cancel()
            await asyncio.gather(voice_command_task, return_exceptions=True)
        if text_request_task is not None:
            text_request_task.cancel()
            await asyncio.gather(text_request_task, return_exceptions=True)
        await manager.close()


async def run_text_request_loop(
    manager: VoiceSessionManager,
    *,
    text_request_source: Callable[[], Awaitable[dict | None]],
    poll_seconds: float = 0.05,
) -> None:
    """Atiende el chat escrito del panel sin abrir el micrófono.

    Comparte con el bucle de voz la sesión, la política y la cancelación; solo
    cambia la entrada. La cancelación se recibe desde la interfaz local.
    """

    request_task: asyncio.Task[dict | None] | None = None
    pending: dict | None = None
    try:
        while True:
            if request_task is None and pending is None:
                request_task = asyncio.create_task(text_request_source())
            if request_task is not None and request_task.done():
                try:
                    pending = request_task.result() or pending
                except Exception:
                    pass
                request_task = None
            if pending is not None and pending.get("cancel"):
                pending = None
                await manager.cancel_active(_PANEL_CANCEL_REASON)
            if pending is not None and manager.state is VoiceState.IDLE:
                accepted = await manager.submit_text(
                    str(pending["text"]),
                    speak=pending.get("speak") is not False,
                    queued_seconds=_seconds_since(pending.get("submitted_at")),
                )
                if accepted is not None:
                    pending = None
            await asyncio.sleep(poll_seconds)
    finally:
        if request_task is not None:
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        await manager.close()


def _seconds_since(timestamp: object) -> float | None:
    """Espera en cola de una solicitud del panel (reloj de pared compartido)."""

    if not isinstance(timestamp, str):
        return None
    try:
        submitted = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if submitted.tzinfo is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - submitted).total_seconds())
