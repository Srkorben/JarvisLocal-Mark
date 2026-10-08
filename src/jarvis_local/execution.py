from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable

from pydantic import ValidationError

from .budgets import ActionBudget, BudgetExceeded
from .cancellation import CancellationToken, OperationCancelled
from .config import Settings
from .database import Database
from .models import (
    ActionRequest,
    ConfirmationReceipt,
    ConfirmationSource,
    PolicyDecision,
    ToolResult,
    ToolStatus,
)
from .policy import PolicyEngine, PolicyViolation
from .projects import ProjectService
from .tools.registry import ToolContext, ToolRegistry

if TYPE_CHECKING:
    from .memory import MemoryRepository


ConfirmationCallback = Callable[
    [ActionRequest, PolicyDecision], ConfirmationReceipt | Awaitable[ConfirmationReceipt]
]


class ActionExecutor:
    """Única puerta del núcleo Python para ejecutar herramientas registradas."""

    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        registry: ToolRegistry,
        policy: PolicyEngine,
        projects: ProjectService,
        memory: "MemoryRepository | None" = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.registry = registry
        self.policy = policy
        self.projects = projects
        self.memory = memory

    async def execute(
        self,
        request: ActionRequest,
        *,
        cancellation: CancellationToken,
        budget: ActionBudget,
        confirmation_callback: ConfirmationCallback | None = None,
        dry_run: bool = False,
    ) -> ToolResult:
        spec = self.registry.get(request.tool)
        if spec is None:
            result = ToolResult(status=ToolStatus.DENIED, error="Herramienta no registrada.")
            self._audit(request, None, result, detail={"reason": "unknown_tool"})
            return result

        try:
            project = self.projects.validate_action_project(request.project_id)
            for permission in spec.required_project_permissions:
                self.projects.require_permission(project, permission)
            normalized_request = self.registry.normalize_request(request, spec)
            decision = self.policy.evaluate(
                normalized_request,
                spec,
                project_root=Path(project.root_path),
            )
        except (ValidationError, ValueError, KeyError, PermissionError, PolicyViolation) as exc:
            result = ToolResult(status=ToolStatus.DENIED, error=str(exc))
            self._audit(request, None, result, detail={"reason": type(exc).__name__})
            return result

        normalized_request = normalized_request.model_copy(
            update={"arguments": decision.normalized_arguments}
        )
        if not decision.allowed:
            result = ToolResult(status=ToolStatus.DENIED, error=" ".join(decision.reasons))
            self._audit(normalized_request, decision, result)
            return result

        confirmation: ConfirmationReceipt | None = None
        if decision.requires_confirmation:
            if confirmation_callback is None:
                result = ToolResult(
                    status=ToolStatus.DENIED,
                    error="La acción requiere confirmación desde una interfaz local confiable.",
                )
                self._audit(normalized_request, decision, result)
                return result
            confirmation_result = confirmation_callback(normalized_request, decision)
            confirmation = (
                await confirmation_result
                if inspect.isawaitable(confirmation_result)
                else confirmation_result
            )
            if confirmation.source != ConfirmationSource.TRUSTED_LOCAL_UI:
                result = ToolResult(status=ToolStatus.DENIED, error="Fuente de confirmación no confiable.")
                self._audit(normalized_request, decision, result, confirmation=confirmation)
                return result
            if confirmation.request_id != normalized_request.request_id or not confirmation.approved:
                result = ToolResult(status=ToolStatus.DENIED, error="La acción no fue confirmada.")
                self._audit(normalized_request, decision, result, confirmation=confirmation)
                return result

        try:
            cancellation.raise_if_cancelled()
            budget.consume_step()
            if spec.modifies_files and not dry_run:
                budget.record_modified_files(1)
            context = ToolContext(
                settings=self.settings,
                project=project,
                cancellation=cancellation,
                budget=budget,
                dry_run=dry_run,
            )
            result = await self.registry.execute(normalized_request, context)
        except (OperationCancelled, BudgetExceeded) as exc:
            result = ToolResult(
                status=ToolStatus.CANCELLED if isinstance(exc, OperationCancelled) else ToolStatus.DENIED,
                error=str(exc),
            )

        self._audit(
            normalized_request,
            decision,
            result,
            confirmation=confirmation,
            detail={"budget": budget.snapshot(), "dry_run": dry_run},
        )
        if self.memory is not None and normalized_request.project_id and not dry_run:
            from .memory import EpisodicKind

            try:
                self.memory.add_episode(
                    project_id=normalized_request.project_id,
                    session_id=normalized_request.session_id,
                    kind=EpisodicKind.ACTION,
                    summary=(
                        f"JarvisLocal ejecutó {normalized_request.tool}: "
                        f"{result.status.value}."
                    ),
                    detail={
                        "tool": normalized_request.tool,
                        "outcome": result.status.value,
                        "expected_result": normalized_request.expected_result,
                        "verification": (
                            None
                            if result.verification is None
                            else result.verification.model_dump(mode="json")
                        ),
                    },
                    source="jarvis_tool_executor",
                )
            except Exception as exc:
                # La memoria es secundaria: nunca convierte una acción ya
                # ejecutada en fallo ni oculta su resultado principal.
                self.database.record_audit(
                    session_id=normalized_request.session_id,
                    project_id=normalized_request.project_id,
                    event_type="episodic_memory_error",
                    outcome="error",
                    detail={"error": f"{type(exc).__name__}: {exc}"},
                )
        return result

    def _audit(
        self,
        request: ActionRequest,
        decision: PolicyDecision | None,
        result: ToolResult,
        *,
        confirmation: ConfirmationReceipt | None = None,
        detail: dict | None = None,
    ) -> None:
        result_detail = {
            "status": result.status.value,
            "error": result.error,
            "metadata": result.metadata,
            **(detail or {}),
        }
        if self.settings.store_tool_output:
            result_detail["value"] = result.value
        self.database.record_audit(
            session_id=request.session_id,
            project_id=request.project_id,
            event_type="tool_execution",
            intent=request.intent,
            tool_name=request.tool,
            risk_level=None if decision is None else int(decision.calculated_risk),
            outcome=result.status.value,
            request=request,
            plan={"expected_result": request.expected_result},
            policy={} if decision is None else decision,
            confirmation={} if confirmation is None else confirmation,
            detail=result_detail,
            verification={} if result.verification is None else result.verification,
            rollback={"reference": result.rollback_reference} if result.rollback_reference else {},
            cancelled=result.status == ToolStatus.CANCELLED,
        )

