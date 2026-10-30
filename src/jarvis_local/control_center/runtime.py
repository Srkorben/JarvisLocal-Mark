from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .catalog import ToolSpec


class ControlCenterError(RuntimeError):
    code = "control_center_error"
    http_status = 400

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class UnknownToolError(ControlCenterError):
    code = "unknown_tool"
    http_status = 404


class ToolUnavailableError(ControlCenterError):
    code = "tool_unavailable"
    http_status = 409


class ToolConflictError(ControlCenterError):
    code = "tool_conflict"
    http_status = 409


class ConfirmationRequiredError(ControlCenterError):
    code = "confirmation_required"
    http_status = 409


@dataclass(slots=True)
class ProcessRecord:
    process: subprocess.Popen[bytes]
    started_at: str
    last_error: str | None = None


class ProcessManager:
    """Ejecuta exclusivamente ToolSpec predefinidos, nunca comandos del cliente."""

    def __init__(
        self,
        catalog: dict[str, ToolSpec],
        *,
        popen_factory: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        process_terminator: Callable[[subprocess.Popen[bytes]], None] | None = None,
        cooldown_seconds: float = 2.0,
    ) -> None:
        self.catalog = dict(catalog)
        self._popen = popen_factory
        self._process_terminator = process_terminator
        self._cooldown_seconds = cooldown_seconds
        self._records: dict[str, ProcessRecord] = {}
        self._last_launch: dict[str, float] = {}
        self._last_result: dict[str, dict[str, object]] = {}
        self._lock = threading.RLock()

    def _tool(self, tool_id: str) -> ToolSpec:
        try:
            return self.catalog[tool_id]
        except KeyError as exc:
            raise UnknownToolError(f"Herramienta desconocida: {tool_id}") from exc

    def _active_record(self, tool_id: str) -> ProcessRecord | None:
        record = self._records.get(tool_id)
        if record is None:
            return None
        code = record.process.poll()
        if code is None:
            return record
        self._last_result[tool_id] = {
            "outcome": "completed" if code == 0 else "error",
            "exit_code": code,
            "finished_at": _now(),
        }
        del self._records[tool_id]
        return None

    def list_status(self) -> list[dict[str, object]]:
        with self._lock:
            result: list[dict[str, object]] = []
            for tool in self.catalog.values():
                missing = tool.missing_requirements()
                record = self._active_record(tool.id)
                last = self._last_result.get(tool.id, {})
                if missing:
                    status = "unavailable"
                elif record is not None:
                    status = "running"
                elif last.get("outcome") == "error":
                    status = "error"
                else:
                    status = "available"
                result.append(
                    {
                        "id": tool.id,
                        "name": tool.name,
                        "description": tool.description,
                        "category": tool.category,
                        "source": tool.source,
                        "status": status,
                        "missing": list(missing),
                        "confirmation_required": tool.confirmation_required,
                        "stoppable": bool(tool.stoppable and record is not None),
                        "pid": record.process.pid if record is not None else None,
                        "started_at": record.started_at if record is not None else None,
                        "last_result": last or None,
                    }
                )
            return result

    def start(self, tool_id: str, *, confirmed: bool = False) -> dict[str, object]:
        with self._lock:
            tool = self._tool(tool_id)
            missing = tool.missing_requirements()
            if missing:
                raise ToolUnavailableError(
                    f"{tool.name} no está disponible: " + "; ".join(missing)
                )
            if tool.confirmation_required and not confirmed:
                raise ConfirmationRequiredError(
                    f"{tool.name} requiere confirmación local explícita."
                )
            active = self._active_record(tool_id)
            if active is not None:
                return {
                    "outcome": "already_running",
                    "tool_id": tool_id,
                    "pid": active.process.pid,
                }
            now = time.monotonic()
            if now - self._last_launch.get(tool_id, 0.0) < self._cooldown_seconds:
                raise ToolConflictError("La acción acaba de iniciarse; espera un momento.")
            for other_id, other_tool in self.catalog.items():
                if other_id == tool_id:
                    continue
                other_record = self._active_record(other_id)
                if other_record is None:
                    continue
                overlap = set(tool.exclusive_groups).intersection(other_tool.exclusive_groups)
                if overlap:
                    raise ToolConflictError(
                        f"{tool.name} entra en conflicto con {other_tool.name}, que sigue en ejecución."
                    )

            command = [str(tool.target), *tool.arguments]
            creation_flags = 0
            if os.name == "nt" and tool.visible_console:
                creation_flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
            elif os.name == "nt":
                creation_flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            extra: dict[str, object] = {}
            if tool.environment:
                extra["env"] = {**os.environ, **dict(tool.environment)}
            try:
                process = self._popen(
                    command,
                    cwd=str(tool.working_directory),
                    shell=False,
                    creationflags=creation_flags,
                    close_fds=True,
                    stdin=subprocess.DEVNULL if not tool.visible_console else None,
                    stdout=subprocess.DEVNULL if not tool.visible_console else None,
                    stderr=subprocess.DEVNULL if not tool.visible_console else None,
                    **extra,
                )
            except Exception as exc:
                self._last_result[tool_id] = {
                    "outcome": "error",
                    "message": str(exc),
                    "finished_at": _now(),
                }
                raise ToolUnavailableError(f"No se pudo iniciar {tool.name}: {exc}") from exc
            started_at = _now()
            self._records[tool_id] = ProcessRecord(process=process, started_at=started_at)
            self._last_launch[tool_id] = now
            self._last_result[tool_id] = {
                "outcome": "started",
                "started_at": started_at,
            }
            return {
                "outcome": "started",
                "tool_id": tool_id,
                "pid": process.pid,
                "started_at": started_at,
            }

    def stop(self, tool_id: str) -> dict[str, object]:
        with self._lock:
            tool = self._tool(tool_id)
            record = self._active_record(tool_id)
            if record is None:
                return {"outcome": "not_running", "tool_id": tool_id}
            if not tool.stoppable:
                raise ToolConflictError(f"{tool.name} no admite detención desde el panel.")
            pid = record.process.pid
            try:
                if self._process_terminator is not None:
                    self._process_terminator(record.process)
                else:
                    _terminate_process_tree(record.process)
            finally:
                self._records.pop(tool_id, None)
            result = {"outcome": "stopped", "tool_id": tool_id, "pid": pid, "finished_at": _now()}
            self._last_result[tool_id] = result
            return result

    def stop_all(self) -> None:
        """Detiene los procesos propiedad del panel al cerrar la aplicación."""

        with self._lock:
            for tool_id in tuple(self._records):
                tool = self.catalog[tool_id]
                if not tool.stoppable:
                    # Explorer/Notepad pueden continuar siendo útiles después de
                    # cerrar el panel. No debemos cerrar aplicaciones delegadas
                    # que el catálogo declara expresamente no detenibles.
                    continue
                record = self._active_record(tool_id)
                if record is None:
                    continue
                try:
                    if self._process_terminator is not None:
                        self._process_terminator(record.process)
                    else:
                        _terminate_process_tree(record.process)
                finally:
                    self._records.pop(tool_id, None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if completed.returncode != 0 and process.poll() is None:
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
