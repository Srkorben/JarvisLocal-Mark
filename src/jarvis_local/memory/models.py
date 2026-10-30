from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field

from ..models import StrictModel


class EpisodicKind(str, Enum):
    ACTION = "action"
    RESULT = "result"
    DECISION = "decision"
    SESSION_SUMMARY = "session_summary"
    PENDING_TASK = "pending_task"


class EpisodicEvent(StrictModel):
    id: str
    project_id: str
    session_id: str | None = None
    kind: EpisodicKind
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)
    source: str
    confirmed: bool
    occurred_at: str
    created_at: str


class ProfileEntry(StrictModel):
    key: str
    value: Any
    source: str
    created_at: str
    updated_at: str


class DecisionSource(StrictModel):
    """Procedencia declarada de una decisión confirmada.

    El contenido documental nunca confirma por sí mismo una decisión: ``kind``
    describe la evidencia, no la autoridad que autorizó persistirla.
    """

    kind: Literal["explicit_user", "document", "tool_result"]
    reference: str = Field(min_length=1, max_length=2048)
    citation: str | None = Field(default=None, max_length=2048)
    source_hash: str | None = Field(default=None, max_length=256)


class TemporalDecision(StrictModel):
    id: str
    project_id: str
    topic: str
    statement: str
    rationale: str
    source: DecisionSource
    supersedes_id: str | None = None
    valid_from: str
    valid_to: str | None = None
    status: Literal["current", "superseded"]
    created_at: str


class DecisionState(StrictModel):
    project_id: str
    topic: str
    current: TemporalDecision | None = None
    previous: TemporalDecision | None = None
    history: tuple[TemporalDecision, ...] = ()

