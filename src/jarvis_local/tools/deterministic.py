from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from pydantic import Field

from ..config import Settings
from ..models import Reversibility, RiskLevel, StrictModel, ToolSpec, VerificationResult
from ..policy import PolicyEngine, PolicyViolation
from ..projects import ProjectService
from .registry import ToolContext, ToolExecutionOutcome, ToolRegistry


OPENABLE_DOCUMENT_EXTENSIONS = {
    ".csv", ".docx", ".gif", ".jpeg", ".jpg", ".json", ".md", ".pdf",
    ".png", ".pptx", ".rtf", ".svg", ".txt", ".webp", ".xlsx", ".xml",
}
NOTE_EXTENSIONS = {".md", ".txt"}


class FindFilesArguments(StrictModel):
    query: str = Field(min_length=1, max_length=200)
    root: str | None = None
    max_results: int = Field(default=25, ge=1, le=100)
    include_generated: bool = False


class OpenFileArguments(StrictModel):
    path: str = Field(min_length=1)


class OpenFolderArguments(StrictModel):
    path: str = Field(min_length=1)


class OpenProjectArguments(StrictModel):
    target_project_id: str = Field(min_length=1, max_length=100)


class StartApplicationArguments(StrictModel):
    application_path: str = Field(min_length=1)


class GitStatusArguments(StrictModel):
    repository_path: str | None = None
    include_untracked: bool = True


class GitLogArguments(StrictModel):
    repository_path: str | None = None
    max_entries: int = Field(default=10, ge=1, le=50)


class CreateNoteArguments(StrictModel):
    path: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=200_000)


class CopyFileArguments(StrictModel):
    source: str = Field(min_length=1)
    destination: str = Field(min_length=1)


class MoveFileArguments(StrictModel):
    source: str = Field(min_length=1)
    destination: str = Field(min_length=1)


