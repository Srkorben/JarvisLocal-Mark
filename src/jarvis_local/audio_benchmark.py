from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import subprocess
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np

from .audio import (
    AudioBuffer,
    AudioPlayer,
    AudioRecorder,
    SoundDevicePlayer,
    VoiceSessionManager,
    create_stt_provider,
    create_tts_provider,
)
from .benchmark import _process_working_set_mib
from .cancellation import CancellationController, CancellationToken, OperationCancelled
from .cli import default_config_path
from .config import Settings
from .database import Database
from .execution import ActionExecutor
from .memory import MemoryRepository
from .model_providers import create_model_provider
from .orchestrator import Orchestrator
from .policy import PolicyEngine
from .projects import ProjectService
from .tools import build_default_registry


SPANISH_CASES = (
    "Mark, abre el proyecto JarvisLocal.",
    "Busca el archivo README punto eme de.",
    "Consulta el estado de Git del proyecto.",
    "¿Cuál es la decisión vigente sobre SQLite?",
    "Busca documentos relacionados con Qwen tres y llama punto ce pe pe.",
)

FULL_TURN_TEXT = (
    "Mark, consulta la hora local actual utilizando la herramienta apropiada."
)


class BufferRecorder(AudioRecorder):
    def __init__(self, audio: AudioBuffer) -> None:
        self.audio = audio
        self.active = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> AudioBuffer:
        self.active = False
        return self.audio

    def abort(self) -> None:
        self.active = False

    @property
    def elapsed_seconds(self) -> float:
        return self.audio.duration_seconds if self.active else 0.0


class MeasuringPlayer(AudioPlayer):
    def __init__(self, delegate: AudioPlayer | None = None) -> None:
        self.delegate = delegate
        self.play_calls = 0
        self.audio_seconds = 0.0

    async def play(self, audio, cancellation) -> float:
        self.play_calls += 1
        self.audio_seconds += audio.duration_seconds
        if self.delegate is not None:
            return await self.delegate.play(audio, cancellation)
        cancellation.raise_if_cancelled()
        return 0.0

    def stop(self) -> None:
        if self.delegate is not None:
            self.delegate.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark reproducible de voz local")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "--hardware-output",
        action="store_true",
        help="Reproduce la respuesta del turno y mide corte real del dispositivo.",
    )
    return parser.parse_args()


async def run_benchmark(settings: Settings, *, hardware_output: bool) -> dict[str, Any]:
    stt = create_stt_provider(settings)
    tts = create_tts_provider(settings)
    token = CancellationToken()
    process_ram_before = _process_working_set_mib(os.getpid())
    gpu_before = _gpu_memory_mib()
    started = time.monotonic()
    await stt.warmup()
    stt_load_seconds = time.monotonic() - started
    started = time.monotonic()
    await tts.warmup()
    tts_load_seconds = time.monotonic() - started
    process_ram_loaded = _process_working_set_mib(os.getpid())

    cases: list[dict[str, Any]] = []
    for expected in SPANISH_CASES:
        spoken = await tts.synthesize(expected, token)
        buffer = _as_buffer(spoken)
        transcript = await stt.transcribe(buffer, token)
        wer = _word_error_rate(expected, transcript.text)
        cases.append(
            {
                "expected": expected,
                "transcript": transcript.text,
                "word_error_rate": wer,
                "ambiguous": transcript.ambiguous,
                "ambiguity_reasons": list(transcript.ambiguity_reasons),
                "audio_seconds": buffer.duration_seconds,
                "synthesis_seconds": spoken.synthesis_seconds,
                "transcription_seconds": transcript.processing_seconds,
                "real_time_factor": (
                    transcript.processing_seconds / buffer.duration_seconds
                    if buffer.duration_seconds
                    else None
                ),
            }
        )

    full_input = await tts.synthesize(FULL_TURN_TEXT, token)
    full_buffer = _as_buffer(full_input)
    full_turn = await _run_full_turn(
        settings,
        stt=stt,
        tts=tts,
        audio=full_buffer,
        hardware_output=hardware_output,
    )
    interruption = (
        await _measure_hardware_interruption(settings, tts)
        if hardware_output
        else {
            "executed": False,
            "reason": "Requiere --hardware-output para producir sonido real.",
        }
    )
    process_ram_after = _process_working_set_mib(os.getpid())
    await stt.aclose()
    await tts.aclose()
    wers = [item["word_error_rate"] for item in cases]
    transcription_times = [item["transcription_seconds"] for item in cases]
    return {
        "benchmark_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "synthetic_piper_to_whisper_with_real_core",
        "models": {
            "stt": {
                "provider": settings.stt_provider,
                "path": str(settings.stt_model_path),
                "compute_type": settings.stt_compute_type,
                "device": "cpu",
                "bytes": _path_size(settings.stt_model_path),
                "load_seconds": stt_load_seconds,
            },
            "tts": {
                "provider": settings.tts_provider,
                "path": str(settings.tts_voice_path),
                "language": settings.tts_language,
                "device": "cpu",
                "bytes": _path_size(settings.tts_voice_path),
                "load_seconds": tts_load_seconds,
            },
        },
        "runtime": {
            "python_process_ram_before_mib": process_ram_before,
            "python_process_ram_models_loaded_mib": process_ram_loaded,
            "python_process_ram_after_mib": process_ram_after,
            "gpu_memory_before_mib": gpu_before,
            "gpu_memory_after_mib": _gpu_memory_mib(),
        },
        "speech_recognition": {
            "cases": cases,
            "mean_word_error_rate": statistics.fmean(wers),
            "median_transcription_seconds": statistics.median(transcription_times),
            "passed_non_ambiguous": sum(not item["ambiguous"] for item in cases),
            "total": len(cases),
            "caveat": (
                "Piper→Whisper es reproducible, pero no sustituye una evaluación "
                "con la voz, micrófono y ruido reales del usuario."
            ),
        },
        "full_turn": full_turn,
        "tts_interruption": interruption,
    }


