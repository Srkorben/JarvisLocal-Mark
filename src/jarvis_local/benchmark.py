from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import statistics
import subprocess
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cancellation import CancellationToken, OperationCancelled
from .config import Settings
from .model_providers.llama_cpp import LlamaCppProvider
from .model_providers.llama_server import LlamaServerManager
from .tools import build_default_registry
from .policy import PolicyEngine


SPANISH_CASES = (
    "Explica en español, en tres frases claras, por qué una copia de seguridad no sustituye al control de versiones.",
    "Un estudiante tiene 90 minutos para estudiar dos temas. Propón un plan breve y justifica la distribución del tiempo.",
    "Resume esta idea sin añadir datos: JarvisLocal debe priorizar seguridad, trazabilidad y control del usuario sobre autonomía.",
)

TOOL_CASES = (
    ("¿Qué hora local es? Usa la herramienta adecuada.", "get_current_time"),
    ("Lista el contenido de la carpeta del proyecto activo.", "list_directory"),
    ("Busca archivos cuyo nombre contenga README dentro del proyecto.", "search_files"),
)


async def run_benchmark(settings: Settings) -> dict[str, Any]:
    if settings.model_provider != "llama_cpp":
        raise ValueError("El benchmark reproducible de Fase 1 requiere model_provider=llama_cpp.")
    if settings.llama_model_path is None:
        raise ValueError("No hay llama_cpp.model_path configurado.")

    manager = LlamaServerManager(settings)
    gpu_before = _gpu_memory_mib()
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    started_process = await manager.ensure_running()
    load_seconds = loop.time() - started_at
    provider = LlamaCppProvider(settings, manager)
    try:
        health = await provider.health()
        if not health.ready:
            raise RuntimeError(health.detail)
        gpu_loaded = _gpu_memory_mib()
        process_ram_mib = _process_working_set_mib(
            manager.process.pid if manager.process is not None else None
        )
        spanish_results = []
        for prompt in SPANISH_CASES:
            response = await provider.complete_chat(
                [
                    {"role": "system", "content": "Responde en español claro y sigue exactamente la instrucción."},
                    {"role": "user", "content": prompt},
                ],
                [],
                CancellationToken(),
            )
            spanish_results.append(
                {
                    "prompt": prompt,
                    "response": response.content,
                    "first_token_seconds": response.metrics.first_token_seconds,
                    "total_seconds": response.metrics.total_seconds,
                    "completion_tokens": response.usage.completion_tokens,
                    "tokens_per_second": _effective_tokens_per_second(response),
                }
            )

        registry = build_default_registry(settings, PolicyEngine(settings))
        schemas = registry.schemas()
        tool_results = []
        for prompt, expected_tool in TOOL_CASES:
            response = await provider.complete_chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Selecciona una herramienta cuando la petición lo requiera. "
                            "Incluye siempre expected_result y no inventes resultados."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                schemas,
                CancellationToken(),
            )
            selected = response.tool_calls[0] if response.tool_calls else None
            passed = bool(
                selected
                and selected.name == expected_tool
                and isinstance(selected.arguments.get("expected_result"), str)
                and selected.arguments["expected_result"].strip()
            )
            tool_results.append(
                {
                    "prompt": prompt,
                    "expected_tool": expected_tool,
                    "selected_tool": None if selected is None else selected.name,
                    "arguments": None if selected is None else selected.arguments,
                    "passed": passed,
                    "first_token_seconds": response.metrics.first_token_seconds,
                    "total_seconds": response.metrics.total_seconds,
                }
            )

        cancellation_token = CancellationToken()
        cancellation_task = asyncio.create_task(
            provider.complete_chat(
                [
                    {
                        "role": "system",
                        "content": "Responde en español y desarrolla extensamente la petición.",
                    },
                    {
                        "role": "user",
                        "content": "Explica en al menos 500 palabras cómo diseñar pruebas de software.",
                    },
                ],
                [],
                cancellation_token,
            )
        )
        await asyncio.sleep(0.25)
        cancel_started = loop.time()
        cancellation_token.cancel("benchmark de cancelación")
        cancelled = False
        try:
            await asyncio.wait_for(cancellation_task, timeout=3)
        except OperationCancelled:
            cancelled = True
        cancellation_latency = loop.time() - cancel_started
        health_after_cancel = await provider.health()

        ttft_values = [
            item["first_token_seconds"]
            for item in spanish_results
            if item["first_token_seconds"] is not None
        ]
        speed_values = [
            item["tokens_per_second"]
            for item in spanish_results
            if item["tokens_per_second"] is not None
        ]
        model_path = settings.llama_model_path
        return {
            "benchmark_version": 2,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": provider.name,
            "llama_cpp_build": "b11459 / f498f864f",
            "model": {
                "alias": settings.model,
                "file": model_path.name,
                "format": "GGUF",
                "quantization": "Q4_K_M",
                "bytes": model_path.stat().st_size,
                "sha256": _sha256(model_path),
                "context_tokens": settings.context_tokens,
                "max_output_tokens": settings.max_output_tokens,
                "gpu_layers_requested": settings.llama_gpu_layers,
                "fit_target_mib": settings.llama_fit_target_mib,
            },
            "runtime": {
                "server_started_by_benchmark": started_process,
                "load_seconds": load_seconds,
                "gpu_memory_before_mib": gpu_before,
                "gpu_memory_loaded_mib": gpu_loaded,
                "gpu_memory_delta_mib": (
                    None if gpu_before is None or gpu_loaded is None else gpu_loaded - gpu_before
                ),
                "process_ram_working_set_mib": process_ram_mib,
            },
            "conversation_spanish": {
                "cases": spanish_results,
                "median_first_token_seconds": _median(ttft_values),
                "median_tokens_per_second": _median(speed_values),
            },
            "tool_calling": {
                "passed": sum(1 for item in tool_results if item["passed"]),
                "total": len(tool_results),
                "cases": tool_results,
            },
            "cancellation": {
                "passed": cancelled and health_after_cancel.ready,
                "generation_cancelled": cancelled,
                "latency_seconds": cancellation_latency,
                "server_ready_after_cancel": health_after_cancel.ready,
            },
        }
    finally:
        await provider.aclose()


