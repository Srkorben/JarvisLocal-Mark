from __future__ import annotations

import hashlib
import os
import time
from fnmatch import fnmatchcase
from pathlib import Path

from ..cancellation import CancellationToken, OperationCancelled
from ..config import Settings
from ..database import Database
from ..models import ProjectRecord
from ..policy import PolicyEngine, PolicyViolation
from ..projects import ProjectService
from .embeddings import EmbeddingProvider
from .extractors import SUPPORTED_EXTENSIONS, chunk_sections, extract_sections
from .models import IndexStats
from .repository import RagRepository


class ProjectIndexer:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        policy: PolicyEngine,
        projects: ProjectService,
        repository: RagRepository,
        embeddings: EmbeddingProvider,
    ):
        self.settings = settings
        self.database = database
        self.policy = policy
        self.projects = projects
        self.repository = repository
        self.embeddings = embeddings

    async def index_project(
        self, project: ProjectRecord, cancellation: CancellationToken
    ) -> IndexStats:
        started = time.monotonic()
        validated = self.projects.validate_action_project(project.id)
        self.projects.require_permission(validated, "read")
        self.projects.require_permission(validated, "index")
        root = self.policy.validate_path(validated.root_path, project_root=Path(validated.root_path))
        seen_paths: set[str] = set()
        scanned = indexed = updated = unchanged = chunks_total = 0
        errors: list[dict[str, str]] = []

        for path in self._iter_documents(root, cancellation):
            cancellation.raise_if_cancelled()
            scanned += 1
            normalized = str(path)
            seen_paths.add(normalized)
            try:
                stat = path.stat()
                source_hash = _sha256(path, cancellation)
                existing = self.repository.get_document(project.id, path)
                if (
                    existing
                    and existing["source_hash"] == source_hash
                    and existing["embedding_model"] == self.embeddings.model
                ):
                    unchanged += 1
                    continue
                sections = extract_sections(
                    path, max_bytes=self.settings.rag_max_document_bytes
                )
                chunks = chunk_sections(
                    sections,
                    max_chars=self.settings.rag_chunk_chars,
                    overlap_chars=self.settings.rag_chunk_overlap_chars,
                )
                vectors: list[tuple[float, ...]] = []
                for offset in range(0, len(chunks), 8):
                    cancellation.raise_if_cancelled()
                    batch = await self.embeddings.embed_documents(
                        [chunk.content for chunk in chunks[offset : offset + 8]],
                        cancellation,
                    )
                    if batch.dimensions != self.settings.embedding_dimensions:
                        raise ValueError(
                            f"Dimensión inesperada: {batch.dimensions}; "
                            f"configurada: {self.settings.embedding_dimensions}."
                        )
                    vectors.extend(batch.vectors)
                was_update = self.repository.replace_document(
                    project_id=project.id,
                    path=path,
                    relative_path=path.relative_to(root).as_posix(),
                    file_type=path.suffix.casefold().lstrip("."),
                    source_hash=source_hash,
                    size_bytes=stat.st_size,
                    modified_ns=stat.st_mtime_ns,
                    chunks=chunks,
                    vectors=vectors,
                    embedding_model=self.embeddings.model,
                )
                indexed += int(not was_update)
                updated += int(was_update)
                chunks_total += len(chunks)
            except OperationCancelled:
                raise
            except Exception as exc:
                errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})

        removed = self.repository.remove_stale(project.id, seen_paths)
        stats = IndexStats(
            project_id=project.id,
            scanned=scanned,
            indexed=indexed,
            updated=updated,
            unchanged=unchanged,
            removed=removed,
            chunks=chunks_total,
            errors=tuple(errors),
            elapsed_seconds=time.monotonic() - started,
        )
        self.database.record_audit(
            session_id=None,
            project_id=project.id,
            event_type="rag_index",
            outcome="partial" if errors else "success",
            detail=stats,
        )
        return stats

    def _iter_documents(self, root: Path, cancellation: CancellationToken):
        excluded_patterns = tuple(self.settings.rag_excluded_path_parts)
        denied = set(self.settings.denied_path_parts)
        for current, directories, files in os.walk(root):
            cancellation.raise_if_cancelled()
            current_path = Path(current)
            safe_directories: list[str] = []
            for directory in directories:
                folded = directory.casefold()
                if folded in denied or any(
                    fnmatchcase(folded, pattern) for pattern in excluded_patterns
                ):
                    continue
                candidate = current_path / directory
                try:
                    safe = self.policy.validate_path(candidate, project_root=root)
                except PolicyViolation:
                    continue
                if safe.is_symlink():
                    continue
                safe_directories.append(directory)
            directories[:] = safe_directories
            for name in sorted(files, key=str.casefold):
                if Path(name).suffix.casefold() not in SUPPORTED_EXTENSIONS:
                    continue
                try:
                    path = self.policy.validate_path(current_path / name, project_root=root)
                except PolicyViolation:
                    continue
                if path.is_file() and not path.is_symlink():
                    yield path


def _sha256(path: Path, cancellation: CancellationToken) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            cancellation.raise_if_cancelled()
            digest.update(block)
    return digest.hexdigest()

