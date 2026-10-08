import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from jarvis_local.budgets import ActionBudget
from jarvis_local.cancellation import CancellationToken
from jarvis_local.database import Database
from jarvis_local.execution import ActionExecutor
from jarvis_local.models import (
    ActionRequest,
    ConfirmationReceipt,
    ConfirmationSource,
    ToolStatus,
)
from jarvis_local.policy import PolicyEngine
from jarvis_local.projects import ProjectService
from jarvis_local.tools import build_default_registry
from tests.helpers import make_settings


TOOL_NAMES = frozenset(
    {
        "find_files",
        "open_file",
        "open_folder",
        "open_project",
        "start_application",
        "git_status",
        "git_log",
        "create_note",
        "copy_file",
        "move_file",
    }
)


class CancelOnCheck(CancellationToken):
    def __init__(self, cancel_on: int):
        super().__init__()
        self.cancel_on = cancel_on
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1
        if self.checks == self.cancel_on:
            self.cancel("Cancelación inyectada durante la operación.")
        super().raise_if_cancelled()


class DeterministicToolTests(IsolatedAsyncioTestCase):
    def build(
        self,
        base: Path,
        *,
        permissions: dict[str, bool] | None = None,
        **settings_updates,
    ):
        root = base / "project"
        root.mkdir()
        settings = make_settings(
            root,
            data_dir=base / "data",
            database_path=base / "data" / "tools.db",
            allowed_roots=(base,),
            allowed_tools=TOOL_NAMES,
            **settings_updates,
        )
        database = Database(settings.database_path)
        policy = PolicyEngine(settings)
        projects = ProjectService(database, policy)
        project = projects.create(
            "Sintético",
            root,
            make_active=True,
            permissions=permissions
            or {
                "read": True,
                "index": True,
                "memory": True,
                "open": True,
                "execute": False,
                "write": True,
            },
        )
        registry = build_default_registry(settings, policy, projects=projects)
        executor = ActionExecutor(
            settings=settings,
            database=database,
            registry=registry,
            policy=policy,
            projects=projects,
        )
        return settings, database, projects, project, executor

    async def execute(self, settings, executor, project, tool, arguments, *, confirm=False, token=None):
        request = ActionRequest(
            tool=tool,
            arguments=arguments,
            expected_result="Resultado verificable de prueba.",
            project_id=project.id,
        )

        def confirmation(action, _decision):
            return ConfirmationReceipt(
                approved=True,
                source=ConfirmationSource.TRUSTED_LOCAL_UI,
                request_id=action.request_id,
                summary="Confirmación local de prueba.",
            )

        return await executor.execute(
            request,
            cancellation=token or CancellationToken(),
            budget=ActionBudget(settings.budget_limits()),
            confirmation_callback=confirmation if confirm else None,
        )

    async def test_find_files_is_scoped_and_skips_generated_directories(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            settings, database, _, project, executor = self.build(base)
            root = Path(project.root_path)
            (root / "informe-final.md").write_text("contenido", encoding="utf-8")
            (root / ".venv-old").mkdir()
            (root / ".venv-old" / "informe-oculto.md").write_text("oculto", encoding="utf-8")

            result = await self.execute(
                settings, executor, project, "find_files", {"query": "informe"}
            )

            self.assertEqual(result.status, ToolStatus.SUCCESS)
            self.assertEqual(
                [item["relative_path"] for item in result.value["results"]],
                ["informe-final.md"],
            )
            self.assertTrue(database.verify_audit_chain()[0])

    async def test_outside_cross_project_and_symlink_paths_are_denied(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            settings, _, projects, project, executor = self.build(base)
            other_root = base / "other"
            other_root.mkdir()
            other = projects.create("Otro", other_root)
            secret = other_root / "secreto.txt"
            secret.write_text("secreto", encoding="utf-8")

            crossed = await self.execute(
                settings,
                executor,
                project,
                "find_files",
                {"query": "secreto", "root": str(other_root)},
            )
            self.assertEqual(crossed.status, ToolStatus.DENIED)

            link = Path(project.root_path) / "enlace.txt"
            try:
                link.symlink_to(secret)
            except OSError as exc:
                self.skipTest(f"No se pudo crear symlink: {exc}")
            linked = await self.execute(
                settings,
                executor,
                project,
                "open_file",
                {"path": str(link)},
            )
            self.assertEqual(linked.status, ToolStatus.DENIED)
            self.assertNotEqual(project.id, other.id)

    async def test_create_copy_and_move_have_verification_and_no_overwrite(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            settings, database, _, project, executor = self.build(base)
            root = Path(project.root_path)
            note = root / "nota.md"
            copied = root / "copia.md"
            moved = root / "movida.md"

            created = await self.execute(
                settings,
                executor,
                project,
                "create_note",
                {"path": str(note), "content": "Nota local verificable."},
            )
            duplicate = await self.execute(
                settings,
                executor,
                project,
                "create_note",
                {"path": str(note), "content": "No sobrescribir."},
            )
            copied_result = await self.execute(
                settings,
                executor,
                project,
                "copy_file",
                {"source": str(note), "destination": str(copied)},
            )
            occupied = await self.execute(
                settings,
                executor,
                project,
                "copy_file",
                {"source": str(note), "destination": str(copied)},
            )
            unconfirmed = await self.execute(
                settings,
                executor,
                project,
                "move_file",
                {"source": str(copied), "destination": str(moved)},
            )
            moved_result = await self.execute(
                settings,
                executor,
                project,
                "move_file",
                {"source": str(copied), "destination": str(moved)},
                confirm=True,
            )

            self.assertEqual(created.status, ToolStatus.SUCCESS)
            self.assertTrue(created.verification.success)
            self.assertIsNotNone(created.rollback_reference)
            self.assertEqual(duplicate.status, ToolStatus.ERROR)
            self.assertEqual(copied_result.status, ToolStatus.SUCCESS)
            self.assertTrue(copied_result.verification.success)
            self.assertEqual(occupied.status, ToolStatus.ERROR)
            self.assertEqual(unconfirmed.status, ToolStatus.DENIED)
            self.assertEqual(moved_result.status, ToolStatus.SUCCESS)
            self.assertTrue(moved_result.verification.success)
            self.assertFalse(copied.exists())
            self.assertEqual(moved.read_text(encoding="utf-8"), "Nota local verificable.")
            self.assertTrue(database.verify_audit_chain()[0])

    async def test_write_permission_and_cancellation_are_enforced(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            permissions = {
                "read": True,
                "index": True,
                "memory": True,
                "open": False,
                "execute": False,
                "write": False,
            }
            settings, _, projects, project, executor = self.build(base, permissions=permissions)
            target = Path(project.root_path) / "denegada.md"
            denied = await self.execute(
                settings,
                executor,
                project,
                "create_note",
                {"path": str(target), "content": "No crear."},
            )
            projects.set_permission(project.id, "write", True)
            token = CancellationToken()
            token.cancel("Prueba antes de escritura.")
            cancelled = await self.execute(
                settings,
                executor,
                project,
                "create_note",
                {"path": str(target), "content": "No crear."},
                token=token,
            )
            self.assertEqual(denied.status, ToolStatus.DENIED)
            self.assertEqual(cancelled.status, ToolStatus.CANCELLED)
            self.assertFalse(target.exists())

    async def test_copy_and_move_rollback_when_cancelled_mid_operation(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            settings, _, _, project, executor = self.build(base)
            root = Path(project.root_path)
            source = root / "grande.bin"
            copied = root / "copia.bin"
            moved = root / "movido.bin"
            source.write_bytes(b"x" * (2 * 1024 * 1024))

            cancelled_copy = await self.execute(
                settings,
                executor,
                project,
                "copy_file",
                {"source": str(source), "destination": str(copied)},
                token=CancelOnCheck(3),
            )
            cancelled_move = await self.execute(
                settings,
                executor,
                project,
                "move_file",
                {"source": str(source), "destination": str(moved)},
                confirm=True,
                token=CancelOnCheck(4),
            )

            self.assertEqual(cancelled_copy.status, ToolStatus.CANCELLED)
            self.assertFalse(copied.exists())
            self.assertEqual(cancelled_move.status, ToolStatus.CANCELLED)
            self.assertTrue(source.exists())
            self.assertFalse(moved.exists())

    async def test_malformed_tool_arguments_are_denied(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            settings, _, _, project, executor = self.build(base)
            result = await self.execute(
                settings,
                executor,
                project,
                "copy_file",
                {"source": str(Path(project.root_path) / "x"), "unexpected": True},
            )
            self.assertEqual(result.status, ToolStatus.DENIED)
            self.assertIn("validation", result.error.casefold())

    async def test_unlisted_application_and_missing_source_are_denied_or_reported(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            permissions = {
                "read": True,
                "index": True,
                "memory": True,
                "open": True,
                "execute": True,
                "write": True,
            }
            settings, _, _, project, executor = self.build(base, permissions=permissions)
            missing = Path(project.root_path) / "no-existe.txt"
            application = Path(project.root_path) / "no-autorizada.exe"
            application.write_bytes(b"MZ")
            app_result = await self.execute(
                settings,
                executor,
                project,
                "start_application",
                {"application_path": str(application)},
            )
            copy_result = await self.execute(
                settings,
                executor,
                project,
                "copy_file",
                {"source": str(missing), "destination": str(Path(project.root_path) / "x.txt")},
            )
            self.assertEqual(app_result.status, ToolStatus.DENIED)
            self.assertEqual(copy_result.status, ToolStatus.ERROR)

    async def test_allowlisted_application_uses_exact_executable_without_arguments(self) -> None:
        class FakeProcess:
            pid = 4242
            returncode = None

            def terminate(self):
                self.returncode = 0

            def kill(self):
                self.returncode = -1

            async def wait(self):
                return self.returncode

        with TemporaryDirectory() as directory:
            base = Path(directory)
            application_dir = base / "apps"
            application_dir.mkdir()
            application = application_dir / "permitida.exe"
            application.write_bytes(b"MZ")
            permissions = {
                "read": True,
                "index": True,
                "memory": True,
                "open": False,
                "execute": True,
                "write": False,
            }
            settings, _, _, project, executor = self.build(
                base,
                permissions=permissions,
                allowed_applications=frozenset({str(application)}),
            )
            fake = FakeProcess()
            with (
                patch("asyncio.create_subprocess_exec", return_value=fake) as launch,
                patch("jarvis_local.tools.deterministic._pid_exists", return_value=True),
            ):
                result = await self.execute(
                    settings,
                    executor,
                    project,
                    "start_application",
                    {"application_path": str(application)},
                )

            self.assertEqual(result.status, ToolStatus.SUCCESS)
            self.assertTrue(result.verification.success)
            self.assertEqual(launch.call_args.args, (str(application.resolve()),))

    async def test_open_tools_and_project_activation_report_verification_limits(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            settings, _, projects, project, executor = self.build(base)
            root = Path(project.root_path)
            document = root / "documento.txt"
            document.write_text("abrir", encoding="utf-8")
            second_root = base / "second"
            second_root.mkdir()
            second = projects.create(
                "Segundo",
                second_root,
                permissions={"read": True, "open": True},
            )
            with patch("jarvis_local.tools.deterministic._startfile") as dispatch:
                opened_file = await self.execute(
                    settings, executor, project, "open_file", {"path": str(document)}
                )
                opened_folder = await self.execute(
                    settings, executor, project, "open_folder", {"path": str(root)}
                )
                opened_project = await self.execute(
                    settings,
                    executor,
                    project,
                    "open_project",
                    {"target_project_id": second.id},
                )
            self.assertEqual(dispatch.call_count, 3)
            self.assertEqual(opened_file.status, ToolStatus.SUCCESS)
            self.assertIsNone(opened_file.verification.success)
            self.assertEqual(opened_folder.status, ToolStatus.SUCCESS)
            self.assertIsNone(opened_folder.verification.success)
            self.assertEqual(opened_project.status, ToolStatus.SUCCESS)
            self.assertEqual(projects.active().id, second.id)

    async def test_git_status_and_log_use_structured_fixed_commands(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("Git no está disponible.")
        with TemporaryDirectory() as directory:
            base = Path(directory)
            settings, _, _, project, executor = self.build(base)
            root = Path(project.root_path)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Jarvis Test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "jarvis@example.invalid"], check=True)
            (root / "seguimiento.txt").write_text("v1", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "seguimiento.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "Commit sintético"], check=True)
            (root / "seguimiento.txt").write_text("v2", encoding="utf-8")

            status = await self.execute(settings, executor, project, "git_status", {})
            log = await self.execute(
                settings, executor, project, "git_log", {"max_entries": 3}
            )

            self.assertEqual(status.status, ToolStatus.SUCCESS)
            self.assertFalse(status.value["clean"])
            self.assertEqual(status.value["change_count"], 1)
            self.assertEqual(log.status, ToolStatus.SUCCESS)
            self.assertEqual(log.value["commits"][0]["subject"], "Commit sintético")