def register_deterministic_tools(
    registry: ToolRegistry,
    *,
    settings: Settings,
    policy: PolicyEngine,
    projects: ProjectService,
) -> None:
    timeout = settings.default_tool_timeout_seconds

    def find_files(context: ToolContext, arguments: FindFilesArguments) -> dict[str, Any]:
        root = policy.validate_path(
            arguments.root or context.project_root,
            project_root=context.project_root,
        )
        if not root.is_dir():
            raise NotADirectoryError(root)
        query = arguments.query.casefold().strip()
        results: list[dict[str, Any]] = []
        for current, directories, files in os.walk(root):
            context.cancellation.raise_if_cancelled()
            current_path = Path(current)
            safe_directories: list[str] = []
            for directory in sorted(directories, key=str.casefold):
                folded = directory.casefold()
                if not arguments.include_generated and any(
                    fnmatchcase(folded, pattern)
                    for pattern in settings.rag_excluded_path_parts
                ):
                    continue
                try:
                    candidate = policy.validate_path(
                        current_path / directory,
                        project_root=context.project_root,
                    )
                except PolicyViolation:
                    continue
                if candidate.is_dir():
                    safe_directories.append(directory)
            directories[:] = safe_directories
            for name in sorted(files, key=str.casefold):
                context.cancellation.raise_if_cancelled()
                if query not in name.casefold():
                    continue
                try:
                    path = policy.validate_path(
                        current_path / name,
                        project_root=context.project_root,
                    )
                except PolicyViolation:
                    continue
                if not path.is_file():
                    continue
                stat = path.stat()
                results.append(
                    {
                        "path": str(path),
                        "relative_path": path.relative_to(context.project_root).as_posix(),
                        "size_bytes": stat.st_size,
                        "modified_ns": stat.st_mtime_ns,
                    }
                )
                if len(results) >= arguments.max_results:
                    return {
                        "root": str(root),
                        "query": arguments.query,
                        "results": results,
                        "truncated": True,
                    }
        return {
            "root": str(root),
            "query": arguments.query,
            "results": results,
            "truncated": False,
        }

    def open_file(context: ToolContext, arguments: OpenFileArguments) -> dict[str, Any]:
        path = policy.validate_path(arguments.path, project_root=context.project_root)
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.suffix.casefold() not in OPENABLE_DOCUMENT_EXTENSIONS:
            raise PolicyViolation(
                f"Tipo de documento no autorizado para apertura asociada: {path.suffix}"
            )
        before = _identity(path)
        context.cancellation.raise_if_cancelled()
        _startfile(path)
        context.cancellation.raise_if_cancelled()
        return {
            "path": str(path),
            "dispatch": "accepted_by_windows_shell",
            "source_identity": before,
            "application_state_verified": False,
        }

    def open_folder(context: ToolContext, arguments: OpenFolderArguments) -> dict[str, Any]:
        path = policy.validate_path(arguments.path, project_root=context.project_root)
        if not path.is_dir():
            raise NotADirectoryError(path)
        context.cancellation.raise_if_cancelled()
        _startfile(path)
        context.cancellation.raise_if_cancelled()
        return {
            "path": str(path),
            "dispatch": "accepted_by_windows_shell",
            "explorer_window_verified": False,
        }

    def open_project(
        context: ToolContext, arguments: OpenProjectArguments
    ) -> ToolExecutionOutcome:
        target = projects.validate_action_project(arguments.target_project_id)
        try:
            projects.require_permission(target, "read")
            projects.require_permission(target, "open")
        except PermissionError as exc:
            raise PolicyViolation(str(exc)) from exc
        root = policy.validate_path(target.root_path, project_root=Path(target.root_path))
        previous = projects.active()
        context.cancellation.raise_if_cancelled()
        projects.activate(target.id)
        try:
            context.cancellation.raise_if_cancelled()
            _startfile(root)
            context.cancellation.raise_if_cancelled()
        except BaseException:
            if previous is not None:
                projects.activate(previous.id)
            raise
        return ToolExecutionOutcome(
            value={
                "project_id": target.id,
                "name": target.name,
                "root_path": str(root),
                "active": True,
                "dispatch": "accepted_by_windows_shell",
                "takes_effect_for_conversation": "next_turn",
            },
            rollback_reference=json.dumps(
                {"operation": "activate_project", "project_id": None if previous is None else previous.id},
                ensure_ascii=False,
            ),
        )

    def verify_open_project(
        context: ToolContext, arguments: OpenProjectArguments, value: dict[str, Any]
    ) -> VerificationResult:
        active = projects.active()
        success = (
            active is not None
            and active.id == arguments.target_project_id
            and value.get("project_id") == arguments.target_project_id
            and Path(value["root_path"]).is_dir()
        )
        return VerificationResult(
            attempted=True,
            success=success,
            details=(
                "Proyecto activo confirmado en SQLite; la ventana de Explorer no se inspecciona."
            ),
        )

    async def start_application(
        context: ToolContext, arguments: StartApplicationArguments
    ) -> dict[str, Any]:
        executable = Path(arguments.application_path)
        if not executable.is_absolute() or not executable.is_file():
            raise FileNotFoundError(executable)
        if executable.suffix.casefold() != ".exe":
            raise PolicyViolation("Solo se admiten ejecutables .exe incluidos expresamente en allowlist.")
        context.cancellation.raise_if_cancelled()
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                str(executable),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=flags,
            )
            await _wait_or_cancel(context, 0.35)
            if process.returncode is not None:
                raise RuntimeError(
                    f"La aplicación terminó durante el arranque con código {process.returncode}."
                )
            return {
                "application_path": str(executable.resolve()),
                "pid": process.pid,
                "running": True,
            }
        except BaseException:
            if process is not None and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            raise

    async def git_status(context: ToolContext, arguments: GitStatusArguments) -> dict[str, Any]:
        root = policy.validate_path(
            arguments.repository_path or context.project_root,
            project_root=context.project_root,
        )
        _require_git_repository(root)
        git = _git_executable()
        untracked = "all" if arguments.include_untracked else "no"
        completed = await _run_process(
            context,
            git,
            "-C",
            str(root),
            "-c",
            "color.ui=false",
            "status",
            "--porcelain=v2",
            "--branch",
            f"--untracked-files={untracked}",
        )
        lines = completed["stdout"].splitlines()
        changes = [line for line in lines if not line.startswith("#")]
        branch = next(
            (line.removeprefix("# branch.head ") for line in lines if line.startswith("# branch.head ")),
            None,
        )
        return {
            "repository_path": str(root),
            "branch": branch,
            "clean": not changes,
            "change_count": len(changes),
            "changes": changes[:200],
        }

    async def git_log(context: ToolContext, arguments: GitLogArguments) -> dict[str, Any]:
        root = policy.validate_path(
            arguments.repository_path or context.project_root,
            project_root=context.project_root,
        )
        _require_git_repository(root)
        completed = await _run_process(
            context,
            _git_executable(),
            "-C",
            str(root),
            "-c",
            "color.ui=false",
            "log",
            f"--max-count={arguments.max_entries}",
            "--date=iso-strict",
            "--pretty=format:%H%x1f%h%x1f%aI%x1f%an%x1f%s",
        )
        commits = []
        for line in completed["stdout"].splitlines():
            parts = line.split("\x1f", 4)
            if len(parts) == 5:
                commits.append(
                    {
                        "commit": parts[0],
                        "short_commit": parts[1],
                        "authored_at": parts[2],
                        "author": parts[3],
                        "subject": parts[4],
                    }
                )
        return {"repository_path": str(root), "commits": commits}

    def create_note(
        context: ToolContext, arguments: CreateNoteArguments
    ) -> ToolExecutionOutcome:
        path = policy.validate_path(arguments.path, project_root=context.project_root)
        if path.suffix.casefold() not in NOTE_EXTENSIONS:
            raise PolicyViolation("Las notas nuevas deben usar extensión .md o .txt.")
        if not path.parent.is_dir():
            raise FileNotFoundError(f"No existe la carpeta destino: {path.parent}")
        payload = arguments.content.encode("utf-8")
        if len(payload) > settings.max_file_operation_bytes:
            raise PolicyViolation("La nota excede el límite de escritura configurado.")
        context.cancellation.raise_if_cancelled()
        created = False
        try:
            with path.open("xb") as handle:
                created = True
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            context.cancellation.raise_if_cancelled()
            digest = hashlib.sha256(payload).hexdigest()
            return ToolExecutionOutcome(
                value={
                    "path": str(path),
                    "created": True,
                    "size_bytes": len(payload),
                    "sha256": digest,
                },
                rollback_reference=json.dumps(
                    {"operation": "delete_created_file", "path": str(path), "sha256": digest},
                    ensure_ascii=False,
                ),
            )
        except BaseException:
            if created:
                path.unlink(missing_ok=True)
            raise

    def copy_file(
        context: ToolContext, arguments: CopyFileArguments
    ) -> ToolExecutionOutcome:
        source = policy.validate_path(arguments.source, project_root=context.project_root)
        destination = policy.validate_path(
            arguments.destination, project_root=context.project_root
        )
        if source == destination:
            raise ValueError("Origen y destino deben ser distintos.")
        if not source.is_file():
            raise FileNotFoundError(source)
        if not destination.parent.is_dir():
            raise FileNotFoundError(f"No existe la carpeta destino: {destination.parent}")
        size = source.stat().st_size
        if size > settings.max_file_operation_bytes:
            raise PolicyViolation("El archivo excede el límite de copia configurado.")
        created = False
        digest = hashlib.sha256()
        try:
            with source.open("rb") as reader, destination.open("xb") as writer:
                created = True
                source_before = _fstat_identity(reader.fileno())
                while block := reader.read(1024 * 1024):
                    context.cancellation.raise_if_cancelled()
                    writer.write(block)
                    digest.update(block)
                writer.flush()
                os.fsync(writer.fileno())
                source_after = _fstat_identity(reader.fileno())
            if source_before != source_after:
                raise RuntimeError("El archivo origen cambió durante la copia.")
            context.cancellation.raise_if_cancelled()
            expected_hash = digest.hexdigest()
            if destination.stat().st_size != size or _sha256(destination) != expected_hash:
                raise RuntimeError("La verificación de la copia no coincide con el origen.")
            return ToolExecutionOutcome(
                value={
                    "source": str(source),
                    "destination": str(destination),
                    "copied": True,
                    "size_bytes": size,
                    "sha256": expected_hash,
                },
                rollback_reference=json.dumps(
                    {
                        "operation": "delete_copied_file",
                        "path": str(destination),
                        "sha256": expected_hash,
                    },
                    ensure_ascii=False,
                ),
            )
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise

    def move_file(
        context: ToolContext, arguments: MoveFileArguments
    ) -> ToolExecutionOutcome:
        source = policy.validate_path(arguments.source, project_root=context.project_root)
        destination = policy.validate_path(
            arguments.destination, project_root=context.project_root
        )
        if source == destination:
            raise ValueError("Origen y destino deben ser distintos.")
        if not source.is_file():
            raise FileNotFoundError(source)
        if not destination.parent.is_dir():
            raise FileNotFoundError(f"No existe la carpeta destino: {destination.parent}")
        if destination.exists():
            raise FileExistsError(destination)
        source_stat = source.stat()
        if source_stat.st_size > settings.max_file_operation_bytes:
            raise PolicyViolation("El archivo excede el límite de movimiento configurado.")
        if source_stat.st_dev != destination.parent.stat().st_dev:
            raise PolicyViolation("move_file solo admite movimientos dentro del mismo volumen.")
        digest = _sha256(source)
        context.cancellation.raise_if_cancelled()
        moved = False
        try:
            _move_without_overwrite(source, destination)
            moved = True
            context.cancellation.raise_if_cancelled()
            if source.exists() or not destination.is_file():
                raise RuntimeError("El estado posterior del movimiento no es válido.")
            if destination.stat().st_size != source_stat.st_size or _sha256(destination) != digest:
                raise RuntimeError("La identidad del archivo movido no coincide.")
            return ToolExecutionOutcome(
                value={
                    "source": str(source),
                    "destination": str(destination),
                    "moved": True,
                    "size_bytes": source_stat.st_size,
                    "sha256": digest,
                },
                rollback_reference=json.dumps(
                    {
                        "operation": "move_file",
                        "source": str(destination),
                        "destination": str(source),
                        "sha256": digest,
                    },
                    ensure_ascii=False,
                ),
            )
        except BaseException:
            if moved and destination.exists() and not source.exists():
                _move_without_overwrite(destination, source)
            raise

    registry.register(
        ToolSpec(
            "find_files",
            "Localiza archivos por nombre dentro del proyecto activo.",
            FindFilesArguments,
            RiskLevel.OBSERVE,
            find_files,
            timeout,
            path_arguments=("root",),
            required_project_permissions=("read",),
        )
    )
    registry.register(
        ToolSpec(
            "open_file",
            "Solicita a Windows abrir un documento autorizado con su aplicación asociada.",
            OpenFileArguments,
            RiskLevel.REVERSIBLE,
            open_file,
            timeout,
            path_arguments=("path",),
            required_project_permissions=("read", "open"),
            verifier=_verify_open_file,
        )
    )
    registry.register(
        ToolSpec(
            "open_folder",
            "Solicita a Windows abrir una carpeta autorizada en el Explorador.",
            OpenFolderArguments,
            RiskLevel.REVERSIBLE,
            open_folder,
            timeout,
            path_arguments=("path",),
            required_project_permissions=("read", "open"),
            verifier=_verify_open_folder,
        )
    )
    registry.register(
        ToolSpec(
            "open_project",
            "Activa un proyecto registrado y solicita abrir su raíz; el contexto cambia en el turno siguiente.",
            OpenProjectArguments,
            RiskLevel.REVERSIBLE,
            open_project,
            timeout,
            required_project_permissions=("open",),
            verifier=verify_open_project,
        )
    )
    registry.register(
        ToolSpec(
            "start_application",
            "Inicia sin argumentos una aplicación .exe incluida en la allowlist.",
            StartApplicationArguments,
            RiskLevel.REVERSIBLE,
            start_application,
            timeout,
            application_argument="application_path",
            required_project_permissions=("execute",),
            verifier=_verify_application,
        )
    )
    registry.register(
        ToolSpec(
            "git_status",
            "Consulta el estado Git mediante argumentos fijos, sin shell.",
            GitStatusArguments,
            RiskLevel.OBSERVE,
            git_status,
            timeout,
            path_arguments=("repository_path",),
            required_project_permissions=("read",),
        )
    )
    registry.register(
        ToolSpec(
            "git_log",
            "Consulta el historial Git estructurado mediante argumentos fijos, sin shell.",
            GitLogArguments,
            RiskLevel.OBSERVE,
            git_log,
            timeout,
            path_arguments=("repository_path",),
            required_project_permissions=("read",),
        )
    )
    registry.register(
        ToolSpec(
            "create_note",
            "Crea una nota UTF-8 .md o .txt sin sobrescribir archivos existentes.",
            CreateNoteArguments,
            RiskLevel.REVERSIBLE,
            create_note,
            timeout,
            path_arguments=("path",),
            modifies_files=True,
            reversibility=Reversibility.REVERSIBLE,
            required_project_permissions=("write",),
            verifier=_verify_created_file,
        )
    )
    registry.register(
        ToolSpec(
            "copy_file",
            "Copia un archivo dentro del proyecto, sin sobrescribir y verificando SHA-256.",
            CopyFileArguments,
            RiskLevel.REVERSIBLE,
            copy_file,
            timeout,
            path_arguments=("source", "destination"),
            modifies_files=True,
            reversibility=Reversibility.REVERSIBLE,
            required_project_permissions=("read", "write"),
            verifier=_verify_copied_file,
        )
    )
    registry.register(
        ToolSpec(
            "move_file",
            "Mueve un archivo en el mismo volumen sin sobrescribir; siempre requiere confirmación.",
            MoveFileArguments,
            RiskLevel.SENSITIVE,
            move_file,
            timeout,
            path_arguments=("source", "destination"),
            modifies_files=True,
            reversibility=Reversibility.PARTIAL,
            required_project_permissions=("read", "write"),
            verifier=_verify_moved_file,
        )
    )


