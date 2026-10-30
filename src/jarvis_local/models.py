from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskLevel(IntEnum):
    OBSERVE = 0
    REVERSIBLE = 1
    SENSITIVE = 2
    PRIVILEGED = 3


class Reversibility(str, Enum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    PARTIAL = "partial"
    IRREVERSIBLE = "irreversible"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    SIMULATED = "simulated"


class ConfirmationSource(str, Enum):
    TRUSTED_LOCAL_UI = "trusted_local_ui"


class ProjectStatus(str, Enum):
    ENABLED = "enabled"
    ARCHIVED = "archived"


class ActionRequest(StrictModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    tool: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_result: str = Field(min_length=1, max_length=1000)
    intent: str | None = Field(default=None, max_length=2000)
    session_id: str | None = None
    project_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class PolicyDecision(StrictModel):
    allowed: bool
    requires_confirmation: bool
    calculated_risk: RiskLevel
    reasons: tuple[str, ...]
    normalized_arguments: dict[str, Any] = Field(default_factory=dict)
    policy_version: str = "1"


class ConfirmationReceipt(StrictModel):
    approved: bool
    source: ConfirmationSource
    request_id: str
    summary: str
    confirmed_at: datetime = Field(default_factory=utc_now)


class VerificationResult(StrictModel):
    attempted: bool
    success: bool | None = None
    details: str = ""


class ToolResult(StrictModel):
    status: ToolStatus
    value: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    verification: VerificationResult | None = None
    rollback_reference: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {ToolStatus.SUCCESS, ToolStatus.SIMULATED}

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json") | {"ok": self.ok}


class ProjectRecord(StrictModel):
    id: str
    name: str
    root_path: str
    status: ProjectStatus = ProjectStatus.ENABLED
    config: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, bool] = Field(default_factory=dict)
    is_active: bool
    created_at: str
    updated_at: str


class EmptyArguments(StrictModel):
    pass


ToolHandler = Callable[..., Any]
ToolVerifier = Callable[..., VerificationResult]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    argument_model: type[BaseModel]
    risk: RiskLevel
    handler: ToolHandler
    timeout_seconds: float
    reversibility: Reversibility = Reversibility.READ_ONLY
    path_arguments: tuple[str, ...] = ()
    application_argument: str | None = None
    domain_argument: str | None = None
    modifies_files: bool = False
    external_effect: bool = False
    requires_elevation: bool = False
    required_project_permissions: tuple[str, ...] = ()
    verifier: ToolVerifier | None = None

    def tool_schema(self) -> dict[str, Any]:
        parameters = self.argument_model.model_json_schema()
        parameters.pop("title", None)
        parameters.setdefault("type", "object")
        properties = parameters.setdefault("properties", {})
        properties["expected_result"] = {
            "type": "string",
            "minLength": 1,
            "maxLength": 1000,
            "description": "Resultado observable esperado tras ejecutar la herramienta.",
        }
        required = list(parameters.get("required", []))
        if "expected_result" not in required:
            required.append("expected_result")
        parameters["required"] = required
        parameters["additionalProperties"] = False
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }

    def ollama_schema(self) -> dict[str, Any]:
        """Alias temporal para integraciones externas de la Fase 0."""

        return self.tool_schema()

