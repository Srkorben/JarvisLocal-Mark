from __future__ import annotations

import hashlib
import math
import re
import struct
import uuid
from pathlib import Path
from typing import Any

from ..database import Database, utc_now
from .models import ChunkDraft


_LEXICAL_STOPWORDS = {
    "a", "al", "algo", "como", "con", "cuál", "cual", "de", "del", "donde",
    "dónde", "el", "ella", "en", "es", "esta", "este", "la", "las", "lo",
    "los", "para", "por", "que", "qué", "se", "su", "sus", "un", "una", "y",
    "and", "for", "from", "how", "the", "what", "where", "with",
}


class RagRepository:
    def __init__(self, database: Database):
        self.database = database

    def get_document(self, project_id: str, path: Path) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT d.*,
                       (SELECT embedding_model FROM document_chunks c
                        WHERE c.document_id = d.id LIMIT 1) AS embedding_model
                FROM document_sources d WHERE project_id = ? AND path = ?
                """,
                (project_id, str(path)),
            ).fetchone()
        return None if row is None else dict(row)

    def replace_document(
        self,
        *,
        project_id: str,
        path: Path,
        relative_path: str,
        file_type: str,
        source_hash: str,
        size_bytes: int,
        modified_ns: int,
        chunks: list[ChunkDraft],
        vectors: list[tuple[float, ...]],
        embedding_model: str,
    ) -> bool:
        if len(chunks) != len(vectors):
            raise ValueError("Cada fragmento debe tener exactamente un embedding.")
        existing = self.get_document(project_id, path)
        document_id = str(existing["id"]) if existing else str(uuid.uuid4())
        timestamp = utc_now()
        with self.database.connection() as connection:
            if existing:
                connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
                connection.execute(
                    """
                    UPDATE document_sources SET relative_path = ?, file_type = ?,
                        source_hash = ?, size_bytes = ?, modified_ns = ?, indexed_at = ?,
                        status = 'indexed', error = NULL
                    WHERE id = ?
                    """,
                    (
                        relative_path,
                        file_type,
                        source_hash,
                        size_bytes,
                        modified_ns,
                        timestamp,
                        document_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO document_sources(
                        id, project_id, path, relative_path, file_type, source_hash,
                        size_bytes, modified_ns, indexed_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'indexed')
                    """,
                    (
                        document_id,
                        project_id,
                        str(path),
                        relative_path,
                        file_type,
                        source_hash,
                        size_bytes,
                        modified_ns,
                        timestamp,
                    ),
                )
            for chunk, vector in zip(chunks, vectors, strict=True):
                connection.execute(
                    """
                    INSERT INTO document_chunks(
                        document_id, project_id, chunk_index, section_title, page_number,
                        content, content_hash, embedding, embedding_dimensions,
                        embedding_model, suspicious_instructions, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        project_id,
                        chunk.index,
                        chunk.section_title,
                        chunk.page_number,
                        chunk.content,
                        hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
                        pack_vector(vector),
                        len(vector),
                        embedding_model,
                        int(chunk.suspicious_instructions),
                        timestamp,
                    ),
                )
        return existing is not None

    def remove_stale(self, project_id: str, current_paths: set[str]) -> int:
        with self.database.connection() as connection:
            if current_paths:
                placeholders = ",".join("?" for _ in current_paths)
                cursor = connection.execute(
                    f"DELETE FROM document_sources WHERE project_id = ? AND path NOT IN ({placeholders})",
                    [project_id, *sorted(current_paths)],
                )
            else:
                cursor = connection.execute(
                    "DELETE FROM document_sources WHERE project_id = ?", (project_id,)
                )
        return int(cursor.rowcount)

    def keyword_search(
        self,
        *,
        project_id: str,
        query: str,
        limit: int,
        modified_after_ns: int | None = None,
        modified_before_ns: int | None = None,
    ) -> list[dict[str, Any]]:
        match_query = fts_query(query)
        if not match_query:
            return []
        clauses = ["c.project_id = ?", "document_chunks_fts MATCH ?"]
        values: list[Any] = [project_id, match_query]
        if modified_after_ns is not None:
            clauses.append("d.modified_ns >= ?")
            values.append(modified_after_ns)
        if modified_before_ns is not None:
            clauses.append("d.modified_ns <= ?")
            values.append(modified_before_ns)
        values.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT c.id AS chunk_id, c.*, d.path, d.relative_path,
                       d.source_hash, d.modified_ns, bm25(document_chunks_fts) AS lexical_score
                FROM document_chunks_fts
                JOIN document_chunks c ON c.id = document_chunks_fts.rowid
                JOIN document_sources d ON d.id = c.document_id
                WHERE {' AND '.join(clauses)}
                ORDER BY lexical_score ASC LIMIT ?
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def vector_candidates(
        self,
        *,
        project_id: str,
        embedding_model: str,
        scan_limit: int,
        modified_after_ns: int | None = None,
        modified_before_ns: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["c.project_id = ?", "c.embedding_model = ?"]
        values: list[Any] = [project_id, embedding_model]
        if modified_after_ns is not None:
            clauses.append("d.modified_ns >= ?")
            values.append(modified_after_ns)
        if modified_before_ns is not None:
            clauses.append("d.modified_ns <= ?")
            values.append(modified_before_ns)
        with self.database.connection() as connection:
            count = int(
                connection.execute(
                    f"""
                    SELECT COUNT(*) FROM document_chunks c
                    JOIN document_sources d ON d.id = c.document_id
                    WHERE {' AND '.join(clauses)}
                    """,
                    values,
                ).fetchone()[0]
            )
            if count > scan_limit:
                raise RuntimeError(
                    f"El proyecto tiene {count} vectores; supera el límite exacto de {scan_limit}. "
                    "Evalúa un índice ANN antes de continuar."
                )
            rows = connection.execute(
                f"""
                SELECT c.id AS chunk_id, c.*, d.path, d.relative_path,
                       d.source_hash, d.modified_ns
                FROM document_chunks c
                JOIN document_sources d ON d.id = c.document_id
                WHERE {' AND '.join(clauses)}
                """,
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def counts(self, project_id: str) -> dict[str, int]:
        with self.database.connection() as connection:
            documents = int(
                connection.execute(
                    "SELECT COUNT(*) FROM document_sources WHERE project_id = ?",
                    (project_id,),
                ).fetchone()[0]
            )
            chunks = int(
                connection.execute(
                    "SELECT COUNT(*) FROM document_chunks WHERE project_id = ?",
                    (project_id,),
                ).fetchone()[0]
            )
        return {"documents": documents, "chunks": chunks}


def fts_query(query: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[^\W_]{2,}", query.casefold(), flags=re.UNICODE)
        if token not in _LEXICAL_STOPWORDS
    ]
    unique = list(dict.fromkeys(tokens))[:20]
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in unique)


def pack_vector(vector: tuple[float, ...]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes, dimensions: int) -> tuple[float, ...]:
    if len(blob) != dimensions * 4:
        raise ValueError("El BLOB vectorial no coincide con sus dimensiones.")
    return tuple(struct.unpack(f"<{dimensions}f", blob))


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        return -1.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return dot / (left_norm * right_norm)

