from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel

from .models import ProjectRecord, ProjectStatus


SCHEMA_VERSION = 4
GENESIS_HASH = "0" * 64


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def json_value(value: Any) -> Any:
    """Convierte recursivamente valores del dominio al JSON realmente persistido."""

    if isinstance(value, BaseModel):
        return json_value(value.model_dump(mode="json"))
    if isinstance(value, Enum):
        return json_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def _add_column(connection: sqlite3.Connection, table: str, definition: str) -> None:
        name = definition.split()[0]
        if name not in Database._columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    root_path TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'enabled',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    permissions_json TEXT NOT NULL DEFAULT '{}',
                    is_active INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0, 1)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_project
                ON projects(is_active) WHERE is_active = 1;

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    project_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, id);

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT,
                    session_id TEXT,
                    project_id TEXT,
                    event_type TEXT NOT NULL,
                    intent TEXT,
                    tool_name TEXT,
                    risk_level INTEGER,
                    outcome TEXT NOT NULL,
                    request_json TEXT NOT NULL DEFAULT '{}',
                    plan_json TEXT NOT NULL DEFAULT '{}',
                    policy_json TEXT NOT NULL DEFAULT '{}',
                    confirmation_json TEXT NOT NULL DEFAULT '{}',
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    verification_json TEXT NOT NULL DEFAULT '{}',
                    rollback_json TEXT NOT NULL DEFAULT '{}',
                    cancelled INTEGER NOT NULL DEFAULT 0,
                    previous_hash TEXT,
                    event_hash TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS working_memory (
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, key)
                );

                CREATE TABLE IF NOT EXISTS episodic_events (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    source TEXT NOT NULL,
                    confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0, 1)),
                    occurred_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_episodes_project_time
                ON episodic_events(project_id, occurred_at DESC);

                CREATE TABLE IF NOT EXISTS profile_entries (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source = 'explicit_user'),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS temporal_decisions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    topic_key TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    supersedes_id TEXT REFERENCES temporal_decisions(id) ON DELETE SET NULL,
                    valid_from TEXT NOT NULL,
                    valid_to TEXT,
                    status TEXT NOT NULL CHECK(status IN ('current', 'superseded')),
                    created_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_temporal_decision_current
                ON temporal_decisions(project_id, topic_key) WHERE status = 'current';

                CREATE INDEX IF NOT EXISTS idx_temporal_decision_history
                ON temporal_decisions(project_id, topic_key, valid_from DESC);

                CREATE TABLE IF NOT EXISTS document_sources (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    path TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'indexed',
                    error TEXT,
                    UNIQUE(project_id, path)
                );

                CREATE INDEX IF NOT EXISTS idx_document_sources_project
                ON document_sources(project_id, relative_path);

                CREATE TABLE IF NOT EXISTS document_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL REFERENCES document_sources(id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    section_title TEXT,
                    page_number INTEGER,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    embedding_dimensions INTEGER NOT NULL,
                    embedding_model TEXT NOT NULL,
                    suspicious_instructions INTEGER NOT NULL DEFAULT 0 CHECK(suspicious_instructions IN (0, 1)),
                    created_at TEXT NOT NULL,
                    UNIQUE(document_id, chunk_index)
                );

                CREATE INDEX IF NOT EXISTS idx_document_chunks_project
                ON document_chunks(project_id, document_id);
                """
            )

            try:
                connection.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
                        content,
                        section_title,
                        content='document_chunks',
                        content_rowid='id',
                        tokenize='unicode61 remove_diacritics 2'
                    );

                    CREATE TRIGGER IF NOT EXISTS document_chunks_fts_insert
                    AFTER INSERT ON document_chunks BEGIN
                        INSERT INTO document_chunks_fts(rowid, content, section_title)
                        VALUES (new.id, new.content, new.section_title);
                    END;

                    CREATE TRIGGER IF NOT EXISTS document_chunks_fts_delete
                    AFTER DELETE ON document_chunks BEGIN
                        INSERT INTO document_chunks_fts(document_chunks_fts, rowid, content, section_title)
                        VALUES ('delete', old.id, old.content, old.section_title);
                    END;

                    CREATE TRIGGER IF NOT EXISTS document_chunks_fts_update
                    AFTER UPDATE ON document_chunks BEGIN
                        INSERT INTO document_chunks_fts(document_chunks_fts, rowid, content, section_title)
                        VALUES ('delete', old.id, old.content, old.section_title);
                        INSERT INTO document_chunks_fts(rowid, content, section_title)
                        VALUES (new.id, new.content, new.section_title);
                    END;
                    """
                )
            except sqlite3.OperationalError as exc:
                raise RuntimeError("SQLite FTS5 es obligatorio para memoria documental.") from exc

            # Migración conservadora desde el prototipo inicial.
            self._add_column(connection, "sessions", "project_id TEXT")
            self._add_column(connection, "projects", "status TEXT NOT NULL DEFAULT 'enabled'")
            self._add_column(connection, "projects", "permissions_json TEXT NOT NULL DEFAULT '{}'")
            for definition in (
                "event_id TEXT",
                "project_id TEXT",
                "intent TEXT",
                "plan_json TEXT NOT NULL DEFAULT '{}'",
                "policy_json TEXT NOT NULL DEFAULT '{}'",
                "confirmation_json TEXT NOT NULL DEFAULT '{}'",
                "verification_json TEXT NOT NULL DEFAULT '{}'",
                "rollback_json TEXT NOT NULL DEFAULT '{}'",
                "cancelled INTEGER NOT NULL DEFAULT 0",
                "previous_hash TEXT",
                "event_hash TEXT",
            ):
                self._add_column(connection, "audit_events", definition)

            needs_backfill = bool(
                connection.execute(
                    """
                    SELECT 1 FROM audit_events
                    WHERE event_id IS NULL OR previous_hash IS NULL OR event_hash IS NULL
                    LIMIT 1
                    """
                ).fetchone()
            )
            if needs_backfill:
                # Solo una migración desde el esquema anterior puede suspender
                # temporalmente las protecciones append-only. En arranques
                # normales jamás se recalculan hashes existentes.
                connection.executescript(
                    """
                    DROP TRIGGER IF EXISTS audit_events_no_update;
                    DROP TRIGGER IF EXISTS audit_events_no_delete;
                    """
                )
                self._backfill_audit_chain(connection)
            connection.executescript(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_event_id ON audit_events(event_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_event_hash ON audit_events(event_hash);

                CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit_events is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit_events is append-only');
                END;
                """
            )
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def _audit_payload_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": row["event_id"],
            "session_id": row["session_id"],
            "project_id": row["project_id"],
            "event_type": row["event_type"],
            "intent": row["intent"],
            "tool_name": row["tool_name"],
            "risk_level": row["risk_level"],
            "outcome": row["outcome"],
            "request": json.loads(row["request_json"] or "{}"),
            "plan": json.loads(row["plan_json"] or "{}"),
            "policy": json.loads(row["policy_json"] or "{}"),
            "confirmation": json.loads(row["confirmation_json"] or "{}"),
            "detail": json.loads(row["detail_json"] or "{}"),
            "verification": json.loads(row["verification_json"] or "{}"),
            "rollback": json.loads(row["rollback_json"] or "{}"),
            "cancelled": bool(row["cancelled"]),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _event_hash(previous_hash: str, payload: dict[str, Any]) -> str:
        material = f"{previous_hash}\n{canonical_json(payload)}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def _backfill_audit_chain(self, connection: sqlite3.Connection) -> None:
        previous_hash = GENESIS_HASH
        rows = connection.execute("SELECT * FROM audit_events ORDER BY id ASC").fetchall()
        for row in rows:
            if row["event_id"] and row["previous_hash"] and row["event_hash"]:
                previous_hash = str(row["event_hash"])
                continue
            event_id = row["event_id"] or str(uuid.uuid4())
            mutable = dict(row)
            mutable["event_id"] = event_id
            payload = self._audit_payload_from_row(_MappingRow(mutable))
            event_hash = self._event_hash(previous_hash, payload)
            connection.execute(
                "UPDATE audit_events SET event_id = ?, previous_hash = ?, event_hash = ? WHERE id = ?",
                (event_id, previous_hash, event_hash, row["id"]),
            )
            previous_hash = event_hash

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> ProjectRecord:
        permissions = {
            "read": True,
            "index": True,
            "memory": True,
            "open": False,
            "execute": False,
            "write": False,
        }
        permissions.update(json.loads(row["permissions_json"] or "{}"))
        return ProjectRecord(
            id=row["id"],
            name=row["name"],
            root_path=row["root_path"],
            status=ProjectStatus(row["status"]),
            config=json.loads(row["config_json"] or "{}"),
            permissions=permissions,
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_project(
        self,
        name: str,
        root_path: Path,
        *,
        make_active: bool = False,
        config: dict[str, Any] | None = None,
        permissions: dict[str, bool] | None = None,
    ) -> ProjectRecord:
        project_id = str(uuid.uuid4())
        timestamp = utc_now()
        with self.connection() as connection:
            if make_active:
                connection.execute("UPDATE projects SET is_active = 0")
            connection.execute(
                """
                INSERT INTO projects(
                    id, name, root_path, status, config_json, permissions_json,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    name,
                    str(root_path.resolve()),
                    ProjectStatus.ENABLED.value,
                    canonical_json(config or {}),
                    canonical_json(
                        {
                            "read": True,
                            "index": True,
                            "memory": True,
                            "open": False,
                            "execute": False,
                            "write": False,
                        }
                        | (permissions or {})
                    ),
                    int(make_active),
                    timestamp,
                    timestamp,
                ),
            )
        return self.get_project(project_id)

    def set_project_permission(
        self, project_id: str, permission: str, enabled: bool
    ) -> ProjectRecord:
        project = self.get_project(project_id)
        permissions = dict(project.permissions)
        permissions[permission] = enabled
        timestamp = utc_now()
        with self.connection() as connection:
            connection.execute(
                "UPDATE projects SET permissions_json = ?, updated_at = ? WHERE id = ?",
                (canonical_json(permissions), timestamp, project_id),
            )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> ProjectRecord:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise KeyError(f"Proyecto no encontrado: {project_id}")
        return self._project_from_row(row)

    def list_projects(self) -> list[ProjectRecord]:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM projects ORDER BY name COLLATE NOCASE").fetchall()
        return [self._project_from_row(row) for row in rows]

    def get_active_project(self) -> ProjectRecord | None:
        with self.connection() as connection:
            row = connection.execute("SELECT id FROM projects WHERE is_active = 1").fetchone()
        return None if row is None else self.get_project(str(row["id"]))

    def set_active_project(self, project_id: str) -> ProjectRecord:
        timestamp = utc_now()
        with self.connection() as connection:
            exists = connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
            if exists is None:
                raise KeyError(f"Proyecto no encontrado: {project_id}")
            connection.execute("UPDATE projects SET is_active = 0")
            connection.execute(
                "UPDATE projects SET is_active = 1, updated_at = ? WHERE id = ?",
                (timestamp, project_id),
            )
        return self.get_project(project_id)

    def create_session(self, title: str | None = None, project_id: str | None = None) -> str:
        session_id = str(uuid.uuid4())
        timestamp = utc_now()
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO sessions(id, title, project_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, title, project_id, timestamp, timestamp),
            )
        return session_id

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        timestamp = utc_now()
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO messages(session_id, role, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, content, canonical_json(metadata or {}), timestamp),
            )
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (timestamp, session_id),
            )

    def load_messages(self, session_id: str, limit: int = 30) -> list[dict[str, str]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT role, content FROM (
                    SELECT id, role, content
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                ) ORDER BY id ASC
                """,
                (session_id, limit),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def record_audit(
        self,
        *,
        session_id: str | None,
        event_type: str,
        outcome: str,
        project_id: str | None = None,
        intent: str | None = None,
        tool_name: str | None = None,
        risk_level: int | None = None,
        request: Any = None,
        plan: Any = None,
        policy: Any = None,
        confirmation: Any = None,
        detail: Any = None,
        verification: Any = None,
        rollback: Any = None,
        cancelled: bool = False,
    ) -> str:
        event_id = str(uuid.uuid4())
        timestamp = utc_now()
        payload = {
            "event_id": event_id,
            "session_id": session_id,
            "project_id": project_id,
            "event_type": event_type,
            "intent": intent,
            "tool_name": tool_name,
            "risk_level": risk_level,
            "outcome": outcome,
            "request": request or {},
            "plan": plan or {},
            "policy": policy or {},
            "confirmation": confirmation or {},
            "detail": detail or {},
            "verification": verification or {},
            "rollback": rollback or {},
            "cancelled": cancelled,
            "created_at": timestamp,
        }
        serializable_payload = json.loads(canonical_json(payload))

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            previous_hash = GENESIS_HASH if row is None else str(row["event_hash"])
            event_hash = self._event_hash(previous_hash, serializable_payload)
            connection.execute(
                """
                INSERT INTO audit_events(
                    event_id, session_id, project_id, event_type, intent, tool_name,
                    risk_level, outcome, request_json, plan_json, policy_json,
                    confirmation_json, detail_json, verification_json, rollback_json,
                    cancelled, previous_hash, event_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    project_id,
                    event_type,
                    intent,
                    tool_name,
                    risk_level,
                    outcome,
                    canonical_json(request or {}),
                    canonical_json(plan or {}),
                    canonical_json(policy or {}),
                    canonical_json(confirmation or {}),
                    canonical_json(detail or {}),
                    canonical_json(verification or {}),
                    canonical_json(rollback or {}),
                    int(cancelled),
                    previous_hash,
                    event_hash,
                    timestamp,
                ),
            )
        return event_id

    def verify_audit_chain(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        previous_hash = GENESIS_HASH
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM audit_events ORDER BY id ASC").fetchall()
        for row in rows:
            if row["previous_hash"] != previous_hash:
                errors.append(f"Evento {row['id']}: previous_hash no coincide.")
            expected = self._event_hash(previous_hash, self._audit_payload_from_row(row))
            if row["event_hash"] != expected:
                errors.append(f"Evento {row['id']}: event_hash no coincide.")
            previous_hash = str(row["event_hash"])
        return not errors, errors

    def counts(self) -> dict[str, int]:
        with self.connection() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("projects", "sessions", "messages", "audit_events")
            }


class _MappingRow:
    """Adaptador mínimo para reutilizar serialización durante migraciones."""

    def __init__(self, values: dict[str, Any]):
        self._values = values

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

