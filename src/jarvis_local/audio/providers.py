from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import subprocess
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from ..cancellation import CancellationToken, OperationCancelled
from ..config import Settings
from .base import AudioError, STTProvider, TTSProvider
from .enrollment import validate_own_voice_consent
from .models import (
    AudioBuffer,
    SynthesizedAudio,
    TranscriptionResult,
    TranscriptionSegment,
)


class FasterWhisperSTTProvider(STTProvider):
    name = "faster_whisper"

    def __init__(self, settings: Settings) -> None:
        if settings.stt_model_path is None:
            raise AudioError(
                "model_not_configured",
                "stt.model_path no está configurado.",
                component="stt",
            )
        self.model_path = Path(settings.stt_model_path)
        self.language = settings.stt_language
        self.compute_type = settings.stt_compute_type
        self.cpu_threads = settings.stt_cpu_threads
        self.beam_size = settings.stt_beam_size
        self.vad_filter = settings.stt_vad_filter
        self.initial_prompt = settings.stt_initial_prompt or None
        self.hotwords = settings.stt_hotwords or None
        self.min_language_probability = settings.stt_min_language_probability
        self.min_average_log_probability = settings.stt_min_average_log_probability
        self._model: Any | None = None
        self._load_lock = asyncio.Lock()

    async def warmup(self) -> None:
        if self._model is not None:
            return
        async with self._load_lock:
            if self._model is not None:
                return
            if not (self.model_path / "model.bin").is_file():
                raise AudioError(
                    "model_missing",
                    f"No existe el modelo faster-whisper local: {self.model_path}",
                    component="stt",
                )

            def load():
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:
                    raise AudioError(
                        "dependency_missing",
                        "Falta faster-whisper; instala el extra 'audio'.",
                        component="stt",
                    ) from exc
                return WhisperModel(
                    str(self.model_path),
                    device="cpu",
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                    num_workers=1,
                    local_files_only=True,
                )

            try:
                self._model = await asyncio.to_thread(load)
            except AudioError:
                raise
            except Exception as exc:
                raise AudioError(
                    "model_load_failed",
                    f"No se pudo cargar faster-whisper: {exc}",
                    component="stt",
                ) from exc

    async def transcribe(
        self, audio: AudioBuffer, cancellation: CancellationToken
    ) -> TranscriptionResult:
        cancellation.raise_if_cancelled()
        await self.warmup()
        started = time.monotonic()
        float_audio = audio.samples.astype(np.float32) / 32768.0

        def run() -> tuple[list[Any], Any]:
            cancellation.raise_if_cancelled()
            segments, info = self._model.transcribe(
                float_audio,
                language=self.language,
                task="transcribe",
                beam_size=self.beam_size,
                condition_on_previous_text=False,
                initial_prompt=self.initial_prompt,
                hotwords=self.hotwords,
                vad_filter=self.vad_filter,
                vad_parameters={
                    "min_speech_duration_ms": 150,
                    "min_silence_duration_ms": 300,
                    "speech_pad_ms": 120,
                },
            )
            materialized = []
            for segment in segments:
                cancellation.raise_if_cancelled()
                materialized.append(segment)
            return materialized, info

        try:
            raw_segments, info = await asyncio.to_thread(run)
        except Exception as exc:
            if cancellation.is_cancelled:
                cancellation.raise_if_cancelled()
            raise AudioError(
                "transcription_failed",
                f"faster-whisper no pudo transcribir: {exc}",
                component="stt",
            ) from exc
        cancellation.raise_if_cancelled()
        segments = tuple(
            TranscriptionSegment(
                start=float(item.start),
                end=float(item.end),
                text=_safe_transcript_text(str(item.text)),
                average_log_probability=_optional_float(
                    getattr(item, "avg_logprob", None)
                ),
                no_speech_probability=_optional_float(
                    getattr(item, "no_speech_prob", None)
                ),
            )
            for item in raw_segments
            if str(item.text).strip()
        )
        text = " ".join(item.text for item in segments).strip()
        weighted_log_probability = _weighted_log_probability(segments)
        language = str(getattr(info, "language", self.language) or self.language)
        language_probability = _optional_float(
            getattr(info, "language_probability", None)
        )
        reasons: list[str] = []
        if not text:
            reasons.append("no_speech")
        if language_probability is not None and language_probability < self.min_language_probability:
            reasons.append("low_language_probability")
        if (
            weighted_log_probability is not None
            and weighted_log_probability < self.min_average_log_probability
        ):
            reasons.append("low_transcription_probability")
        return TranscriptionResult(
            text=text,
            language=language,
            language_probability=language_probability,
            average_log_probability=weighted_log_probability,
            ambiguous=bool(reasons),
            ambiguity_reasons=tuple(reasons),
            processing_seconds=time.monotonic() - started,
            segments=segments,
        )


