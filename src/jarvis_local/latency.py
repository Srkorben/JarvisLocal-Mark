"""Trazas de latencia por turno, sin contenido conversacional.

Cada turno registra marcas monotónicas por etapa (contexto, primer token,
respuesta completa, primer audio...) y métricas por ronda del LLM. Solo se
guardan tiempos, recuentos y tamaños: nunca texto, audio ni credenciales.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Claves numéricas de ``timings`` de llama-server que se conservan.
_PROVIDER_TIMING_KEYS = (
    "prompt_n",
    "prompt_ms",
    "prompt_per_second",
    "predicted_n",
    "predicted_ms",
    "predicted_per_second",
    "cache_n",
)
MAX_LOG_BYTES = 5 * 1024 * 1024


class TurnTrace:
    def __init__(self, *, interface: str, turn_id: str | None = None) -> None:
        self.turn_id = turn_id or str(uuid.uuid4())
        self.interface = interface
        self.started = time.monotonic()
        self.created_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        self.stages: dict[str, float] = {}
        self.rounds: list[dict[str, Any]] = []
        self.values: dict[str, Any] = {}

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def mark(self, stage: str) -> None:
        """Registra la primera vez que el turno alcanza una etapa."""

        self.stages.setdefault(stage, round(self.elapsed(), 4))

    def set(self, **values: Any) -> None:
        self.values.update(values)

    def add_round(
        self,
        *,
        number: int,
        first_token_seconds: float | None,
        total_seconds: float,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        tokens_per_second: float | None,
        provider_metrics: dict[str, Any],
        tool_calls: int,
    ) -> dict[str, Any]:
        timings = provider_metrics if isinstance(provider_metrics, dict) else {}
        record: dict[str, Any] = {
            "round": number,
            "first_token_seconds": _rounded(first_token_seconds),
            "total_seconds": _rounded(total_seconds),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "tokens_per_second": _rounded(tokens_per_second),
            "tool_calls": tool_calls,
            "tools": [],
        }
        for key in _PROVIDER_TIMING_KEYS:
            value = timings.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                record[f"server_{key}"] = round(float(value), 3)
        self.rounds.append(record)
        return record

    def add_tool(self, round_record: dict[str, Any], *, name: str, status: str, seconds: float) -> None:
        round_record["tools"].append(
            {"name": name, "status": status, "seconds": round(seconds, 4)}
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "type": "turn_latency",
            "turn_id": self.turn_id,
            "interface": self.interface,
            "created_at": self.created_at,
            "total_seconds": round(self.elapsed(), 4),
            "stages": dict(self.stages),
            "rounds": list(self.rounds),
            **self.values,
        }


class LatencyLog:
    """Escritor JSONL acotado. Un fallo de registro nunca interrumpe el turno."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, trace: TurnTrace) -> None:
        if self.path is None:
            return
        line = json.dumps(trace.as_record(), ensure_ascii=False, separators=(",", ":"))
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > MAX_LOG_BYTES:
                    self.path.replace(self.path.with_suffix(self.path.suffix + ".1"))
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError:
            return


def default_latency_log(data_dir: Path) -> LatencyLog:
    return LatencyLog(data_dir / "logs" / "latency.jsonl")


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)
