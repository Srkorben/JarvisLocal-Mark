from __future__ import annotations

import time
from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class BudgetLimits:
    max_steps: int
    max_runtime_seconds: float
    max_modified_files: int
    max_outbound_bytes: int


class ActionBudget:
    def __init__(self, limits: BudgetLimits):
        self.limits = limits
        self.started_at = time.monotonic()
        self.steps = 0
        self.modified_files = 0
        self.outbound_bytes = 0

    def check_runtime(self) -> None:
        if time.monotonic() - self.started_at > self.limits.max_runtime_seconds:
            raise BudgetExceeded("Se agotó el presupuesto temporal del turno.")

    def consume_step(self) -> None:
        self.check_runtime()
        if self.steps >= self.limits.max_steps:
            raise BudgetExceeded("Se agotó el número máximo de acciones del turno.")
        self.steps += 1

    def record_modified_files(self, count: int = 1) -> None:
        if count < 0:
            raise ValueError("count no puede ser negativo")
        if self.modified_files + count > self.limits.max_modified_files:
            raise BudgetExceeded("La acción excede el máximo de archivos modificables por turno.")
        self.modified_files += count

    def record_outbound_bytes(self, count: int) -> None:
        if count < 0:
            raise ValueError("count no puede ser negativo")
        if self.outbound_bytes + count > self.limits.max_outbound_bytes:
            raise BudgetExceeded("La acción excede el máximo de datos salientes por turno.")
        self.outbound_bytes += count

    def snapshot(self) -> dict[str, int | float]:
        return {
            "steps": self.steps,
            "modified_files": self.modified_files,
            "outbound_bytes": self.outbound_bytes,
            "elapsed_seconds": round(time.monotonic() - self.started_at, 3),
        }

