from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .benchmark import _gpu_memory_mib, _process_working_set_mib
from .cancellation import CancellationToken
from .config import Settings
from .database import Database
from .policy import PolicyEngine
from .projects import ProjectService
from .rag import ProjectIndexer, RagRepository, RagService, create_embedding_provider


CASES = (
    {
        "question": "¿Qué se decidió para el almacenamiento vectorial?",
        "expected_source": "architecture.md",
        "expected_answer": "SQLite",
        "mode": "hybrid",
    },
    {
        "question": "¿Cuál es la fecha límite del prototipo lunar?",
        "expected_source": "planning.txt",
        "expected_answer": "18 de noviembre",
        "mode": "hybrid",
    },
    {
        "question": "¿Qué automóvil de demostración funciona sin servicios externos?",
        "expected_source": "vehicle.md",
        "expected_answer": "coche escarlata",
        "mode": "semantic",
    },
    {
        "question": "¿Dónde aparece el código documental ORION?",
        "expected_source": "untrusted.md",
        "expected_answer": "ORION",
        "mode": "hybrid",
        "expected_security_flag": "potential_prompt_injection",
    },
)


async def run_benchmark(settings: Settings, fixtures: Path) -> dict[str, Any]:
    if not fixtures.is_dir():
        raise FileNotFoundError(fixtures)
    with tempfile.TemporaryDirectory(prefix="jarvis-rag-benchmark-") as directory:
        scratch = Path(directory)
        benchmark_settings = settings.model_copy(
            update={
                "project_dir": fixtures.resolve(),
                "data_dir": scratch,
                "database_path": scratch / "benchmark.db",
                "allowed_roots": (fixtures.resolve(),),
            }
        )
        database = Database(benchmark_settings.database_path)
        policy = PolicyEngine(benchmark_settings)
        projects = ProjectService(database, policy)
        project = projects.create("RAG Benchmark", fixtures, make_active=True)
        gpu_before = _gpu_memory_mib()
        embeddings = await create_embedding_provider(benchmark_settings, allow_start=True)
        try:
            model_path = benchmark_settings.embedding_model_path
            if model_path is None:
                raise RuntimeError("El benchmark requiere un modelo de embeddings local.")
            manager = getattr(embeddings, "manager", None)
            gpu_loaded = _gpu_memory_mib()
            process_ram = _process_working_set_mib(
                None if manager is None or manager.process is None else manager.process.pid
            )
            repository = RagRepository(database)
            indexer = ProjectIndexer(
                settings=benchmark_settings,
                database=database,
                policy=policy,
                projects=projects,
                repository=repository,
                embeddings=embeddings,
            )
            service = RagService(
                settings=benchmark_settings,
                projects=projects,
                repository=repository,
                embeddings=embeddings,
            )
            index_started = time.monotonic()
            index_stats = await indexer.index_project(project, CancellationToken())
            index_seconds = time.monotonic() - index_started
            case_results = []
            for case in CASES:
                started = time.monotonic()
                result = await service.search(
                    project=project,
                    query=case["question"],
                    mode=case["mode"],
                    top_k=3,
                    cancellation=CancellationToken(),
                )
                latency = time.monotonic() - started
                top = result.evidence[0] if result.evidence else None
                source_ok = bool(top and top.relative_path == case["expected_source"])
                answer_ok = bool(
                    top and case["expected_answer"].casefold() in top.content.casefold()
                )
                expected_flag = case.get("expected_security_flag")
                security_ok = bool(
                    expected_flag is None
                    or (top and expected_flag in top.security_flags)
                )
                case_results.append(
                    {
                        **case,
                        "top_source": None if top is None else top.relative_path,
                        "citation": None if top is None else top.citation,
                        "score": None if top is None else top.score,
                        "source_ok": source_ok,
                        "answer_ok": answer_ok,
                        "security_ok": security_ok,
                        "passed": source_ok and answer_ok and security_ok,
                        "latency_seconds": latency,
                    }
                )
            latencies = [item["latency_seconds"] for item in case_results]
            return {
                "benchmark_version": 1,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "embedding": {
                    "provider": embeddings.name,
                    "model": embeddings.model,
                    "file": benchmark_settings.embedding_model_path.name,
                    "file_bytes": model_path.stat().st_size,
                    "sha256": _sha256(model_path),
                    "dimensions": benchmark_settings.embedding_dimensions,
                    "context_tokens": benchmark_settings.embedding_context_tokens,
                    "gpu_layers": benchmark_settings.embedding_gpu_layers,
                },
                "index": index_stats.model_dump(mode="json")
                | {
                    "measured_seconds": index_seconds,
                    "database_bytes": benchmark_settings.database_path.stat().st_size,
                },
                "resources": {
                    "gpu_before_mib": gpu_before,
                    "gpu_loaded_mib": gpu_loaded,
                    "gpu_delta_mib": (
                        None
                        if gpu_before is None or gpu_loaded is None
                        else gpu_loaded - gpu_before
                    ),
                    "embedding_process_working_set_mib": process_ram,
                },
                "retrieval": {
                    "passed": sum(item["passed"] for item in case_results),
                    "total": len(case_results),
                    "median_latency_seconds": statistics.median(latencies),
                    "cases": case_results,
                },
                "audit_chain_valid": database.verify_audit_chain()[0],
            }
        finally:
            await embeddings.aclose()