async def _run_full_turn(
    settings: Settings,
    *,
    stt,
    tts,
    audio: AudioBuffer,
    hardware_output: bool,
) -> dict[str, Any]:
    temporary_parent = settings.project_dir / "benchmarks" / ".tmp"
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix="jarvis-voice-benchmark-", dir=temporary_parent
    ) as directory:
        root = Path(directory).resolve()
        benchmark_settings = settings.model_copy(
            update={
                "project_dir": root,
                "data_dir": root / "data",
                "database_path": root / "data" / "benchmark.db",
                "allowed_roots": (root,),
                "allowed_tools": frozenset({"get_current_time"}),
                "max_steps_per_turn": 3,
                "max_tool_rounds": 3,
            }
        )
        database = Database(benchmark_settings.database_path)
        policy = PolicyEngine(benchmark_settings)
        projects = ProjectService(database, policy)
        project = projects.ensure_bootstrap_project("Benchmark de voz", root)
        memory = MemoryRepository(database)
        registry = build_default_registry(benchmark_settings, policy, memory=memory)
        executor = ActionExecutor(
            settings=benchmark_settings,
            database=database,
            registry=registry,
            policy=policy,
            projects=projects,
            memory=memory,
        )
        provider = await create_model_provider(benchmark_settings, allow_start=True)
        delegate = (
            SoundDevicePlayer(selector=benchmark_settings.audio_output_device)
            if hardware_output
            else None
        )
        player = MeasuringPlayer(delegate)
        manager = VoiceSessionManager(
            database=database,
            orchestrator=Orchestrator(
                settings=benchmark_settings,
                database=database,
                provider=provider,
                registry=registry,
                executor=executor,
            ),
            project=project,
            session_id=database.create_session(project_id=project.id),
            cancellation=CancellationController(),
            recorder=BufferRecorder(audio),
            player=player,
            stt=stt,
            tts=tts,
            min_record_seconds=benchmark_settings.audio_min_record_seconds,
            min_rms=benchmark_settings.audio_min_rms,
            max_turn_seconds=benchmark_settings.max_runtime_seconds,
            max_record_seconds=benchmark_settings.audio_max_record_seconds,
        )
        try:
            await manager.start_recording()
            result = await (await manager.finish_recording())
            tool_events = 0
            with database.connection() as connection:
                tool_events = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM audit_events WHERE tool_name = ?",
                        ("get_current_time",),
                    ).fetchone()[0]
                )
            valid_audit, audit_errors = database.verify_audit_chain()
            return {
                "input_text": FULL_TURN_TEXT,
                "transcript": result.transcript,
                "response": result.response,
                "outcome": result.outcome,
                "error": result.error,
                "metrics": result.metrics.model_dump(mode="json"),
                "tool": "get_current_time",
                "tool_audit_events": tool_events,
                "tool_executed": tool_events == 1,
                "audio_play_calls": player.play_calls,
                "generated_audio_seconds": player.audio_seconds,
                "hardware_output": hardware_output,
                "audit_valid": valid_audit,
                "audit_errors": audit_errors,
                "passed": (
                    result.outcome == "success"
                    and tool_events == 1
                    and player.play_calls >= 1
                    and valid_audit
                ),
            }
        finally:
            await manager.close()
            await provider.aclose()


async def _measure_hardware_interruption(settings: Settings, tts) -> dict[str, Any]:
    text = (
        "Esta reproducción es deliberadamente larga para comprobar que la tecla "
        "de cancelación detiene el audio de Mark de forma inmediata y consistente."
    )
    audio = await tts.synthesize(text, CancellationToken())
    player = SoundDevicePlayer(selector=settings.audio_output_device)
    token = CancellationToken()
    task = asyncio.create_task(player.play(audio, token))
    await asyncio.sleep(0.25)
    started = time.monotonic()
    token.cancel("benchmark de interrupción TTS")
    player.stop()
    cancelled = False
    try:
        await asyncio.wait_for(task, timeout=3)
    except OperationCancelled:
        cancelled = True
    return {
        "executed": True,
        "cancelled": cancelled,
        "latency_seconds": time.monotonic() - started,
        "source_audio_seconds": audio.duration_seconds,
        "passed": cancelled,
    }


