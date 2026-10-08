from __future__ import annotations

import time
from pathlib import Path

from ..cancellation import CancellationToken
from ..config import Settings
from ..models import ProjectRecord
from ..projects import ProjectService
from .embeddings import EmbeddingProvider
from .models import EvidenceReference, RetrievalResult
from .repository import RagRepository, cosine_similarity, unpack_vector


class RagService:
    def __init__(
        self,
        *,
        settings: Settings,
        projects: ProjectService,
        repository: RagRepository,
        embeddings: EmbeddingProvider,
    ):
        self.settings = settings
        self.projects = projects
        self.repository = repository
        self.embeddings = embeddings

    async def search(
        self,
        *,
        project: ProjectRecord,
        query: str,
        cancellation: CancellationToken,
        mode: str = "hybrid",
        top_k: int | None = None,
        modified_after_ns: int | None = None,
        modified_before_ns: int | None = None,
    ) -> RetrievalResult:
        started = time.monotonic()
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("La consulta RAG no puede estar vacía.")
        if mode not in {"hybrid", "lexical", "semantic"}:
            raise ValueError("Modo de recuperación no soportado.")
        limit = top_k or self.settings.rag_default_top_k
        if not 1 <= limit <= 25:
            raise ValueError("top_k debe estar entre 1 y 25.")
        validated = self.projects.validate_action_project(project.id)
        self.projects.require_permission(validated, "read")
        self.projects.require_permission(validated, "memory")

        lexical_rows = []
        if mode in {"hybrid", "lexical"}:
            lexical_rows = self.repository.keyword_search(
                project_id=project.id,
                query=normalized_query,
                limit=max(limit * 4, 20),
                modified_after_ns=modified_after_ns,
                modified_before_ns=modified_before_ns,
            )
        semantic_rows: list[tuple[dict, float]] = []
        if mode in {"hybrid", "semantic"}:
            query_vector = await self.embeddings.embed_query(
                normalized_query, cancellation
            )
            rows = self.repository.vector_candidates(
                project_id=project.id,
                embedding_model=self.embeddings.model,
                scan_limit=self.settings.rag_vector_scan_limit,
                modified_after_ns=modified_after_ns,
                modified_before_ns=modified_before_ns,
            )
            for row in rows:
                cancellation.raise_if_cancelled()
                vector = unpack_vector(row["embedding"], row["embedding_dimensions"])
                semantic_rows.append((row, cosine_similarity(query_vector, vector)))
            semantic_rows.sort(key=lambda item: item[1], reverse=True)

        fused: dict[int, dict] = {}
        for rank, row in enumerate(lexical_rows, 1):
            item = fused.setdefault(int(row["chunk_id"]), {"row": row, "score": 0.0})
            item["score"] += 1.0 / (60 + rank)
            item["lexical_rank"] = rank
        for rank, (row, similarity) in enumerate(semantic_rows[: max(limit * 4, 20)], 1):
            item = fused.setdefault(int(row["chunk_id"]), {"row": row, "score": 0.0})
            item["score"] += 1.0 / (60 + rank)
            item["semantic_rank"] = rank
            item["semantic_similarity"] = similarity

        if mode == "lexical":
            ordered = sorted(fused.values(), key=lambda item: item.get("lexical_rank", 10**9))
        elif mode == "semantic":
            ordered = sorted(
                fused.values(), key=lambda item: item.get("semantic_similarity", -1.0), reverse=True
            )
        else:
            ordered = sorted(fused.values(), key=lambda item: item["score"], reverse=True)

        evidence: list[EvidenceReference] = []
        for item in ordered[:limit]:
            row = item["row"]
            flags = (
                ("potential_prompt_injection",)
                if bool(row["suspicious_instructions"])
                else ()
            )
            evidence.append(
                EvidenceReference(
                    chunk_id=int(row["chunk_id"]),
                    path=str(Path(row["path"])),
                    relative_path=row["relative_path"],
                    section=row["section_title"],
                    page=row["page_number"],
                    content=row["content"],
                    score=float(item.get("semantic_similarity", item["score"])),
                    lexical_rank=item.get("lexical_rank"),
                    semantic_rank=item.get("semantic_rank"),
                    source_hash=row["source_hash"],
                    modified_ns=int(row["modified_ns"]),
                    security_flags=flags,
                )
            )

        best_semantic = max(
            (item.get("semantic_similarity", -1.0) for item in fused.values()),
            default=-1.0,
        )
        sufficient = bool(lexical_rows) or best_semantic >= 0.35
        return RetrievalResult(
            project_id=project.id,
            query=normalized_query,
            mode=mode,
            evidence=tuple(evidence),
            sufficient_evidence=sufficient and bool(evidence),
            insufficiency_reason=(
                None
                if sufficient and evidence
                else "No se encontró evidencia suficientemente relacionada en el proyecto activo."
            ),
            elapsed_seconds=time.monotonic() - started,
            metadata={
                "lexical_candidates": len(lexical_rows),
                "semantic_candidates": len(semantic_rows),
                "embedding_model": self.embeddings.model,
                "project_root": validated.root_path,
            },
        )