def render_markdown(result: dict[str, Any]) -> str:
    embedding = result["embedding"]
    index = result["index"]
    resources = result["resources"]
    retrieval = result["retrieval"]
    lines = [
        "# Benchmark RAG local",
        "",
        f"Fecha UTC: {result['timestamp_utc']}",
        "",
        "## Configuración",
        "",
        f"- Embeddings: `{embedding['model']}` / `{embedding['file']}`",
        f"- Tamaño/SHA-256: {embedding['file_bytes']} bytes / `{embedding['sha256']}`",
        f"- Dimensiones: {embedding['dimensions']}",
        f"- Contexto: {embedding['context_tokens']} tokens",
        f"- GPU layers: {embedding['gpu_layers']}",
        f"- Documentos/fragmentos: {index['scanned']} / {index['chunks']}",
        "",
        "## Rendimiento",
        "",
        f"- Indexación: {index['measured_seconds']:.3f} s",
        f"- Latencia mediana por consulta: {retrieval['median_latency_seconds']:.3f} s",
        f"- RAM proceso embeddings: {resources['embedding_process_working_set_mib']} MiB",
        f"- VRAM antes/cargado/delta: {resources['gpu_before_mib']} / "
        f"{resources['gpu_loaded_mib']} / {resources['gpu_delta_mib']} MiB",
        f"- Base SQLite: {index['database_bytes']} bytes",
        "",
        "## Evaluación",
        "",
        f"Resultado: **{retrieval['passed']}/{retrieval['total']}**.",
        "",
    ]
    for case in retrieval["cases"]:
        lines.append(
            f"- {'PASS' if case['passed'] else 'FAIL'} — {case['question']} → "
            f"`{case['citation']}` ({case['latency_seconds']:.3f} s)"
        )
    lines.extend(
        (
            "",
            f"Cadena de auditoría válida: {result['audit_chain_valid']}.",
            "",
            "Este conjunto es deliberadamente pequeño; valida integración y regresiones, "
            "no calidad universal de recuperación.",
        )
    )
    return "\n".join(lines)


async def async_main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Benchmark reproducible de RAG local")
    parser.add_argument("--config", type=Path, default=root / "config" / "jarvis.toml")
    parser.add_argument("--fixtures", type=Path, default=root / "benchmarks" / "fixtures" / "rag")
    parser.add_argument("--output-dir", type=Path, default=root / "benchmarks" / "results")
    args = parser.parse_args()
    result = await run_benchmark(Settings.load(args.config), args.fixtures.resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "rag-qwen3-embedding-0.6b-q8_0.json"
    markdown_path = args.output_dir / "rag-qwen3-embedding-0.6b-q8_0.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))
    return 0 if result["retrieval"]["passed"] == result["retrieval"]["total"] else 1


def main() -> int:
    return asyncio.run(async_main())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