def _as_buffer(audio) -> AudioBuffer:
    samples = np.asarray(audio.samples, dtype=np.int16)
    return AudioBuffer(
        samples=samples,
        sample_rate=audio.sample_rate,
        duration_seconds=audio.duration_seconds,
        rms=float(np.sqrt(np.mean((samples.astype(np.float32) / 32768.0) ** 2))),
    )


def _normalized_words(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.findall(r"[a-z0-9]+", normalized)


def _word_error_rate(expected: str, actual: str) -> float:
    reference = _normalized_words(expected)
    hypothesis = _normalized_words(actual)
    if not reference:
        return 0.0 if not hypothesis else 1.0
    previous = list(range(len(hypothesis) + 1))
    for row, expected_word in enumerate(reference, start=1):
        current = [row]
        for column, actual_word in enumerate(hypothesis, start=1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (expected_word != actual_word),
                )
            )
        previous = current
    return previous[-1] / len(reference)


def _path_size(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _gpu_memory_mib() -> int | None:
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return int(completed.stdout.splitlines()[0].strip())
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return None


def render_markdown(result: dict[str, Any]) -> str:
    stt = result["models"]["stt"]
    tts = result["models"]["tts"]
    recognition = result["speech_recognition"]
    full_turn = result["full_turn"]
    metrics = full_turn["metrics"]
    interruption = result["tts_interruption"]
    lines = [
        "# Benchmark de voz — Fase 2",
        "",
        f"Fecha UTC: {result['timestamp_utc']}",
        "",
        "## Configuración",
        "",
        f"- STT: `{stt['provider']}` / CPU `{stt['compute_type']}` / {stt['bytes']} bytes",
        f"- TTS: `{tts['provider']}` / `{tts['language']}` / CPU / {tts['bytes']} bytes",
        f"- Carga STT/TTS: {stt['load_seconds']:.3f} / {tts['load_seconds']:.3f} s",
        "- Entrada de calidad: audio Piper sintetizado; no representa el micrófono ni la voz real.",
        "",
        "## Reconocimiento reproducible",
        "",
        f"- Casos no ambiguos: {recognition['passed_non_ambiguous']}/{recognition['total']}",
        f"- WER medio: {recognition['mean_word_error_rate']:.3f}",
        f"- Mediana de transcripción: {recognition['median_transcription_seconds']:.3f} s",
        "",
        "| Esperado | Transcripción | WER | STT |",
        "|---|---|---:|---:|",
    ]
    for case in recognition["cases"]:
        lines.append(
            f"| {case['expected']} | {case['transcript']} | "
            f"{case['word_error_rate']:.3f} | {case['transcription_seconds']:.3f} s |"
        )
    lines.extend(
        [
            "",
            "## Turno completo",
            "",
            f"- Resultado: `{full_turn['outcome']}`; aprobado: **{full_turn['passed']}**",
            f"- Transcripción: {full_turn['transcript']}",
            f"- Herramienta auditada: `{full_turn['tool']}` ({full_turn['tool_audit_events']} evento)",
            f"- TTFT desde cierre de captura: {metrics['first_token_seconds']} s",
            f"- Primer audio generado: {metrics['first_audio_seconds']} s",
            f"- Transcripción: {metrics['transcription_seconds']} s",
            f"- Duración total: {metrics['total_seconds']} s",
            f"- Audio físico: {full_turn['hardware_output']}",
            f"- Auditoría válida: {full_turn['audit_valid']}",
            "",
            "## Interrupción TTS",
            "",
            f"- Ejecutada sobre hardware: {interruption['executed']}",
            f"- Resultado: {interruption.get('passed', False)}",
            f"- Latencia: {interruption.get('latency_seconds')} s",
            "",
            "## Limitaciones",
            "",
            "La calidad automática usa Piper→Whisper y solo sirve como regresión reproducible. "
            "La prueba física abre los dispositivos, pero una persona debe validar inteligibilidad, "
            "ruido ambiente y comodidad. faster-whisper comprueba la cancelación entre segmentos "
            "y al terminar la inferencia; CTranslate2 no garantiza cortar un kernel CPU ya iniciado.",
            "",
        ]
    )
    return "\n".join(lines)


async def async_main() -> int:
    args = parse_args()
    settings = Settings.load(args.config)
    result = await run_benchmark(settings, hardware_output=args.hardware_output)
    output_dir = settings.project_dir / "benchmarks" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "audio-phase2.json"
    markdown_path = output_dir / "audio-phase2.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    # Windows PowerShell puede conservar una página ANSI aunque los archivos
    # sean UTF-8. Escapar Unicode evita que el reporte falle después de medir.
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["full_turn"]["passed"] else 1


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