def _startfile(path: Path) -> None:
    if os.name != "nt" or not hasattr(os, "startfile"):
        raise RuntimeError("La apertura asociada solo está disponible en Windows.")
    os.startfile(str(path))  # type: ignore[attr-defined]


def _identity(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "size": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


def _fstat_identity(file_descriptor: int) -> tuple[int, int, int, int]:
    stat = os.fstat(file_descriptor)
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _move_without_overwrite(source: Path, destination: Path) -> None:
    if os.name == "nt":
        move_file = ctypes.windll.kernel32.MoveFileW
        move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        move_file.restype = ctypes.c_int
        if not move_file(str(source), str(destination)):
            error = ctypes.get_last_error()
            if destination.exists():
                raise FileExistsError(destination)
            raise OSError(error, "MoveFileW falló", str(source), str(destination))
        return
    if destination.exists():
        raise FileExistsError(destination)
    os.rename(source, destination)


def _git_executable() -> str:
    executable = shutil.which("git.exe" if os.name == "nt" else "git")
    if not executable:
        raise FileNotFoundError("Git no está instalado o no aparece en PATH.")
    return str(Path(executable).resolve())


def _require_git_repository(root: Path) -> None:
    if not root.is_dir():
        raise NotADirectoryError(root)
    marker = root / ".git"
    if not marker.exists():
        raise ValueError(f"La ruta no es la raíz de un repositorio Git: {root}")


async def _run_process(context: ToolContext, executable: str, *arguments: str) -> dict[str, Any]:
    context.cancellation.raise_if_cancelled()
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = await asyncio.create_subprocess_exec(
        executable,
        *arguments,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=flags,
    )
    communicate_task = asyncio.create_task(process.communicate())
    cancel_task = asyncio.create_task(context.cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            {communicate_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if cancel_task in done:
            process.terminate()
            await process.wait()
            from ..cancellation import OperationCancelled

            raise OperationCancelled(context.cancellation.reason or "Proceso cancelado.")
        cancel_task.cancel()
        await asyncio.gather(cancel_task, return_exceptions=True)
        stdout, stderr = communicate_task.result()
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise
    finally:
        for task in (communicate_task, cancel_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(communicate_task, cancel_task, return_exceptions=True)
    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")
    if len(stdout_text) > 1_000_000 or len(stderr_text) > 100_000:
        raise RuntimeError("La salida del proceso excedió el límite seguro.")
    if process.returncode != 0:
        raise RuntimeError(
            f"El proceso terminó con código {process.returncode}: {stderr_text.strip()}"
        )
    return {"returncode": process.returncode, "stdout": stdout_text, "stderr": stderr_text}


async def _wait_or_cancel(context: ToolContext, seconds: float) -> None:
    delay = asyncio.create_task(asyncio.sleep(seconds))
    cancel = asyncio.create_task(context.cancellation.wait())
    try:
        done, _ = await asyncio.wait({delay, cancel}, return_when=asyncio.FIRST_COMPLETED)
        if cancel in done:
            from ..cancellation import OperationCancelled

            raise OperationCancelled(context.cancellation.reason or "Arranque cancelado.")
    finally:
        for task in (delay, cancel):
            if not task.done():
                task.cancel()
        await asyncio.gather(delay, cancel, return_exceptions=True)


def _verify_open_file(
    context: ToolContext, _: OpenFileArguments, value: dict[str, Any]
) -> VerificationResult:
    path = Path(value["path"])
    unchanged = path.is_file() and _identity(path) == value["source_identity"]
    return VerificationResult(
        attempted=True,
        success=None if unchanged else False,
        details=(
            "Windows aceptó el despacho y el documento sigue siendo el mismo; "
            "esta fase no inspecciona la ventana de la aplicación."
            if unchanged
            else "El documento cambió o desapareció después del despacho."
        ),
    )


def _verify_open_folder(
    context: ToolContext, _: OpenFolderArguments, value: dict[str, Any]
) -> VerificationResult:
    exists = Path(value["path"]).is_dir()
    return VerificationResult(
        attempted=True,
        success=None if exists else False,
        details=(
            "Windows aceptó el despacho y la carpeta existe; esta fase no inspecciona Explorer."
            if exists
            else "La carpeta ya no existe."
        ),
    )


def _verify_application(
    context: ToolContext, _: StartApplicationArguments, value: dict[str, Any]
) -> VerificationResult:
    pid = int(value["pid"])
    running = _pid_exists(pid)
    return VerificationResult(
        attempted=True,
        success=running,
        details=f"Proceso {pid} {'está activo' if running else 'no está activo'} tras el arranque.",
    )


def _pid_exists(pid: int) -> bool:
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _verify_created_file(
    context: ToolContext, _: CreateNoteArguments, value: dict[str, Any]
) -> VerificationResult:
    path = Path(value["path"])
    success = path.is_file() and path.stat().st_size == value["size_bytes"] and _sha256(
        path
    ) == value["sha256"]
    return VerificationResult(attempted=True, success=success, details="Existencia, tamaño y SHA-256 comprobados.")


def _verify_copied_file(
    context: ToolContext, _: CopyFileArguments, value: dict[str, Any]
) -> VerificationResult:
    source = Path(value["source"])
    destination = Path(value["destination"])
    success = (
        source.is_file()
        and destination.is_file()
        and _sha256(source) == value["sha256"]
        and _sha256(destination) == value["sha256"]
    )
    return VerificationResult(attempted=True, success=success, details="Origen y copia tienen el mismo SHA-256.")


def _verify_moved_file(
    context: ToolContext, _: MoveFileArguments, value: dict[str, Any]
) -> VerificationResult:
    source = Path(value["source"])
    destination = Path(value["destination"])
    success = not source.exists() and destination.is_file() and _sha256(
        destination
    ) == value["sha256"]
    return VerificationResult(attempted=True, success=success, details="Origen ausente y destino verificado por SHA-256.")

