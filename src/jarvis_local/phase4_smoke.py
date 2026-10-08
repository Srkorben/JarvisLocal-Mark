from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .budgets import ActionBudget
from .cancellation import CancellationToken
from .config import Settings
from .database import Database
from .execution import ActionExecutor
from .models import ActionRequest, ConfirmationReceipt, ConfirmationSource
from .policy import PolicyEngine
from .projects import ProjectService
from .tools import build_default_registry


PHASE4_TOOLS = frozenset(
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


async def run_smoke(config_path: Path) -> dict:
    base_settings = Settings.load(config_path)
    smoke_parent = base_settings.data_dir / "phase4-smoke"
    smoke_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=smoke_parent) as directory:
        scratch = Path(directory).resolve()
        root = scratch / "project"
        root.mkdir()
        settings = base_settings.model_copy(
            update={
                "project_dir": root,
                "data_dir": scratch / "data",
                "database_path": scratch / "data" / "smoke.db",
                "allowed_roots": (scratch,),
                "allowed_tools": PHASE4_TOOLS,
                "allowed_applications": frozenset(),
            }
        )
        database = Database(settings.database_path)
        policy = PolicyEngine(settings)
        projects = ProjectService(database, policy)
        project = projects.create(
            "Phase4Smoke",
            root,
            make_active=True,
            permissions={
                "read": True,
                "index": False,
                "memory": False,
                "open": False,
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

        async def execute(tool: str, arguments: dict, *, confirm: bool = False):
            request = ActionRequest(
                tool=tool,
                arguments=arguments,
                expected_result=f"Resultado verificable de {tool}.",
                intent="Smoke test local controlado de Fase 4.",
                project_id=project.id,
            )

            def confirmation(action, _decision):
                return ConfirmationReceipt(
                    approved=True,
                    source=ConfirmationSource.TRUSTED_LOCAL_UI,
                    request_id=action.request_id,
                    summary="Confirmación local exclusiva del smoke test.",
                )

            return await executor.execute(
                request,
                cancellation=CancellationToken(),
                budget=ActionBudget(settings.budget_limits()),
                confirmation_callback=confirmation if confirm else None,
            )

        note = root / "nota-smoke.md"
        copied = root / "nota-copiada.md"
        moved = root / "archivo" / "nota-movida.md"
        moved.parent.mkdir()
        results = []
        results.append(
            await execute(
                "create_note",
                {"path": str(note), "content": "Evidencia determinista de Fase 4."},
            )
        )
        results.append(
            await execute(
                "find_files", {"query": "nota-smoke", "root": str(root)}
            )
        )
        results.append(
            await execute(
                "copy_file", {"source": str(note), "destination": str(copied)}
            )
        )
        results.append(
            await execute(
                "move_file",
                {"source": str(copied), "destination": str(moved)},
                confirm=True,
            )
        )

        git_available = shutil.which("git") is not None
        if git_available:
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "config", "user.name", "Jarvis Smoke"],
                check=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(root), "config", "user.email",
                    "jarvis-smoke@example.invalid",
                ],
                check=True,
            )
            subprocess.run(["git", "-C", str(root), "add", "nota-smoke.md"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-q", "-m", "Smoke inicial"],
                check=True,
            )
            note.write_text("Evidencia actualizada.", encoding="utf-8")
            results.append(await execute("git_status", {"repository_path": str(root)}))
            results.append(
                await execute(
                    "git_log", {"repository_path": str(root), "max_entries": 3}
                )
            )

        valid_audit, audit_errors = database.verify_audit_chain()
        payload = {
            "operations": [
                {
                    "status": result.status.value,
                    "verification": (
                        None
                        if result.verification is None
                        else result.verification.model_dump(mode="json")
                    ),
                    "rollback_reference": result.rollback_reference,
                }
                for result in results
            ],
            "files": {
                "note_exists": note.is_file(),
                "copy_source_absent_after_move": not copied.exists(),
                "moved_exists": moved.is_file(),
            },
            "git_available": git_available,
            "audit_valid": valid_audit,
            "audit_errors": audit_errors,
        }
        payload["passed"] = (
            all(result.ok for result in results)
            and all(
                result.verification is None or result.verification.success is not False
                for result in results
            )
            and all(payload["files"].values())
            and valid_audit
        )
        return payload


async def async_main() -> int:
    root = Path(__file__).resolve().parents[2]
    result = await run_smoke(root / "config" / "jarvis.toml")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())

