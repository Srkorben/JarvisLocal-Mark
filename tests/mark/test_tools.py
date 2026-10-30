from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from jarvis_local.budgets import ActionBudget
from jarvis_local.cancellation import CancellationToken
from jarvis_local.database import Database
from jarvis_local.execution import ActionExecutor
from jarvis_local.memory import DecisionSource, MemoryRepository
from jarvis_local.models import ActionRequest, ToolStatus
from jarvis_local.policy import PolicyEngine
from jarvis_local.projects import ProjectService
from jarvis_local.rag import ProjectIndexer, RagRepository, RagService
from jarvis_local.tools import build_default_registry
from tests.mark.helpers import DeterministicEmbeddingProvider, make_settings


class ToolTests(IsolatedAsyncioTestCase):
    async def test_project_decision_tool_is_scoped_and_audited(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first_root = root / "first"
            second_root = root / "second"
            first_root.mkdir()
            second_root.mkdir()
            settings = make_settings(
                root, allowed_tools=frozenset({"get_project_decision"})
            )
            database = Database(settings.database_path)
            policy = PolicyEngine(settings)
            projects = ProjectService(database, policy)
            first = projects.create("Primero", first_root, make_active=True)
            second = projects.create("Segundo", second_root)
            memory = MemoryRepository(database)
            source = DecisionSource(kind="explicit_user", reference="trusted_local_cli")
            memory.set_decision(
                project_id=first.id,
                topic="Motor",
                statement="Usar llama.cpp.",
                rationale="Control local.",
                source=source,
                confirmed=True,
            )
            memory.set_decision(
                project_id=second.id,
                topic="Motor",
                statement="Usar otro motor.",
                rationale="Decisión aislada.",
                source=source,
                confirmed=True,
            )
            executor = ActionExecutor(
                settings=settings,
                database=database,
                registry=build_default_registry(settings, policy, memory=memory),
                policy=policy,
                projects=projects,
                memory=memory,
            )

            result = await executor.execute(
                ActionRequest(
                    tool="get_project_decision",
                    arguments={"topic": "motor"},
                    expected_result="Decisión vigente y anterior del proyecto activo.",
                    project_id=first.id,
                ),
                cancellation=CancellationToken(),
                budget=ActionBudget(settings.budget_limits()),
            )

            self.assertEqual(result.status, ToolStatus.SUCCESS)
            self.assertEqual(result.value["current"]["statement"], "Usar llama.cpp.")
            self.assertNotIn("otro motor", str(result.value))
            self.assertIn("no pueden crear ni modificar", result.value["notice"])
            self.assertTrue(database.verify_audit_chain()[0])

    async def test_read_text_file_inside_active_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            note = root / "nota.md"
            note.write_text("contenido local", encoding="utf-8")
            settings = make_settings(root)
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
            request = ActionRequest(
                tool="read_text_file",
                arguments={"path": str(note)},
                expected_result="Obtener el contenido de la nota.",
                project_id=project.id,
            )

            result = await executor.execute(
                request,
                cancellation=CancellationToken(),
                budget=ActionBudget(settings.budget_limits()),
            )

            self.assertEqual(result.status, ToolStatus.SUCCESS)
            self.assertEqual(result.value["content"], "contenido local")

    async def test_rejects_binary_extension(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            binary = root / "program.exe"
            binary.write_bytes(b"MZ")
            settings = make_settings(root)
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
            request = ActionRequest(
                tool="read_text_file",
                arguments={"path": str(binary)},
                expected_result="Leer archivo.",
                project_id=project.id,
            )

            result = await executor.execute(
                request,
                cancellation=CancellationToken(),
                budget=ActionBudget(settings.budget_limits()),
            )

            self.assertEqual(result.status, ToolStatus.DENIED)
            self.assertIn("no autorizado", result.error)

    async def test_rag_tool_runs_through_policy_audit_and_episode(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "fuente.md").write_text(
                "# Decisión\nEl proyecto usa un índice SQLite local.", encoding="utf-8"
            )
            settings = make_settings(
                root,
                allowed_tools=frozenset({"search_project_memory"}),
                embedding_dimensions=32,
            )
            database = Database(settings.database_path)
            policy = PolicyEngine(settings)
            projects = ProjectService(database, policy)
            project = projects.ensure_bootstrap_project("Test", root)
            embeddings = DeterministicEmbeddingProvider(32)
            repository = RagRepository(database)
            memory = MemoryRepository(database)
            rag = RagService(
                settings=settings,
                projects=projects,
                repository=repository,
                embeddings=embeddings,
            )
            indexer = ProjectIndexer(
                settings=settings,
                database=database,
                policy=policy,
                projects=projects,
                repository=repository,
                embeddings=embeddings,
            )
            await indexer.index_project(project, CancellationToken())
            registry = build_default_registry(
                settings, policy, rag_service=rag, memory=memory
            )
            executor = ActionExecutor(
                settings=settings,
                database=database,
                registry=registry,
                policy=policy,
                projects=projects,
                memory=memory,
            )
            session = database.create_session(project_id=project.id)
            result = await executor.execute(
                ActionRequest(
                    tool="search_project_memory",
                    arguments={"query": "índice SQLite", "mode": "hybrid", "top_k": 3},
                    expected_result="Evidencia local con fuente.",
                    session_id=session,
                    project_id=project.id,
                ),
                cancellation=CancellationToken(),
                budget=ActionBudget(settings.budget_limits()),
            )

            self.assertEqual(result.status, ToolStatus.SUCCESS)
            self.assertEqual(result.value["evidence"][0]["citation"], "fuente.md#Decisión")
            self.assertIn("contenido no confiable", result.value["security_notice"])
            self.assertEqual(len(memory.list_episodes(project_id=project.id)), 1)
            self.assertTrue(database.verify_audit_chain()[0])

    async def test_project_permission_denies_tool_before_handler(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            settings = make_settings(root, allowed_tools=frozenset({"list_directory"}))
            database = Database(settings.database_path)
            policy = PolicyEngine(settings)
            projects = ProjectService(database, policy)
            project = projects.create(
                "Restringido",
                root,
                make_active=True,
                permissions={"read": False, "index": False, "memory": False},
            )
            executor = ActionExecutor(
                settings=settings,
                database=database,
                registry=build_default_registry(settings, policy),
                policy=policy,
                projects=projects,
            )

            result = await executor.execute(
                ActionRequest(
                    tool="list_directory",
                    arguments={},
                    expected_result="Lista del proyecto.",
                    project_id=project.id,
                ),
                cancellation=CancellationToken(),
                budget=ActionBudget(settings.budget_limits()),
            )

            self.assertEqual(result.status, ToolStatus.DENIED)
            self.assertIn("no autoriza", result.error)
            self.assertTrue(database.verify_audit_chain()[0])