def _effective_tokens_per_second(response) -> float | None:
    timings = response.metrics.provider_metrics
    predicted = timings.get("predicted_per_second")
    if isinstance(predicted, (int, float)):
        return float(predicted)
    return response.metrics.tokens_per_second


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _gpu_memory_mib() -> int | None:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return int(result.stdout.strip().splitlines()[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _process_working_set_mib(pid: int | None) -> float | None:
    if pid is None or not hasattr(ctypes, "windll"):
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    handle = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x0400, False, pid)
    if not handle:
        return None
    try:
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        return round(counters.WorkingSetSize / (1024 * 1024), 2) if ok else None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def render_markdown(result: dict[str, Any]) -> str:
    model = result["model"]
    runtime = result["runtime"]
    conversation = result["conversation_spanish"]
    tools = result["tool_calling"]
    cancellation = result["cancellation"]
    lines = [
        "# Benchmark de Fase 1",
        "",
        f"Fecha UTC: {result['timestamp_utc']}",
        "",
        "## Configuración",
        "",
        f"- Modelo: `{model['file']}`",
        f"- Formato/cuantización: {model['format']} / {model['quantization']}",
        f"- Tamaño: {model['bytes']} bytes",
        f"- SHA-256: `{model['sha256']}`",
        f"- Contexto: {model['context_tokens']} tokens",
        f"- Máximo de salida: {model['max_output_tokens']} tokens",
        f"- Offload solicitado: {model['gpu_layers_requested']} "
        f"(reserva objetivo: {model['fit_target_mib']} MiB)",
        f"- llama.cpp: {result['llama_cpp_build']}",
        "",
        "## Rendimiento observado",
        "",
        f"- Carga hasta health-ready: {runtime['load_seconds']:.3f} s",
        f"- VRAM aproximada antes/cargado/delta: {runtime['gpu_memory_before_mib']} / "
        f"{runtime['gpu_memory_loaded_mib']} / {runtime['gpu_memory_delta_mib']} MiB",
        f"- RAM del proceso (working set): {runtime['process_ram_working_set_mib']} MiB",
        f"- TTFT mediano: {conversation['median_first_token_seconds']:.3f} s",
        f"- Velocidad mediana: {conversation['median_tokens_per_second']:.2f} tokens/s",
        "",
        "## Tool calling",
        "",
        f"Resultado: **{tools['passed']}/{tools['total']}** casos.",
        "",
    ]
    for case in tools["cases"]:
        lines.append(
            f"- `{case['expected_tool']}` → `{case['selected_tool']}`: "
            f"{'PASS' if case['passed'] else 'FAIL'}"
        )
    lines.extend(
        (
            "",
            "## Cancelación real",
            "",
            f"Resultado: **{'PASS' if cancellation['passed'] else 'FAIL'}**; "
            f"latencia {cancellation['latency_seconds']:.3f} s; servidor listo después: "
            f"{cancellation['server_ready_after_cancel']}.",
            "",
            "## Conversación en español",
            "",
        )
    )
    for index, case in enumerate(conversation["cases"], 1):
        lines.extend(
            (
                f"### Caso {index}",
                "",
                f"**Prompt:** {case['prompt']}",
                "",
                f"**Respuesta:** {case['response']}",
                "",
            )
        )
    return "\n".join(lines)


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark reproducible de JarvisLocal")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "config" / "jarvis.toml",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "benchmarks" / "results",
    )
    args = parser.parse_args()
    settings = Settings.load(args.config)
    result = await run_benchmark(settings)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{settings.model}-ctx{settings.context_tokens}"
    json_path = args.output_dir / f"{stem}.json"
    markdown_path = args.output_dir / f"{stem}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
