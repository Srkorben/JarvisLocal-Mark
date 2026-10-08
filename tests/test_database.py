import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from jarvis_local.database import Database


class DatabaseTests(TestCase):
    def test_persists_projects_conversation_and_verifiable_audit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "jarvis.db")
            project = database.create_project("Prueba", root, make_active=True)
            session_id = database.create_session("prueba", project.id)
            database.add_message(session_id, "user", "hola")
            database.add_message(session_id, "assistant", "qué tal")
            database.record_audit(
                session_id=session_id,
                project_id=project.id,
                event_type="test",
                outcome="success",
                request={"safe": True},
            )

            self.assertEqual(
                database.load_messages(session_id),
                [
                    {"role": "user", "content": "hola"},
                    {"role": "assistant", "content": "qué tal"},
                ],
            )
            self.assertEqual(database.counts(), {"projects": 1, "sessions": 1, "messages": 2, "audit_events": 1})
            self.assertEqual(database.verify_audit_chain(), (True, []))

    def test_audit_rows_cannot_be_updated_or_deleted(self) -> None:
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "jarvis.db")
            database.record_audit(session_id=None, event_type="test", outcome="success")
            with self.assertRaises(sqlite3.IntegrityError):
                with database.connection() as connection:
                    connection.execute("UPDATE audit_events SET outcome = 'tampered' WHERE id = 1")
            with self.assertRaises(sqlite3.IntegrityError):
                with database.connection() as connection:
                    connection.execute("DELETE FROM audit_events WHERE id = 1")

    def test_project_configuration_and_permissions_are_persisted(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = Database(root / "jarvis.db")
            project = database.create_project(
                "Aislado",
                root,
                make_active=True,
                config={"tags": ["académico"]},
                permissions={"read": True, "index": False, "memory": True},
            )

            reopened = Database(root / "jarvis.db").get_project(project.id)

            self.assertEqual(reopened.config, {"tags": ["académico"]})
            self.assertEqual(
                reopened.permissions,
                {
                    "read": True,
                    "index": False,
                    "memory": True,
                    "open": False,
                    "execute": False,
                    "write": False,
                },
            )
            updated = database.set_project_permission(project.id, "write", True)
            self.assertTrue(updated.permissions["write"])
            self.assertFalse(updated.permissions["execute"])

    def test_reopening_database_does_not_repair_a_tampered_chain(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "jarvis.db"
            database = Database(path)
            database.record_audit(
                session_id=None,
                event_type="test",
                outcome="success",
                detail={"original": True},
            )
            # Simula manipulación externa del archivo SQLite por un proceso con
            # control total. El siguiente arranque debe detectarla, no ocultarla.
            with closing(sqlite3.connect(path)) as connection:
                with connection:
                    connection.execute("DROP TRIGGER audit_events_no_update")
                    connection.execute("UPDATE audit_events SET detail_json = '{\"tampered\":true}'")

            reopened = Database(path)

            valid, errors = reopened.verify_audit_chain()
            self.assertFalse(valid)
            self.assertTrue(any("event_hash" in error for error in errors))

