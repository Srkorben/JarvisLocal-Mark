"""H-01: ``logging.store_conversation_content`` debe cumplirse de verdad."""

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from jarvis_local.cancellation import CancellationToken
from jarvis_local.database import Database
from jarvis_local.execution import ActionExecutor
from jarvis_local.orchestrator import Orchestrator
from jarvis_local.policy import PolicyEngine
from jarvis_local.projects import ProjectService
from jarvis_local.tools import build_default_registry
from tests.mark.helpers import make_settings
from tests.mark.test_orchestrator import SequenceProvider, text_response, tool_response


SECRET_QUESTION = "mi-dato-privado-7f3a ¿qué hora es?"


class CapturingProvider(SequenceProvider):
    def __init__(self, responses):
        super().__init__(responses)
        self.requests: list[list[dict]] = []

    async def stream_chat(self, messages, tools, cancellation):
        self.requests.append([dict(item) for item in messages])
        async for event in super().stream_chat(messages, tools, cancellation):
            yield event
SECRET_ANSWER = "respuesta-privada-91bc"


class ConversationPrivacyTests(IsolatedAsyncioTestCase):
    def build(self, root: Path, provider, *, store: bool):
        settings = make_settings(root, store_conversation_content=store)
        database = Database(settings.database_path)
        policy = PolicyEngine(settings)
        projects = ProjectService(database, policy)
        project = projects.ensure_bootstrap_project("Test", root)
        registry = build_default_registry(settings, policy, projects=projects)
        executor = ActionExecutor(
            settings=settings, database=database, registry=registry, policy=policy, projects=projects
        )
        orchestrator = Orchestrator(
            settings=settings, database=database, provider=provider, registry=registry, executor=executor
        )
        return settings, database, project, orchestrator

    def provider(self):
        return CapturingProvider([
            tool_response("get_current_time", '{"expected_result":"hora local"}'),
            text_response(SECRET_ANSWER),
            text_response("segunda respuesta"),
        ])

    def database_text(self, path: Path) -> str:
        connection = sqlite3.connect(path)
        try:
            chunks = []
            for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
                for row in connection.execute(f'SELECT * FROM "{table}"'):
                    chunks.append(" ".join(str(value) for value in row))
            return "\n".join(chunks)
        finally:
            connection.close()

    async def test_disabled_keeps_conversation_out_of_sqlite_but_in_context(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            provider = self.provider()
            settings, database, project, orchestrator = self.build(root, provider, store=False)
            session = database.create_session(project_id=project.id)
            first = await orchestrator.chat(session, project, SECRET_QUESTION, CancellationToken())
            self.assertEqual(first, SECRET_ANSWER)
            await orchestrator.chat(session, project, "¿y ahora?", CancellationToken())
            stored = self.database_text(settings.database_path)
            self.assertNotIn("mi-dato-privado-7f3a", stored)
            self.assertNotIn(SECRET_ANSWER, stored)
            self.assertEqual(database.load_messages(session), [])
            # El contexto de la sesión sigue disponible en memoria para el modelo.
            contents = " ".join(str(m.get("content")) for m in provider.requests[-1])
            self.assertIn("mi-dato-privado-7f3a", contents)
            self.assertIn(SECRET_ANSWER, contents)
            history = orchestrator._history(session)
            self.assertIn(SECRET_QUESTION, [item["content"] for item in history])
            # La auditoría de la herramienta se conserva, sin el texto del usuario.
            with database.connection() as connection:
                audit = connection.execute(
                    "SELECT tool_name, outcome, intent FROM audit_events WHERE event_type='tool_execution'"
                ).fetchall()
            self.assertEqual([(row[0], row[1]) for row in audit], [("get_current_time", "success")])
            self.assertTrue(audit[0][2].startswith("[contenido no almacenado"))
            valid, errors = database.verify_audit_chain()
            self.assertTrue(valid, errors)

    async def test_enabled_persists_conversation_and_intent(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            settings, database, project, orchestrator = self.build(root, self.provider(), store=True)
            session = database.create_session(project_id=project.id)
            await orchestrator.chat(session, project, SECRET_QUESTION, CancellationToken())
            stored = self.database_text(settings.database_path)
            self.assertIn("mi-dato-privado-7f3a", stored)
            self.assertIn(SECRET_ANSWER, stored)
            self.assertEqual(
                [item["role"] for item in database.load_messages(session)], ["user", "assistant"]
            )

    async def test_existing_conversations_are_not_deleted(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            settings, database, project, orchestrator = self.build(
                root, SequenceProvider([text_response("nueva")]), store=False
            )
            session = database.create_session(project_id=project.id)
            database.add_message(session, "user", "mensaje-antiguo")
            await orchestrator.chat(session, project, "hola", CancellationToken())
            self.assertEqual(
                [item["content"] for item in database.load_messages(session)], ["mensaje-antiguo"]
            )