class PiperTTSProvider(TTSProvider):
    name = "piper"

    def __init__(self, settings: Settings) -> None:
        if settings.tts_voice_path is None:
            raise AudioError(
                "voice_not_configured",
                "tts.voice_path no está configurado.",
                component="tts",
            )
        self.voice_path = Path(settings.tts_voice_path)
        self.config_path = settings.tts_config_path
        self.speed = settings.tts_speed
        self.volume = settings.tts_volume
        self._voice: Any | None = None
        self._load_lock = asyncio.Lock()

    async def warmup(self) -> None:
        if self._voice is not None:
            return
        async with self._load_lock:
            if self._voice is not None:
                return
            if not self.voice_path.is_file():
                raise AudioError(
                    "voice_missing",
                    f"No existe la voz Piper local: {self.voice_path}",
                    component="tts",
                )

            def load():
                try:
                    from piper import PiperVoice
                except ImportError as exc:
                    raise AudioError(
                        "dependency_missing",
                        "Falta piper-tts; instala el extra 'audio'.",
                        component="tts",
                    ) from exc
                return PiperVoice.load(
                    self.voice_path,
                    config_path=self.config_path,
                    use_cuda=False,
                )

            try:
                self._voice = await asyncio.to_thread(load)
            except AudioError:
                raise
            except Exception as exc:
                raise AudioError(
                    "voice_load_failed",
                    f"No se pudo cargar la voz Piper: {exc}",
                    component="tts",
                ) from exc

    async def synthesize(
        self, text: str, cancellation: CancellationToken
    ) -> SynthesizedAudio:
        normalized = " ".join(text.split())
        if not normalized:
            raise AudioError("empty_text", "No hay texto para sintetizar.", component="tts")
        cancellation.raise_if_cancelled()
        await self.warmup()
        started = time.monotonic()

        def run() -> tuple[np.ndarray, int, int]:
            from piper import SynthesisConfig

            cancellation.raise_if_cancelled()
            config = SynthesisConfig(
                length_scale=1.0 / self.speed,
                volume=self.volume,
                normalize_audio=True,
            )
            chunks: list[np.ndarray] = []
            sample_rate = 0
            channels = 1
            for chunk in self._voice.synthesize(normalized, syn_config=config):
                cancellation.raise_if_cancelled()
                sample_rate = int(chunk.sample_rate)
                channels = int(chunk.sample_channels)
                chunks.append(np.asarray(chunk.audio_int16_array, dtype=np.int16).copy())
            if not chunks or sample_rate <= 0:
                raise AudioError(
                    "empty_audio", "Piper no produjo audio.", component="tts"
                )
            return np.concatenate(chunks), sample_rate, channels

        try:
            samples, sample_rate, channels = await asyncio.to_thread(run)
        except AudioError:
            raise
        except Exception as exc:
            if cancellation.is_cancelled:
                cancellation.raise_if_cancelled()
            raise AudioError(
                "synthesis_failed",
                f"Piper no pudo sintetizar: {exc}",
                component="tts",
            ) from exc
        cancellation.raise_if_cancelled()
        return SynthesizedAudio(
            samples=samples,
            sample_rate=sample_rate,
            channels=channels,
            synthesis_seconds=time.monotonic() - started,
        )


