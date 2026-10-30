from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from jarvis_local.database import Database
from jarvis_local.memory import DecisionSource, EpisodicKind, MemoryRepository


class MemoryTests(TestCase):
    def test_working_memory_is_scoped_to_session_and_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "memory.db")
            first = database.create_project("Uno", root / "uno", make_active=True)
            (root / "dos").mkdir()
            second = database.create_project("Dos", root / "dos")
            session = database.create_session(project_id=first.id)
            memory = MemoryRepository(database)

            memory.set_working(
                session_id=session,
                project_id=first.id,
                key="focus",
                value={"file": "README.md"},
            )

            self.assertEqual(
                memory.get_working(session_id=session, project_id=first.id),
                {"focus": {"file": "README.md"}},
            )
            with self.assertRaises(ValueError):
                memory.get_working(session_id=session, project_id=second.id)

    def test_decisions_and_pending_tasks_require_confirmation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "memory.db")
            project = database.create_project("Uno", root, make_active=True)
            memory = MemoryRepository(database)

            with self.assertRaises(ValueError):
                memory.add_episode(
                    project_id=project.id,
                    kind=EpisodicKind.DECISION,
                    summary="Usar SQLite.",
                )
            event = memory.add_episode(
                project_id=project.id,
                kind=EpisodicKind.DECISION,
                summary="Usar SQLite.",
                source="trusted_local_cli",
                confirmed=True,
            )
            self.assertTrue(event.confirmed)
            self.assertEqual(memory.list_episodes(project_id=project.id)[0].summary, "Usar SQLite.")

    def test_profile_accepts_only_explicit_values_and_is_editable(self) -> None:
        with TemporaryDirectory() as directory:
            memory = MemoryRepository(Database(Path(directory) / "memory.db"))
            with self.assertRaises(ValueError):
                memory.set_profile("idioma", "es", explicit=False)
            created = memory.set_profile("Idioma", "es", explicit=True)
            self.assertEqual(created.key, "idioma")
            self.assertEqual(memory.list_profile()[0].value, "es")
            memory.set_profile("idioma", "es-CO", explicit=True)
            self.assertEqual(memory.get_profile("IDIOMA").value, "es-CO")
            self.assertTrue(memory.delete_profile("idioma"))
            self.assertEqual(memory.list_profile(), [])

    def test_temporal_decision_tracks_contradiction_validity_and_provenance(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "memory.db")
            project = database.create_project("Uno", root / "uno", make_active=True)
            memory = MemoryRepository(database)
            first_time = datetime(2026, 1, 10, 14, 0, tzinfo=timezone.utc)
            second_time = datetime(2026, 2, 3, 9, 30, tzinfo=timezone.utc)

            memory.set_decision(
                project_id=project.id,
                topic="Base de datos principal",
                statement="Usar PostgreSQL.",
                rationale="Necesitábamos acceso concurrente remoto.",
                source=DecisionSource(
                    kind="document",
                    reference="docs/architecture.md",
                    citation="docs/architecture.md#Persistencia",
                    source_hash="sha256:primera",
                ),
                confirmed=True,
                effective_at=first_time,
            )
            state = memory.set_decision(
                project_id=project.id,
                topic="base de datos principal",
                statement="Usar SQLite.",
                rationale="El despliegue será local y de un solo usuario.",
                source=DecisionSource(
                    kind="explicit_user",
                    reference="trusted_local_cli",
                ),
                confirmed=True,
                effective_at=second_time,
            )

            self.assertEqual(state.current.statement, "Usar SQLite.")
            self.assertEqual(state.current.valid_from, second_time.isoformat(timespec="milliseconds"))
            self.assertEqual(state.current.source.kind, "explicit_user")
            self.assertEqual(state.previous.statement, "Usar PostgreSQL.")
            self.assertEqual(state.previous.valid_to, second_time.isoformat(timespec="milliseconds"))
            self.assertEqual(state.previous.source.citation, "docs/architecture.md#Persistencia")
            self.assertEqual(state.current.supersedes_id, state.previous.id)
            self.assertEqual(len(state.history), 2)

            with self.assertRaises(ValueError):
                memory.set_decision(
                    project_id=project.id,
                    topic="Base de datos principal",
                    statement="Usar SQLite.",
                    rationale="Duplicado.",
                    source=DecisionSource(kind="explicit_user", reference="test"),
                    confirmed=True,
                )
            self.assertEqual(
                memory.get_decision_state(
                    project_id=project.id, topic="BASE DE DATOS PRINCIPAL"
                ).current.id,
                state.current.id,
            )

    def test_temporal_decisions_are_project_isolated_and_explicitly_forgettable(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "memory.db")
            first = database.create_project("Uno", root / "uno", make_active=True)
            second = database.create_project("Dos", root / "dos")
            memory = MemoryRepository(database)
            source = DecisionSource(kind="explicit_user", reference="trusted_local_cli")
            for project, statement in ((first, "Usar azul."), (second, "Usar verde.")):
                memory.set_decision(
                    project_id=project.id,
                    topic="Color",
                    statement=statement,
                    rationale="Elección confirmada para este proyecto.",
                    source=source,
                    confirmed=True,
                )

            self.assertEqual(
                memory.get_decision_state(project_id=first.id, topic="color").current.statement,
                "Usar azul.",
            )
            self.assertEqual(
                memory.get_decision_state(project_id=second.id, topic="color").current.statement,
                "Usar verde.",
            )
            with self.assertRaises(ValueError):
                memory.forget_decision_topic(project_id=first.id, topic="color", explicit=False)
            self.assertEqual(
                memory.forget_decision_topic(project_id=first.id, topic="color", explicit=True),
                1,
            )
            forgotten = memory.get_decision_state(project_id=first.id, topic="color")
            self.assertIsNone(forgotten.current)
            self.assertIsNone(forgotten.previous)
            self.assertEqual(forgotten.history, ())
            self.assertEqual(
                memory.get_decision_state(project_id=second.id, topic="color").current.statement,
                "Usar verde.",
            )

    def test_temporal_decision_requires_confirmation_and_memory_permission(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "memory.db")
            allowed = database.create_project("Permitido", root / "allowed")
            denied = database.create_project(
                "Denegado", root / "denied", permissions={"memory": False}
            )
            memory = MemoryRepository(database)
            source = DecisionSource(kind="explicit_user", reference="trusted_local_cli")

            with self.assertRaises(ValueError):
                memory.set_decision(
                    project_id=allowed.id,
                    topic="Motor",
                    statement="Usar llama.cpp.",
                    rationale="Control local.",
                    source=source,
                    confirmed=False,
                )
            with self.assertRaises(PermissionError):
                memory.set_decision(
                    project_id=denied.id,
                    topic="Motor",
                    statement="Usar llama.cpp.",
                    rationale="Control local.",
                    source=source,
                    confirmed=True,
                )
            with self.assertRaises(PermissionError):
                memory.get_decision_state(project_id=denied.id, topic="Motor")
            with self.assertRaises(PermissionError):
                memory.forget_decision_topic(
                    project_id=denied.id, topic="Motor", explicit=True
                )

