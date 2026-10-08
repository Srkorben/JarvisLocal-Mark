import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from jarvis_local.budgets import ActionBudget
from jarvis_local.cancellation import CancellationToken
from jarvis_local.database import Database
from jarvis_local.execution import ActionExecutor
from jarvis_local.models import ActionRequest, EmptyArguments, RiskLevel, ToolSpec, ToolStatus
from jarvis_local.policy import PolicyEngine
from jarvis_local.projects import ProjectService
from jarvis_local.tools.registry import ToolRegistry
from tests.helpers import make_settings


class ExecutionTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    def build(self, registry: ToolRegistry, **updates):
        allowed = frozenset(registry.names())
        settings = make_settings(self.root, allowed_tools=allowed, **updates)
        database = Database(settings.database_path)
        policy = PolicyEngine(settings)
        projects = ProjectService(database, policy)
        project = projects.ensure_bootstrap_project("Test", self.root)
        executor = ActionExecutor(
            settings=settings,
            database=database,
            registry=registry,
            policy=policy,
            projects=projects,
        )
        return settings, database, project, executor

    async def test_dry_run_does_not_invoke_handler(self) -> None:
        calls = 0

        def handler(*_):
            nonlocal calls
            calls += 1

        registry = ToolRegistry()
        registry.register(ToolSpec("simulate", "test", EmptyArguments, RiskLevel.OBSERVE, handler, 1))
        settings, database, project, executor = self.build(registry)
        request = ActionRequest(
            tool="simulate",
            arguments={},
            expected_result="sin efectos",
            project_id=project.id,
        )
        result = await executor.execute(
            request,
            cancellation=CancellationToken(),
            budget=ActionBudget(settings.budget_limits()),
            dry_run=True,
        )
        self.assertEqual(result.status, ToolStatus.SIMULATED)
        self.assertEqual(calls, 0)
        self.assertTrue(database.verify_audit_chain()[0])

    async def test_cancelled_action_never_invokes_handler(self) -> None:
        calls = 0

        def handler(*_):
            nonlocal calls
            calls += 1

        registry = ToolRegistry()
        registry.register(ToolSpec("cancel_test", "test", EmptyArguments, RiskLevel.OBSERVE, handler, 1))
        settings, _, project, executor = self.build(registry)
        token = CancellationToken()
        token.cancel("prueba")
        request = ActionRequest(
            tool="cancel_test",
            arguments={},
            expected_result="no ejecutar",
            project_id=project.id,
        )
        result = await executor.execute(
            request,
            cancellation=token,
            budget=ActionBudget(settings.budget_limits()),
        )
        self.assertEqual(result.status, ToolStatus.CANCELLED)
        self.assertEqual(calls, 0)

    async def test_tool_timeout_is_reported(self) -> None:
        async def slow(*_):
            await asyncio.sleep(0.1)

        registry = ToolRegistry()
        registry.register(ToolSpec("slow", "test", EmptyArguments, RiskLevel.OBSERVE, slow, 0.01))
        settings, _, project, executor = self.build(registry)
        request = ActionRequest(
            tool="slow",
            arguments={},
            expected_result="timeout",
            project_id=project.id,
        )
        result = await executor.execute(
            request,
            cancellation=CancellationToken(),
            budget=ActionBudget(settings.budget_limits()),
        )
        self.assertEqual(result.status, ToolStatus.TIMEOUT)

    async def test_sync_timeout_waits_for_cooperative_cleanup(self) -> None:
        cleaned = False

        def slow(context, _arguments):
            nonlocal cleaned
            try:
                while True:
                    context.cancellation.raise_if_cancelled()
                    time.sleep(0.005)
            finally:
                cleaned = True

        registry = ToolRegistry()
        registry.register(
            ToolSpec("slow_sync", "test", EmptyArguments, RiskLevel.OBSERVE, slow, 0.02)
        )
        settings, _, project, executor = self.build(registry)
        result = await executor.execute(
            ActionRequest(
                tool="slow_sync",
                arguments={},
                expected_result="timeout limpio",
                project_id=project.id,
            ),
            cancellation=CancellationToken(),
            budget=ActionBudget(settings.budget_limits()),
        )
        self.assertEqual(result.status, ToolStatus.TIMEOUT)
        self.assertTrue(cleaned)

