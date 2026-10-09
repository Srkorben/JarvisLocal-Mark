"""Benchmark local de latencia de Mark (Ref 1.0).

Mide interacciones sintéticas de texto y voz con los componentes reales:
primer token, respuesta completa, tokens/s, STT, primer audio, total, RAM y
VRAM. Separa la ejecución en frío de las repeticiones en caliente e informa
medianas y p90.

Privacidad: usa una base de datos temporal (nunca ``data/jarvis.db``), genera
la voz de entrada con el propio TTS y no guarda texto de respuestas.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from .audio import VoiceSessionManager, create_stt_provider, create_tts_provider
from .audio.base import AudioPlayer
from .audio_benchmark import BufferRecorder, _as_buffer
from .benchmark import _gpu_memory_mib, _process_working_set_mib
from .cancellation import CancellationController, CancellationToken
from .cli import default_config_path
from .config import Settings
from .database import Database
from .execution import ActionExecutor
from .latency import LatencyLog, TurnTrace
from .memory import MemoryRepository
from .model_providers import create_model_provider
from .orchestrator import Orchestrator
from .policy import PolicyEngine
from .projects import ProjectService
from .tools import build_default_registry


TEXT_SCENARIOS = {
    "text_short": "Responde en una sola frase: ¿qué puedes hacer por mí?",
    "text_long": (
        "Explica en unos seis párrafos cómo organizar un proyecto de software pequeño, "
        "desde la planificación hasta el mantenimiento."
    ),
    "text_tool": "Usa la herramienta adecuada para decirme la hora local actual.",
}
VOICE_SCENARIOS = {
    "voice_short": "Mark, saluda brevemente y dime en una frase cómo estás.",
    "voice_long": (
        "Mark, explícame en varios párrafos cómo preparar una buena presentación "
        "para una reunión de trabajo."
    ),
}


class CapturingLatencyLog(LatencyLog):
    def __init__(self) -> None:
        super().__init__(None)
        self.records: list[dict[str, Any]] = []

    def write(self, trace: TurnTrace) -> None:
        self.records.append(trace.as_record())


class RealtimeSilentPlayer(AudioPlayer):
    """Ocupa el tiempo real del audio sin sonar: conserva el solapamiento
    síntesis/reproducción del turno sin necesitar altavoces."""

    async def play(self, audio, cancellation) -> float:
        duration = audio.duration_seconds
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            cancellation.raise_if_cancelled()
            await asyncio.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        return duration

    def stop(self) -> None:
        return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark local de latencia de Mark")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument(
        "--profile",
        choices=("text", "voice"),
        default="voice",
        help="text: solo LLM (GPU libre para el modelo). voice: STT+TTS cargados como en la conversación por voz.",
    )
    parser.add_argument("--repeat", type=int, default=5, help="Repeticiones en caliente por escenario.")
    parser.add_argument("--scenarios", nargs="*", help="Subconjunto de escenarios a ejecutar.")
    parser.add_argument("--tts-provider", choices=("piper", "chatterbox"))
    parser.add_argument("--tts-device", choices=("cpu", "cuda"))
    parser.add_argument("--audio-output", action="store_true", help="Reproduce las respuestas por los altavoces.")
    parser.add_argument("--output-dir", type=Path, help="Por defecto: data/benchmarks/latency.")
    args = parser.parse_args(argv)
    if not 1 <= args.repeat <= 50:
        parser.error("--repeat debe estar entre 1 y 50")
    return args


def percentile(values: list[float], fraction: float) -> float | None:
    """Percentil por rango más cercano (sin interpolación)."""

    clean = sorted(value for value in values if value is not None)
    if not clean:
        return None
    rank = max(1, math.ceil(fraction * len(clean)))
    return clean[rank - 1]


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    keys = (
        "first_token_seconds",
        "llm_done_seconds",
        "first_audio_seconds",
        "estimated_sequential_first_audio_seconds",
        "stt_seconds",
        "total_seconds",
        "tokens_per_second",
        "completion_tokens",
        "prompt_tokens",
        "rounds",
        "vram_used_mib",
    )
    summary: dict[str, Any] = {
        "runs": len(runs),
        "errors": sum(1 for run in runs if run.get("error")),
    }
    for key in keys:
        values = [run[key] for run in runs if isinstance(run.get(key), (int, float))]
        if values:
            summary[key] = {
                "median": round(statistics.median(values), 3),
                "p90": round(percentile(values, 0.9), 3),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
            }
    return summary


def run_from_trace(record: dict[str, Any] | None) -> dict[str, Any]:
    if not record:
        return {}
    stages = record.get("stages", {})
    rounds = record.get("rounds", [])
    completion = sum(item.get("completion_tokens") or 0 for item in rounds) or None
    speeds = [
        item.get("server_predicted_per_second") or item.get("tokens_per_second")
        for item in rounds
    ]
    speeds = [value for value in speeds if isinstance(value, (int, float))]
    return {
        "first_token_seconds": stages.get("first_token"),
        "llm_done_seconds": stages.get("llm_done"),
        "first_audio_seconds": stages.get("first_audio"),
        "total_seconds": record.get("total_seconds"),
        "stt_seconds": record.get("stt_seconds"),
        "rounds": len(rounds),
        "tools": [tool["name"] for item in rounds for tool in item.get("tools", [])],
        "completion_tokens": completion,
        "prompt_tokens": (rounds[0].get("prompt_tokens") if rounds else None),
        "tokens_per_second": (statistics.median(speeds) if speeds else None),
        "outcome": record.get("outcome"),
        **_sequential_estimate(record),
    }


def _sequential_estimate(record: dict[str, Any]) -> dict[str, Any]:
    """Estima el primer audio del método anterior (hablar tras la respuesta
    completa, sin solapar): fin del LLM + síntesis media de una frase. Es una
    estimación derivada de la misma ejecución, no una medición."""

    sentences = record.get("sentences_spoken") or 0
    llm_done = record.get("stages", {}).get("llm_done")
    synthesis = record.get("synthesis_seconds")
    if not sentences or llm_done is None or synthesis is None:
        return {}
    return {
        "estimated_sequential_first_audio_seconds": round(llm_done + synthesis / sentences, 3)
    }


async def run_suite(
    settings: Settings,
    *,
    profile: str,
    repeat: int,
    scenarios: list[str] | None = None,
    player: AudioPlayer | None = None,
    provider_factory: Callable[..., Any] = create_model_provider,
    stt_factory: Callable[[Settings], Any] = create_stt_provider,
    tts_factory: Callable[[Settings], Any] = create_tts_provider,
    resource_probe: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    selected_text = [name for name in TEXT_SCENARIOS if not scenarios or name in scenarios]
    selected_voice = (
        [name for name in VOICE_SCENARIOS if not scenarios or name in scenarios]
        if profile == "voice"
        else []
    )
    probe = resource_probe or (lambda: _resources(None))
    result: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": profile,
        "repeat": repeat,
        "model": settings.model,
        "context_tokens": settings.context_tokens,
        "tts_provider": settings.effective_tts[0] if profile == "voice" else None,
        "tts_device": settings.effective_tts[1] if profile == "voice" else None,
        "startup": {},
        "resources_before": probe(),
        "scenarios": {},
    }
    with TemporaryDirectory(prefix="mark-latency-") as directory:
        bench_settings = settings.model_copy(
            update={
                "data_dir": Path(directory),
                "database_path": Path(directory) / "benchmark.db",
            }
        )
        database = Database(bench_settings.database_path)
        policy = PolicyEngine(bench_settings)
        projects = ProjectService(database, policy)
        project = projects.ensure_bootstrap_project("JarvisLocal", bench_settings.project_dir)
        memory = MemoryRepository(database)
        registry = build_default_registry(
            bench_settings, policy, memory=memory, projects=projects
        )
        executor = ActionExecutor(
            settings=bench_settings,
            database=database,
            registry=registry,
            policy=policy,
            projects=projects,
            memory=memory,
        )
        stt = tts = None
        if profile == "voice":
            # Mismo orden que la conversación por voz: la voz reserva su
            # memoria antes de que llama-server calcule el offload.
            started = time.monotonic()
            stt = stt_factory(bench_settings)
            await stt.warmup()
            result["startup"]["stt_load_seconds"] = round(time.monotonic() - started, 3)
            started = time.monotonic()
            tts = tts_factory(bench_settings)
            await tts.warmup()
            result["startup"]["tts_load_seconds"] = round(time.monotonic() - started, 3)
        started = time.monotonic()
        provider = await provider_factory(bench_settings, allow_start=True)
        result["startup"]["llm_ready_seconds"] = round(time.monotonic() - started, 3)
        result["resources_loaded"] = probe()
        log = CapturingLatencyLog()
        orchestrator = Orchestrator(
            settings=bench_settings,
            database=database,
            provider=provider,
            registry=registry,
            executor=executor,
            latency_log=log,
        )
        try:
            for name in selected_text:
                result["scenarios"][name] = await _run_text_scenario(
                    orchestrator, database, project, TEXT_SCENARIOS[name], repeat, log, probe
                )
            for name in selected_voice:
                result["scenarios"][name] = await _run_voice_scenario(
                    bench_settings,
                    orchestrator,
                    database,
                    project,
                    VOICE_SCENARIOS[name],
                    repeat,
                    log,
                    probe,
                    stt=stt,
                    tts=tts,
                    player=player or RealtimeSilentPlayer(),
                )
        finally:
            await provider.aclose()
            if stt is not None:
                await stt.aclose()
            if tts is not None:
                await tts.aclose()
    return result


async def _run_text_scenario(orchestrator, database, project, prompt, repeat, log, probe):
    runs = []
    for index in range(repeat + 1):
        session_id = database.create_session(project_id=project.id)
        error = None
        try:
            await orchestrator.chat(session_id, project, prompt, CancellationToken())
        except Exception as exc:  # se registra el tipo, nunca el contenido
            error = type(exc).__name__
        record = log.records[-1] if log.records else None
        run = run_from_trace(record) | {"phase": "cold" if index == 0 else "warm"}
        run.update(probe())
        if error:
            run["error"] = error
        runs.append(run)
    return _scenario_result(runs)


async def _run_voice_scenario(
    settings, orchestrator, database, project, prompt, repeat, log, probe, *, stt, tts, player
):
    spoken = await tts.synthesize(prompt, CancellationToken())
    buffer = _as_buffer(spoken)
    if buffer.sample_rate != settings.audio_sample_rate:
        buffer = _resample(buffer, settings.audio_sample_rate)
    runs = []
    for index in range(repeat + 1):
        manager = VoiceSessionManager(
            database=database,
            orchestrator=orchestrator,
            project=project,
            session_id=database.create_session(project_id=project.id),
            cancellation=CancellationController(),
            recorder=BufferRecorder(buffer),
            player=player,
            stt=stt,
            tts=tts,
            min_record_seconds=settings.audio_min_record_seconds,
            min_rms=0.0,
            max_turn_seconds=settings.max_runtime_seconds,
            max_record_seconds=settings.audio_max_record_seconds,
            latency_log=log,
        )
        error = None
        try:
            await manager.start_recording()
            task = await manager.finish_recording()
            turn = await task if task is not None else None
            if turn is not None and turn.outcome != "success":
                error = turn.outcome
        except Exception as exc:
            error = type(exc).__name__
        record = log.records[-1] if log.records else None
        run = run_from_trace(record) | {"phase": "cold" if index == 0 else "warm"}
        run.update(probe())
        if error:
            run["error"] = error
        runs.append(run)
    return _scenario_result(runs)


def _scenario_result(runs: list[dict[str, Any]]) -> dict[str, Any]:
    warm = [run for run in runs if run["phase"] == "warm"]
    return {"cold": runs[0], "warm": summarize(warm), "runs": runs}


def _resample(buffer, rate: int):
    import numpy as np

    from .audio import AudioBuffer

    count = max(1, round(buffer.samples.size * rate / buffer.sample_rate))
    positions = np.linspace(0, buffer.samples.size - 1, count)
    samples = np.interp(positions, np.arange(buffer.samples.size), buffer.samples.astype(np.float64))
    pcm = np.clip(np.rint(samples), -32768, 32767).astype(np.int16)
    rms = float(np.sqrt(np.mean((pcm.astype(np.float64) / 32768.0) ** 2)))
    return AudioBuffer(samples=pcm, sample_rate=rate, duration_seconds=pcm.size / rate, rms=rms)


def _resources(llama_pid: int | None) -> dict[str, Any]:
    return {
        "vram_used_mib": _gpu_memory_mib(),
        "process_ram_mib": _process_working_set_mib(os.getpid()),
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Latencia de Mark — perfil `{result['profile']}`",
        "",
        f"- Fecha: {result['created_at']}",
        f"- Modelo: {result['model']} (contexto {result['context_tokens']})",
        f"- TTS: {result.get('tts_provider')} / {result.get('tts_device')}",
        f"- Repeticiones en caliente por escenario: {result['repeat']}",
        f"- Arranque: {json.dumps(result['startup'], ensure_ascii=False)}",
        f"- VRAM antes / cargado: {result['resources_before'].get('vram_used_mib')} / "
        f"{result.get('resources_loaded', {}).get('vram_used_mib')} MiB",
        "",
        "| Escenario | Frío: 1er token | Frío: total | Caliente 1er token (med/p90) | "
        "Caliente total (med/p90) | 1er audio (med/p90) | 1er audio secuencial estimado (med) | "
        "tokens/s (med) | Errores |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, data in result["scenarios"].items():
        warm = data["warm"]

        def pair(key: str) -> str:
            item = warm.get(key)
            return "—" if not item else f"{item['median']} / {item['p90']}"

        speed = warm.get("tokens_per_second", {}).get("median", "—")
        sequential = warm.get("estimated_sequential_first_audio_seconds", {}).get("median", "—")
        lines.append(
            f"| {name} | {data['cold'].get('first_token_seconds')} | {data['cold'].get('total_seconds')} | "
            f"{pair('first_token_seconds')} | {pair('total_seconds')} | {pair('first_audio_seconds')} | "
            f"{sequential} | {speed} | {warm['errors']} |"
        )
    lines += [
        "",
        "Tiempos en segundos. El texto de las respuestas no se registra.",
        "El primer audio secuencial es una estimación (fin del LLM + síntesis media de una frase),",
        "no una medición del código anterior.",
    ]
    return "\n".join(lines) + "\n"


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings.load(args.config)
    updates: dict[str, Any] = {}
    if args.tts_provider:
        updates["tts_provider"] = args.tts_provider
    if args.tts_device:
        updates["tts_clone_device"] = args.tts_device
        # Pedir --tts-device cuda en el benchmark es la autorización explícita
        # para medir Chatterbox en la GPU.
        updates["tts_clone_allow_gpu"] = args.tts_device == "cuda"
    if updates:
        settings = settings.model_copy(update=updates)
    player = None
    if args.audio_output and args.profile == "voice":
        from .audio import SoundDevicePlayer

        player = SoundDevicePlayer(selector=settings.audio_output_device)
    result = await run_suite(
        settings,
        profile=args.profile,
        repeat=args.repeat,
        scenarios=args.scenarios,
        player=player,
    )
    output_dir = args.output_dir or settings.data_dir / "benchmarks" / "latency"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = output_dir / f"latency-{args.profile}-{stamp}"
    base.with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    base.with_suffix(".md").write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))
    print(f"Resultados: {base.with_suffix('.json')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
