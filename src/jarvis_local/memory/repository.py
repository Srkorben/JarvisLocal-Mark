from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ..database import Database, canonical_json, utc_now
from .models import (
    DecisionSource,
    DecisionState,
    EpisodicEvent,
    EpisodicKind,
    ProfileEntry,
    TemporalDecision,
)


class MemoryRepository:
    """Persistencia explícita; no decide por sí sola qué merece recordarse."""

    def __init__(self, database: Database):
        self.database = database

    def set_working(
        self,
        *,
        session_id: str,
        project_id: str,
        key: str,
        value: Any,
    ) -> None:
        normalized_key = key.strip()
        if not normalized_key:
            raise ValueError("La clave de memoria de trabajo no puede estar vacía.")
        self._require_session_project(session_id, project_id)
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO working_memory(session_id, project_id, key, value_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, key) DO UPDATE SET
                    project_id = excluded.project_id,
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (session_id, project_id, normalized_key, canonical_json(value), utc_now()),
            )

    def get_working(self, *, session_id: str, project_id: str) -> dict[str, Any]:
        self._require_session_project(session_id, project_id)
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT key, value_json FROM working_memory
                WHERE session_id = ? AND project_id = ? ORDER BY key
                """,
                (session_id, project_id),
            ).fetchall()
        return {str(row["key"]): json.loads(row["value_json"]) for row in rows}

    def clear_working(self, *, session_id: str, project_id: str) -> int:
        self._require_session_project(session_id, project_id)
        with self.database.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM working_memory WHERE session_id = ? AND project_id = ?",
                (session_id, project_id),
            )
        return int(cursor.rowcount)

    def add_episode(
        self,
        *,
        project_id: str,
        kind: EpisodicKind,
        summary: str,
        session_id: str | None = None,
        detail: dict[str, Any] | None = None,
        source: str = "jarvis",
        confirmed: bool = False,
        occurred_at: datetime | None = None,
    ) -> EpisodicEvent:
        normalized_summary = summary.strip()
        if not normalized_summary:
            raise ValueError("El resumen episódico no puede estar vacío.")
        if kind in {EpisodicKind.DECISION, EpisodicKind.PENDING_TASK} and not confirmed:
            raise ValueError("Las decisiones y pendientes requieren confirmación explícita.")
        self.database.get_project(project_id)
        if session_id is not None:
            self._require_session_project(session_id, project_id)
        event_id = str(uuid.uuid4())
        created_at = utc_now()
        timestamp = (occurred_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        ).isoformat(timespec="milliseconds")
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO episodic_events(
                    id, project_id, session_id, kind, summary, detail_json,
                    source, confirmed, occurred_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    project_id,
                    session_id,
                    kind.value,
                    normalized_summary,
                    canonical_json(detail or {}),
                    source,
                    int(confirmed),
                    timestamp,
                    created_at,
                ),
            )
        return self.get_episode(event_id)

    def get_episode(self, event_id: str) -> EpisodicEvent:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM episodic_events WHERE id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Evento episódico no encontrado: {event_id}")
        return self._episode_from_row(row)

    def list_episodes(
        self,
        *,
        project_id: str,
        limit: int = 20,
        kind: EpisodicKind | None = None,
        since: str | None = None,
    ) -> list[EpisodicEvent]:
        if not 1 <= limit <= 100:
            raise ValueError("El límite de episodios debe estar entre 1 y 100.")
        clauses = ["project_id = ?"]
        values: list[Any] = [project_id]
        if kind is not None:
            clauses.append("kind = ?")
            values.append(kind.value)
        if since is not None:
            clauses.append("occurred_at >= ?")
            values.append(since)
        values.append(limit)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM episodic_events
                WHERE {' AND '.join(clauses)}
                ORDER BY occurred_at DESC, created_at DESC LIMIT ?
                """,
                values,
            ).fetchall()
        return [self._episode_from_row(row) for row in rows]

    def set_profile(self, key: str, value: Any, *, explicit: bool) -> ProfileEntry:
        if not explicit:
            raise ValueError("El perfil solo acepta preferencias explícitas del usuario.")
        normalized_key = key.strip().casefold()
        if not normalized_key:
            raise ValueError("La clave de perfil no puede estar vacía.")
        timestamp = utc_now()
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO profile_entries(key, value_json, source, created_at, updated_at)
                VALUES (?, ?, 'explicit_user', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (normalized_key, canonical_json(value), timestamp, timestamp),
            )
        return self.get_profile(normalized_key)

    def get_profile(self, key: str) -> ProfileEntry:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM profile_entries WHERE key = ?", (key.casefold(),)
            ).fetchone()
        if row is None:
            raise KeyError(f"Preferencia no encontrada: {key}")
        return ProfileEntry(
            key=row["key"],
            value=json.loads(row["value_json"]),
            source=row["source"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_profile(self) -> list[ProfileEntry]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM profile_entries ORDER BY key"
            ).fetchall()
        return [
            ProfileEntry(
                key=row["key"],
                value=json.loads(row["value_json"]),
                source=row["source"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def delete_profile(self, key: str) -> bool:
        with self.database.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM profile_entries WHERE key = ?", (key.casefold(),)
            )
        return cursor.rowcount > 0

    def set_decision(
        self,
        *,
        project_id: str,
        topic: str,
        statement: str,
        rationale: str,
        source: DecisionSource,
        confirmed: bool,
        effective_at: datetime | None = None,
    ) -> DecisionState:
        """Crea o sustituye atómicamente la decisión vigente de un tema.

        El tema es la identidad determinista de la cadena temporal. No se intenta
        inferir contradicciones con un LLM y ninguna evidencia documental concede
        autoridad para persistir: el llamador debe aportar ``confirmed=True`` desde
        una superficie local confiable.
        """

        if not confirmed:
            raise ValueError("Una decisión temporal requiere confirmación explícita.")
        self._require_memory_permission(project_id)
        normalized_topic = " ".join(topic.split())
        normalized_statement = " ".join(statement.split())
        normalized_rationale = " ".join(rationale.split())
        if not normalized_topic or not normalized_statement or not normalized_rationale:
            raise ValueError("Tema, decisión y motivo son obligatorios.")
        topic_key = normalized_topic.casefold()
        timestamp = (effective_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        ).isoformat(timespec="milliseconds")
        decision_id = str(uuid.uuid4())

        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT * FROM temporal_decisions
                WHERE project_id = ? AND topic_key = ? AND status = 'current'
                """,
                (project_id, topic_key),
            ).fetchone()
            if current is not None and current["statement"] == normalized_statement:
                raise ValueError("La decisión indicada ya es la vigente para este tema.")
            supersedes_id = None if current is None else str(current["id"])
            if current is not None:
                connection.execute(
                    """
                    UPDATE temporal_decisions
                    SET status = 'superseded', valid_to = ?
                    WHERE id = ? AND status = 'current'
                    """,
                    (timestamp, supersedes_id),
                )
            connection.execute(
                """
                INSERT INTO temporal_decisions(
                    id, project_id, topic_key, topic, statement, rationale,
                    source_json, supersedes_id, valid_from, valid_to, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 'current', ?)
                """,
                (
                    decision_id,
                    project_id,
                    topic_key,
                    normalized_topic,
                    normalized_statement,
                    normalized_rationale,
                    canonical_json(source),
                    supersedes_id,
                    timestamp,
                    utc_now(),
                ),
            )
        return self.get_decision_state(project_id=project_id, topic=normalized_topic)

    def get_decision_state(self, *, project_id: str, topic: str) -> DecisionState:
        self._require_memory_permission(project_id)
        normalized_topic = " ".join(topic.split())
        if not normalized_topic:
            raise ValueError("El tema de la decisión no puede estar vacío.")
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM temporal_decisions
                WHERE project_id = ? AND topic_key = ?
                ORDER BY valid_from DESC, created_at DESC
                """,
                (project_id, normalized_topic.casefold()),
            ).fetchall()
        history = tuple(self._decision_from_row(row) for row in rows)
        current = next((item for item in history if item.status == "current"), None)
        previous = next(
            (item for item in history if current is None or item.id != current.id),
            None,
        )
        return DecisionState(
            project_id=project_id,
            topic=normalized_topic,
            current=current,
            previous=previous,
            history=history,
        )

    def forget_decision_topic(
        self, *, project_id: str, topic: str, explicit: bool
    ) -> int:
        """Elimina toda la cadena de un tema; no reactiva versiones anteriores."""

        if not explicit:
            raise ValueError("Olvidar una decisión requiere una solicitud explícita.")
        self._require_memory_permission(project_id)
        normalized_topic = " ".join(topic.split())
        if not normalized_topic:
            raise ValueError("El tema de la decisión no puede estar vacío.")
        with self.database.connection() as connection:
            cursor = connection.execute(
                "DELETE FROM temporal_decisions WHERE project_id = ? AND topic_key = ?",
                (project_id, normalized_topic.casefold()),
            )
        return int(cursor.rowcount)

    def counts(self) -> dict[str, int]:
        with self.database.connection() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (
                    "working_memory",
                    "episodic_events",
                    "profile_entries",
                    "temporal_decisions",
                    "document_sources",
                    "document_chunks",
                )
            }

    def _require_session_project(self, session_id: str, project_id: str) -> None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT project_id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Sesión no encontrada: {session_id}")
        if row["project_id"] != project_id:
            raise ValueError("La sesión pertenece a otro proyecto.")

    def _require_memory_permission(self, project_id: str) -> None:
        project = self.database.get_project(project_id)
        if not project.permissions.get("memory", False):
            raise PermissionError("El proyecto no autoriza memoria persistente.")

    @staticmethod
    def _episode_from_row(row) -> EpisodicEvent:
        return EpisodicEvent(
            id=row["id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            kind=EpisodicKind(row["kind"]),
            summary=row["summary"],
            detail=json.loads(row["detail_json"] or "{}"),
            source=row["source"],
            confirmed=bool(row["confirmed"]),
            occurred_at=row["occurred_at"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _decision_from_row(row) -> TemporalDecision:
        return TemporalDecision(
            id=row["id"],
            project_id=row["project_id"],
            topic=row["topic"],
            statement=row["statement"],
            rationale=row["rationale"],
            source=DecisionSource.model_validate(json.loads(row["source_json"])),
            supersedes_id=row["supersedes_id"],
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            status=row["status"],
            created_at=row["created_at"],
        )

