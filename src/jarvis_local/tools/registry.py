from __future__ import annotations

import asyncio
import inspect
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..budgets import ActionBudget, BudgetExceeded
from ..cancellation import CancellationToken, OperationCancelled
from ..config import Settings
from ..models import (
    ActionRequest,
    ProjectRecord,
    ToolResult,
    ToolSpec,
    ToolStatus,
    VerificationResult,
)
from ..policy import PolicyViolation


@dataclass(frozen=True)
class ToolContext:
    settings: Settings
    project: ProjectRecord
    cancellation: CancellationToken
    budget: ActionBudget
    dry_run: bool = False

    @property
    def project_root(self) -> Path:
        return Path(self.project.root_path)


@dataclass(frozen=True)
class ToolExecutionOutcome:
    value: Any
    rollback_reference: str | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Herramienta duplicada: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def schemas(self, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
        if names is None:
            return [spec.tool_schema() for spec in self._tools.values()]
        selected = set(names)
        return [spec.tool_schema() for spec in self._tools.values() if spec.name in selected]

    def normalize_request(self, request: ActionRequest, spec: ToolSpec) -> ActionRequest:
        arguments = spec.argument_model.model_validate(request.arguments)
        return request.model_copy(update={"arguments": arguments.model_dump(mode="json", exclude_none=True)})

    async def execute(self, request: ActionRequest, context: ToolContext) -> ToolResult:
        spec = self.get(request.tool)
        if spec is None:
            return ToolResult(status=ToolStatus.DENIED, error=f"Herramienta desconocida: {request.tool}")

        try:
            normalized = self.normalize_request(request, spec)
            arguments: BaseModel = spec.argument_model.model_validate(normalized.arguments)
            context.cancellation.raise_if_cancelled()
            if context.dry_run:
                return ToolResult(
                    status=ToolStatus.SIMULATED,
                    value={
                        "tool": spec.name,
                        "arguments": normalized.arguments,
                        "expected_result": normalized.expected_result,
                    },
                    verification=VerificationResult(
                        attempted=False,
                        success=None,
                        details="La simulación no produjo efectos sobre el sistema.",
                    ),
                )

            async with asyncio.timeout(spec.timeout_seconds):
                if inspect.iscoroutinefunction(spec.handler):
                    raw_value = await spec.handler(context, arguments)
                else:
                    raw_value = await self._run_sync_handler(
                        spec.handler, context, arguments
                    )
            if isinstance(raw_value, ToolExecutionOutcome):
                value = raw_value.value
                rollback_reference = raw_value.rollback_reference
            else:
                value = raw_value
                rollback_reference = None
            context.cancellation.raise_if_cancelled()

            verification = VerificationResult(
                attempted=False,
                success=None,
                details="Herramienta de lectura; el resultado estructurado constituye la observación.",
            )
            if spec.verifier is not None:
                if inspect.iscoroutinefunction(spec.verifier):
                    verification = await spec.verifier(context, arguments, value)
                else:
                    verification = await asyncio.to_thread(spec.verifier, context, arguments, value)

            verification_failed = verification.attempted and verification.success is False
            return ToolResult(
                status=ToolStatus.ERROR if verification_failed else ToolStatus.SUCCESS,
                value=value,
                error=(
                    "La comprobación posterior no confirmó el resultado esperado."
                    if verification_failed
                    else None
                ),
                verification=verification,
                rollback_reference=rollback_reference,
            )
        except ValidationError as exc:
            return ToolResult(status=ToolStatus.DENIED, error=f"Argumentos inválidos: {exc}")
        except OperationCancelled as exc:
            return ToolResult(status=ToolStatus.CANCELLED, error=str(exc))
        except TimeoutError:
            return ToolResult(
                status=ToolStatus.TIMEOUT,
                error=f"La herramienta excedió su timeout de {spec.timeout_seconds:g} segundos.",
            )
        except BudgetExceeded as exc:
            return ToolResult(status=ToolStatus.DENIED, error=str(exc))
        except PolicyViolation as exc:
            return ToolResult(status=ToolStatus.DENIED, error=str(exc))
        except Exception as exc:
            return ToolResult(status=ToolStatus.ERROR, error=f"{type(exc).__name__}: {exc}")

    @staticmethod
    async def _run_sync_handler(handler, context: ToolContext, arguments: BaseModel):
        """No devuelve mientras un handler síncrono cancelado siga modificando estado."""

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, handler, context, arguments)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            context.cancellation.cancel(
                "La herramienta síncrona recibió cancelación o excedió su timeout."
            )
            # Los threads de Python no se pueden matar con seguridad. Los handlers
            # de escritura son cooperativos y deshacen parciales al observar el token.
            try:
                await asyncio.shield(future)
            except Exception:
                # La excepción cooperativa del thread no sustituye la causa que
                # canceló el await (por ejemplo, asyncio.timeout).
                pass
            raise

