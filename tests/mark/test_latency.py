import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase

from jarvis_local.cancellation import CancellationToken
from jarvis_local.database import Database
from jarvis_local.execution import ActionExecutor
from jarvis_local.latency import LatencyLog, TurnTrace
from jarvis_local.model_providers import ModelStreamEvent
from jarvis_local.orchestrator import Orchestrator
from jarvis_local.policy import PolicyEngine
from jarvis_local.projects import ProjectService
from jarvis_local.tools import build_default_registry
from tests.mark.helpers import make_settings
from tests.mark.test_orchestrator import SequenceProvider, text_response, tool_response


SECRET_TEXT = "texto-privado-que-no-debe-registrarse"
# Misma lista blanca que config/jarvis.toml: el filtrado depende de los permisos
# del proyecto, no de una lista recortada.
PRODUCTION_ALLOWED_TOOLS = frozenset(
    {
        "get_current_time", "list_directory", "search_files", "read_text_file",
        "get_project_context", "search_project_memory", "get_recent_project_activity",
        "get_project_decision", "get_user_profile", "find_files", "open_file",
        "open_folder", "open_project", "start_application", "git_status", "git_log",
        "create_note", "copy_file", "move_file",
    }
)


class LatencyLogTests(TestCase):
    def test_records_timings_without_content(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "logs" / "latency.jsonl"
            trace = TurnTrace(interface="text")
            trace.mark("first_token")
            trace.mark("first_token")
            round_record = trace.add_round(
                number=1,
                first_token_seconds=0.5,
                total_seconds=2.0,
                prompt_tokens=100,
                completion_tokens=40,
                tokens_per_second=20.0,
                provider_metrics={
                    "prompt_n": 12,
                    "predicted_per_second": 33.3,
                    "content": SECRET_TEXT,
                },
                tool_calls=1,
            )
            trace.add_tool(round_record, name="get_current_time", status="success", seconds=0.01)
            LatencyLog(path).write(trace)
            raw = path.read_text(encoding="utf-8")
            record = json.loads(raw)
            self.assertNotIn(SECRET_TEXT, raw)
            self.assertEqual(list(record["stages"]), ["first_token"])
            self.assertEqual(record["rounds"][0]["server_prompt_n"], 12.0)
            self.assertEqual(record["rounds"][0]["tools"][0]["name"], "get_current_time")

    def test_log_failure_never_raises(self) -> None:
        with TemporaryDirectory() as directory:
            blocker = Path(directory) / "file"
            blocker.write_text("x", encoding="utf-8")
            LatencyLog(blocker / "sub" / "latency.jsonl").write(TurnTrace(interface="text"))


class OrchestratorLatencyTests(IsolatedAsyncioTestCase):
    def build(self, root: Path, provider, *, permissions=None):
        settings = make_settings(root, allowed_tools=PRODUCTION_ALLOWED_TOOLS)
        database = Database(settings.database_path)
        policy = PolicyEngine(settings)
        projects = ProjectService(database, policy)
        project = projects.ensure_bootstrap_project("Test", root)
        for permission, enabled in (permissions or {}).items():
            project = projects.set_permission(project.id, permission, enabled)
        registry = build_default_registry(settings, policy, projects=projects)
        executor = ActionExecutor(
            settings=settings, database=database, registry=registry, policy=policy, projects=projects
        )
        log_path = root / "latency.jsonl"
        orchestrator = Orchestrator(
            settings=settings,
            database=database,
            provider=provider,
            registry=registry,
            executor=executor,
            latency_log=LatencyLog(log_path),
        )
        return orchestrator, database, project, log_path

    async def test_exposes_only_tools_the_project_may_use(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            captured: list[list[str]] = []

            class CapturingProvider(SequenceProvider):
                async def stream_chat(self, messages, tools, cancellation):
                    captured.append([tool["function"]["name"] for tool in tools])
                    async for event in super().stream_chat(messages, tools, cancellation):
                        yield event

            provider = CapturingProvider([text_response("Hola.")])
            orchestrator, database, project, _ = self.build(root, provider)
            session = database.create_session(project_id=project.id)
            await orchestrator.chat(session, project, "hola", CancellationToken())
            exposed = set(captured[0])
            # Por defecto open/execute/write están denegados: esas herramientas
            # serían rechazadas siempre por la política y no se ofrecen.
            for denied in ("open_file", "start_application", "create_note", "copy_file", "move_file"):
                self.assertNotIn(denied, exposed)
            for allowed in ("get_current_time", "list_directory", "git_status", "find_files"):
                self.assertIn(allowed, exposed)

    async def test_granting_permission_exposes_the_tool(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            seen: list[set[str]] = []

            class CapturingProvider(SequenceProvider):
                async def stream_chat(self, messages, tools, cancellation):
                    seen.append({tool["function"]["name"] for tool in tools})
                    async for event in super().stream_chat(messages, tools, cancellation):
                        yield event

            orchestrator, database, project, _ = self.build(
                root, CapturingProvider([text_response("Listo.")]), permissions={"write": True}
            )
            await orchestrator.chat(
                database.create_session(project_id=project.id), project, "nota", CancellationToken()
            )
            self.assertIn("create_note", seen[0])
            self.assertNotIn("start_application", seen[0])

    async def test_writes_round_and_tool_timings_without_text(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            provider = SequenceProvider(
                [
                    tool_response(
                        "get_current_time",
                        '{"expected_result":"hora local"}',
                    ),
                    [
                        ModelStreamEvent(kind="text_delta", text="Son las "),
                        ModelStreamEvent(kind="text_delta", text="diez."),
                        ModelStreamEvent(
                            kind="done",
                            finish_reason="stop",
                            provider_metrics={"prompt_n": 7, "predicted_per_second": 41.0},
                        ),
                    ],
                ]
            )
            orchestrator, database, project, log_path = self.build(root, provider)
            session = database.create_session(project_id=project.id)
            await orchestrator.chat(session, project, SECRET_TEXT, CancellationToken())
            raw = log_path.read_text(encoding="utf-8")
            self.assertNotIn(SECRET_TEXT, raw)
            self.assertNotIn("Son las", raw)
            record = json.loads(raw)
            self.assertEqual(len(record["rounds"]), 2)
            self.assertEqual(record["rounds"][0]["tools"][0]["name"], "get_current_time")
            self.assertEqual(record["rounds"][0]["tools"][0]["status"], "success")
            self.assertEqual(record["rounds"][1]["server_prompt_n"], 7.0)
            for stage in ("context_ready", "first_token", "llm_done"):
                self.assertIn(stage, record["stages"])
            self.assertLessEqual(record["stages"]["context_ready"], record["stages"]["first_token"])
            self.assertGreater(record["tools_registered"], record["tools_exposed"])

    async def test_external_trace_is_left_to_the_caller(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            orchestrator, database, project, log_path = self.build(
                root, SequenceProvider([text_response("Hola.")])
            )
            trace = TurnTrace(interface="push_to_talk")
            await orchestrator.chat(
                database.create_session(project_id=project.id),
                project,
                "hola",
                CancellationToken(),
                trace=trace,
            )
            self.assertFalse(log_path.exists())
            self.assertIn("llm_done", trace.stages)