class ChatterboxTTSProvider(TTSProvider):
    """Cliente de un worker aislado para clonación local de la voz propia.

    El proceso separado evita mezclar el stack PyTorch/NumPy de Chatterbox con
    el núcleo y permite una cancelación dura de inferencia. Por defecto usa CPU
    para no competir con Qwen3-8B por los 8 GB de VRAM.
    """

    name = "chatterbox"

    def __init__(self, settings: Settings) -> None:
        self.python = settings.tts_clone_python
        self.model_path = settings.tts_clone_model_path
        self.model_file = settings.tts_clone_model_file
        self.reference_path = settings.tts_clone_reference_path
        self.consent_path = settings.tts_clone_consent_path
        self.device = settings.tts_clone_device
        self.language = "es"
        self.timeout_seconds = settings.tts_clone_timeout_seconds
        self.exaggeration = settings.tts_clone_exaggeration
        self.cfg_weight = settings.tts_clone_cfg_weight
        self.temperature = settings.tts_clone_temperature
        self.log_path = settings.data_dir / "logs" / "chatterbox-worker.log"
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    def _validate_files(self) -> None:
        required = {
            "python": self.python,
            "model_path": self.model_path,
            "reference_path": self.reference_path,
            "consent_path": self.consent_path,
        }
        missing = [name for name, path in required.items() if path is None]
        if missing:
            raise AudioError(
                "clone_not_configured",
                "Falta configuración de clonación: " + ", ".join(missing),
                component="voice_clone",
            )
        if not self.python.is_file():
            raise AudioError(
                "clone_environment_missing",
                f"No existe el Python aislado de Chatterbox: {self.python}",
                component="voice_clone",
            )
        model_files = (
            "ve.pt",
            "s3gen.pt",
            "grapheme_mtl_merged_expanded_v1.json",
            self.model_file,
            "pkuseg/spacy_ontonotes/features.msgpack",
            "pkuseg/spacy_ontonotes/weights.npz",
        )
        absent = [name for name in model_files if not (self.model_path / name).is_file()]
        if absent:
            raise AudioError(
                "clone_model_missing",
                "Faltan archivos de Chatterbox: " + ", ".join(absent),
                component="voice_clone",
            )
        validate_own_voice_consent(self.reference_path, self.consent_path)

    def _command(self) -> list[str]:
        return [
            str(self.python),
            "-m",
            "jarvis_local.chatterbox_worker",
            "--model-dir",
            str(self.model_path),
            "--model-file",
            self.model_file,
            "--reference",
            str(self.reference_path),
            "--device",
            self.device,
            "--language",
            self.language,
        ]

    async def warmup(self) -> None:
        async with self._lock:
            await self._ensure_started()

    async def _ensure_started(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        self._validate_files()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = self.log_path.open("ab", buffering=0)
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            worker_environment = os.environ.copy()
            worker_environment.update(
                {
                    "PKUSEG_HOME": str(self.model_path / "pkuseg"),
                    "HF_HUB_OFFLINE": "1",
                    "TRANSFORMERS_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1",
                }
            )
            self._process = await asyncio.create_subprocess_exec(
                *self._command(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=log_handle,
                cwd=str(self.model_path),
                env=worker_environment,
                creationflags=creation_flags,
            )
        except Exception as exc:
            self._process = None
            raise AudioError(
                "clone_worker_start_failed",
                f"No se pudo iniciar Chatterbox: {exc}",
                component="voice_clone",
            ) from exc
        finally:
            log_handle.close()
        try:
            line = await asyncio.wait_for(
                self._process.stdout.readline(), timeout=self.timeout_seconds
            )
            payload = json.loads(line.decode("utf-8")) if line else {}
            if payload.get("type") != "ready":
                raise RuntimeError(payload or f"worker terminó: {self._process.returncode}")
        except Exception as exc:
            await self._stop_process()
            raise AudioError(
                "clone_worker_not_ready",
                f"Chatterbox no quedó listo: {exc}. Revisa {self.log_path}",
                component="voice_clone",
            ) from exc

    async def synthesize(
        self, text: str, cancellation: CancellationToken
    ) -> SynthesizedAudio:
        normalized = " ".join(text.split())
        if not normalized:
            raise AudioError("empty_text", "No hay texto para sintetizar.", component="tts")
        cancellation.raise_if_cancelled()
        async with self._lock:
            await self._ensure_started()
            started = time.monotonic()
            request_id = str(uuid.uuid4())
            request = {
                "id": request_id,
                "command": "synthesize",
                "text": normalized,
                "exaggeration": self.exaggeration,
                "cfg_weight": self.cfg_weight,
                "temperature": self.temperature,
            }
            process = self._process
            try:
                process.stdin.write(
                    (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
                )
                await process.stdin.drain()
                read_task = asyncio.create_task(process.stdout.readline())
                cancel_task = asyncio.create_task(cancellation.wait())
                done, _ = await asyncio.wait(
                    {read_task, cancel_task},
                    timeout=self.timeout_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_task in done or cancellation.is_cancelled:
                    await self._stop_process()
                    read_task.cancel()
                    await asyncio.gather(read_task, return_exceptions=True)
                    cancellation.raise_if_cancelled()
                if read_task not in done:
                    await self._stop_process()
                    read_task.cancel()
                    cancel_task.cancel()
                    await asyncio.gather(read_task, cancel_task, return_exceptions=True)
                    raise AudioError(
                        "synthesis_timeout",
                        "Chatterbox excedió el tiempo máximo; el worker fue detenido.",
                        component="voice_clone",
                    )
                cancel_task.cancel()
                await asyncio.gather(cancel_task, return_exceptions=True)
                line = read_task.result()
                payload = json.loads(line.decode("utf-8")) if line else {}
                if payload.get("id") != request_id or payload.get("ok") is not True:
                    error = payload.get("error") or {}
                    raise AudioError(
                        str(error.get("code") or "synthesis_failed"),
                        str(error.get("message") or "Respuesta inválida del worker."),
                        component="voice_clone",
                    )
                raw = base64.b64decode(payload["pcm16_base64"], validate=True)
                samples = np.frombuffer(raw, dtype="<i2").astype(np.int16, copy=True)
                cancellation.raise_if_cancelled()
                return SynthesizedAudio(
                    samples=samples,
                    sample_rate=int(payload["sample_rate"]),
                    channels=int(payload.get("channels", 1)),
                    synthesis_seconds=time.monotonic() - started,
                )
            except (AudioError, OperationCancelled):
                raise
            except Exception as exc:
                await self._stop_process()
                raise AudioError(
                    "synthesis_failed",
                    f"Falló el worker Chatterbox: {exc}",
                    component="voice_clone",
                ) from exc

    async def _stop_process(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def aclose(self) -> None:
        async with self._lock:
            await self._stop_process()


def create_stt_provider(settings: Settings) -> STTProvider:
    if settings.stt_provider == "faster_whisper":
        return FasterWhisperSTTProvider(settings)
    raise AudioError(
        "unsupported_provider",
        f"Proveedor STT no soportado: {settings.stt_provider}",
        component="stt",
    )


def create_tts_provider(settings: Settings) -> TTSProvider:
    if settings.tts_provider == "piper":
        return PiperTTSProvider(settings)
    if settings.tts_provider == "chatterbox":
        return ChatterboxTTSProvider(settings)
    raise AudioError(
        "unsupported_provider",
        f"Proveedor TTS no soportado: {settings.tts_provider}",
        component="tts",
    )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _safe_transcript_text(value: str) -> str:
    """Normaliza texto del tokenizer y elimina Unicode no serializable.

    Algunos tokenizers pueden producir sustitutos aislados ante audio difícil.
    Esos valores no son UTF-8 válido y romperían el transporte JSON al LLM.
    No se corrigen palabras: solo se reemplazan code points inválidos y controles.
    """

    valid = value.encode("utf-8", errors="replace").decode("utf-8")
    normalized = unicodedata.normalize("NFC", valid)
    normalized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", normalized)
    return " ".join(normalized.split())


def _weighted_log_probability(
    segments: tuple[TranscriptionSegment, ...]
) -> float | None:
    values = [
        (max(item.end - item.start, 0.01), item.average_log_probability)
        for item in segments
        if item.average_log_probability is not None
    ]
    if not values:
        return None
    total = sum(weight for weight, _ in values)
    return sum(weight * float(value) for weight, value in values) / total
