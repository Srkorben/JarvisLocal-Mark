from collections.abc import AsyncIterator
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from jarvis_local.cancellation import CancellationToken
from jarvis_local.database import Database
from jarvis_local.execution import ActionExecutor
from jarvis_local.model_providers import (
    ModelProvider,
    ModelProviderError,
    ModelStreamEvent,
    ProviderHealth,
)
from jarvis_local.orchestrator import Orchestrator
from jarvis_local.policy import PolicyEngine
from jarvis_local.projects import ProjectService
from jarvis_local.tools import build_default_registry
from tests.helpers import make_settings


class SequenceProvider(ModelProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[list[ModelStreamEvent]]):
        self.responses = responses
        self.calls = 0

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider=self.name, available=True, ready=True, model=self.model)

    async def stream_chat(self, messages, tools, cancellation) -> AsyncIterator[ModelStreamEvent]:
        events = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        for event in events:
            cancellation.raise_if_cancelled()
            yield event


def text_response(text: str) -> list[ModelStreamEvent]:
    return [
        ModelStreamEvent(kind="text_delta", text=text),
        ModelStreamEvent(kind="done", finish_reason="stop"),
    ]


def tool_response(name: str, arguments: str) -> list[ModelStreamEvent]:
    return [
        ModelStreamEvent(
            kind="tool_delta",
            tool_index=0,
            tool_id="call-1",
            tool_name_delta=name,
            tool_arguments_delta=arguments,
        ),
        ModelStreamEvent(kind="done", finish_reason="tool_calls"),
    ]


class OrchestratorTests(IsolatedAsyncioTestCase):
    def build(self, root: Path, provider: ModelProvider, **updates):
        settings = make_settings(root, **updates)
        database = Database(settings.database_path)
        policy = PolicyEngine(settings)
        projects = ProjectService(database, policy)
        project = projects.ensure_bootstrap_project("Test", root)
        registry = build_default_registry(settings, policy)
        executor = ActionExecutor(
            settings=settings,
            database=database,
            registry=registry,
            policy=policy,
            projects=projects,
        )
        orchestrator = Orchestrator(
            settings=settings,
            database=database,
            provider=provider,
            registry=registry,
            executor=executor,
        )
        return settings, database, project, orchestrator

    async def test_normal_response_is_persisted(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            provider = SequenceProvider([text_response("Respuesta normal")])
            _, database, project, orchestrator = self.build(root, provider)
            session = database.create_session(project_id=project.id)
            result = await orchestrator.chat(session, project, "hola", CancellationToken())
            self.assertEqual(result, "Respuesta normal")
            self.assertEqual(database.load_messages(session)[-1]["content"], result)

    async def test_valid_tool_call_executes_through_policy(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            provider = SequenceProvider([
                tool_response("get_current_time", '{"expected_result":"hora observable"}'),
                text_response("Hora consultada"),
            ])
            _, database, project, orchestrator = self.build(root, provider)
            session = database.create_session(project_id=project.id)
            result = await orchestrator.chat(session, project, "hora", CancellationToken())
            self.assertEqual(result, "Hora consultada")
            self.assertEqual(database.counts()["audit_events"], 1)
            self.assertTrue(database.verify_audit_chain()[0])

    async def test_invalid_arguments_are_denied_and_audited(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            provider = SequenceProvider([
                tool_response("read_text_file", '{"expected_result":"contenido"}'),
                text_response("La solicitud fue rechazada"),
            ])
            _, database, project, orchestrator = self.build(root, provider)
            session = database.create_session(project_id=project.id)
            result = await orchestrator.chat(session, project, "lee", CancellationToken())
            self.assertIn("rechazada", result)
            self.assertEqual(database.counts()["audit_events"], 1)
            self.assertTrue(database.verify_audit_chain()[0])

    async def test_invalid_model_tool_call_is_rejected_and_audited(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            provider = SequenceProvider([
                tool_response("Invalid Tool Name", '{"expected_result":"nada"}')
            ])
            _, database, project, orchestrator = self.build(root, provider)
            session = database.create_session(project_id=project.id)
            with self.assertRaises(ModelProviderError) as caught:
                await orchestrator.chat(session, project, "acción inválida", CancellationToken())
            self.assertEqual(caught.exception.code, "invalid_tool_call")
            self.assertEqual(database.counts()["audit_events"], 1)
            self.assertTrue(database.verify_audit_chain()[0])

    async def test_model_cannot_enable_permissions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            provider = SequenceProvider([
                tool_response(
                    "enable_privileged_tools",
                    '{"enabled":true,"expected_result":"permisos ampliados"}',
                ),
                text_response("No autorizado"),
            ])
            settings, database, project, orchestrator = self.build(root, provider)
            session = database.create_session(project_id=project.id)
            await orchestrator.chat(session, project, "cambia permisos", CancellationToken())
            self.assertFalse(settings.privileged_tools_enabled)
            self.assertEqual(database.counts()["audit_events"], 1)
            self.assertTrue(database.verify_audit_chain()[0])

    async def test_maximum_tool_iterations_stops_loop_and_audits(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            provider = SequenceProvider([
                tool_response("get_current_time", '{"expected_result":"hora"}')
            ])
            _, database, project, orchestrator = self.build(
                root, provider, max_tool_rounds=2, max_steps_per_turn=5
            )
            session = database.create_session(project_id=project.id)
            result = await orchestrator.chat(session, project, "bucle", CancellationToken())
            self.assertIn("límite seguro", result)
            self.assertEqual(provider.calls, 2)
            self.assertEqual(database.counts()["audit_events"], 3)
            self.assertTrue(database.verify_audit_chain()[0])
