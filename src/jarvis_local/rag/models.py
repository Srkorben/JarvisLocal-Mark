from __future__ import annotations

from typing import Any

from pydantic import Field

from ..models import StrictModel


class ExtractedSection(StrictModel):
    title: str | None = None
    page_number: int | None = None
    text: str


class ChunkDraft(StrictModel):
    index: int
    section_title: str | None = None
    page_number: int | None = None
    content: str
    suspicious_instructions: bool = False


class IndexStats(StrictModel):
    project_id: str
    scanned: int = 0
    indexed: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    chunks: int = 0
    errors: tuple[dict[str, str], ...] = ()
    elapsed_seconds: float = 0.0


class EvidenceReference(StrictModel):
    chunk_id: int
    path: str
    relative_path: str
    section: str | None = None
    page: int | None = None
    content: str
    score: float
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    source_hash: str
    modified_ns: int
    trust: str = "untrusted_document_content"
    security_flags: tuple[str, ...] = ()

    @property
    def citation(self) -> str:
        anchor = f"p.{self.page}" if self.page is not None else self.section
        return self.relative_path if not anchor else f"{self.relative_path}#{anchor}"


class RetrievalResult(StrictModel):
    project_id: str
    query: str
    mode: str
    evidence: tuple[EvidenceReference, ...] = ()
    sufficient_evidence: bool = False
    insufficiency_reason: str | None = None
    elapsed_seconds: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)

