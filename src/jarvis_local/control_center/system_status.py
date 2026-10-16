from __future__ import annotations

import copy
import ctypes
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from ..config import Settings
from .runtime import ProcessManager


HardwareSnapshot = dict[str, object]


class HardwareReader(Protocol):
    def __call__(self) -> HardwareSnapshot: ...


class SystemStatusMonitor:
    """Vista segura y de bajo coste del núcleo y del hardware local.

    El estado de procesos y presencia se calcula en cada solicitud. Las lecturas
    de hardware, en cambio, se almacenan durante un intervalo corto para evitar
    lanzar ``nvidia-smi`` en cada refresco de la interfaz.
    """

    def __init__(
        self,
        settings: Settings,
        manager: ProcessManager,
        *,
        cache_ttl_seconds: float = 2.0,
        hardware_reader: HardwareReader | None = None,
        clock: Callable[[], float] = time.monotonic,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds debe ser positivo.")
        self.settings = settings
        self.manager = manager
        self.cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        self._reader = hardware_reader or _NativeHardwareReader(command_runner=command_runner)
        self._lock = threading.Lock()
        self._cached_at = float("-inf")
        self._cached_hardware: HardwareSnapshot | None = None

    def snapshot(self, presence: dict[str, object] | None = None) -> dict[str, object]:
        runtime_status = {
            str(item["id"]): item
            for item in self.manager.list_status()
            if item.get("id") in {"chat_runtime", "voice"}
        }
        safe_presence = presence if isinstance(presence, dict) else {}
        hardware = self._hardware_snapshot()
        core = _core_state(runtime_status, safe_presence)
        return {
            "sampled_at": _utc_now(),
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "core": core,
            "model": {
                "provider": self.settings.model_provider,
                "name": self.settings.model,
                "context_tokens": self.settings.context_tokens,
                "gpu_layers": self.settings.llama_gpu_layers,
            },
            "runtimes": {
                "text": _safe_runtime(runtime_status.get("chat_runtime")),
                "voice": _safe_runtime(runtime_status.get("voice")),
            },
            **hardware,
        }

    def _hardware_snapshot(self) -> HardwareSnapshot:
        now = self._clock()
        with self._lock:
            if (
                self._cached_hardware is not None
                and now - self._cached_at < self.cache_ttl_seconds
            ):
                return copy.deepcopy(self._cached_hardware)
            try:
                value = self._reader()
            except Exception:
                value = {
                    "cpu": _unavailable("measurement_failed"),
                    "ram": _unavailable("measurement_failed"),
                    "gpu": _unavailable("measurement_failed"),
                }
            self._cached_hardware = _normalize_hardware(value)
            self._cached_at = now
            return copy.deepcopy(self._cached_hardware)


class _NativeHardwareReader:
    def __init__(
        self,
        *,
        command_runner: Callable[..., subprocess.CompletedProcess[str]],
    ) -> None:
        self._run = command_runner
        self._previous_cpu: tuple[int, int] | None = None
        self._lock = threading.Lock()

    def __call__(self) -> HardwareSnapshot:
        return {
            "cpu": self._cpu(),
            "ram": self._ram(),
            "gpu": _read_nvidia_gpu(self._run),
        }

    def _cpu(self) -> dict[str, object]:
        try:
            sample = _windows_cpu_times() if os.name == "nt" else _proc_cpu_times()
        except (OSError, ValueError):
            return _unavailable("counter_unavailable")
        if sample is None:
            return _unavailable("counter_unavailable")
        with self._lock:
            previous = self._previous_cpu
            self._previous_cpu = sample
        if previous is None:
            return {"available": False, "percent": None, "reason": "warming_up"}
        idle_delta = sample[0] - previous[0]
        total_delta = sample[1] - previous[1]
        if total_delta <= 0:
            return _unavailable("counter_unavailable")
        percent = 100.0 * (1.0 - idle_delta / total_delta)
        return {"available": True, "percent": round(max(0.0, min(100.0, percent)), 1)}

    def _ram(self) -> dict[str, object]:
        try:
            memory = _windows_memory() if os.name == "nt" else _proc_memory()
        except (OSError, ValueError):
            return _unavailable("counter_unavailable")
        if memory is None:
            return _unavailable("counter_unavailable")
        used_bytes, total_bytes = memory
        if total_bytes <= 0:
            return _unavailable("counter_unavailable")
        mib = 1024 * 1024
        return {
            "available": True,
            "used_mib": round(used_bytes / mib),
            "total_mib": round(total_bytes / mib),
            "percent": round(used_bytes * 100.0 / total_bytes, 1),
        }


def _core_state(
    runtimes: dict[str, dict[str, object]], presence: dict[str, object]
) -> dict[str, object]:
    state = presence.get("state") if isinstance(presence.get("state"), str) else "offline"
    active = any(item.get("status") == "running" for item in runtimes.values())
    runtime_error = any(item.get("status") == "error" for item in runtimes.values())
    if state == "error" or (runtime_error and not active):
        value, label = "error", "Error"
    elif state == "cancelling":
        value, label = "cancelling", "Cancelando"
    elif state in {"recording", "transcribing", "processing", "speaking"}:
        value, label = "processing", "Procesando"
    elif state in {"loading", "queued"} or (active and state == "offline"):
        value, label = "initializing", "Inicializando"
    elif active:
        value, label = "available", "Disponible"
    else:
        value, label = "off", "Apagado"
    detail = presence.get("error") if value == "error" else ""
    return {
        "state": value,
        "label": label,
        "presence_state": state,
        "detail": detail if isinstance(detail, str) else "",
    }


def _safe_runtime(item: dict[str, object] | None) -> dict[str, object]:
    if item is None:
        return {"state": "unavailable", "label": "No disponible", "started_at": None}
    state = str(item.get("status", "unavailable"))
    labels = {
        "available": "Detenido",
        "running": "Activo",
        "unavailable": "No disponible",
        "error": "Error",
    }
    return {
        "state": state,
        "label": labels.get(state, "No disponible"),
        "started_at": item.get("started_at") if state == "running" else None,
    }


def _normalize_hardware(value: HardwareSnapshot) -> HardwareSnapshot:
    result: HardwareSnapshot = {}
    for name in ("cpu", "ram", "gpu"):
        metric = value.get(name)
        result[name] = dict(metric) if isinstance(metric, dict) else _unavailable("invalid_data")
    return result


def _unavailable(reason: str) -> dict[str, object]:
    return {"available": False, "reason": reason}


def _read_nvidia_gpu(
    command_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, object]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = command_runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=0.8,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError:
        return _unavailable("nvidia_smi_missing")
    except subprocess.TimeoutExpired:
        return _unavailable("timeout")
    except OSError:
        return _unavailable("query_failed")
    if completed.returncode != 0:
        return _unavailable("query_failed")
    first_line = next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "")
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) != 4:
        return _unavailable("invalid_data")
    try:
        utilization = float(parts[1])
        used_mib = float(parts[2])
        total_mib = float(parts[3])
    except ValueError:
        return _unavailable("invalid_data")
    if total_mib <= 0:
        return _unavailable("invalid_data")
    return {
        "available": True,
        "name": parts[0][:160],
        "utilization_percent": round(max(0.0, min(100.0, utilization)), 1),
        "memory_used_mib": round(max(0.0, used_mib)),
        "memory_total_mib": round(total_mib),
        "memory_percent": round(max(0.0, min(100.0, used_mib * 100.0 / total_mib)), 1),
    }


def _windows_cpu_times() -> tuple[int, int] | None:
    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    idle = FileTime()
    kernel = FileTime()
    user = FileTime()
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    ):
        return None

    def integer(value: FileTime) -> int:
        return (value.high << 32) | value.low

    idle_value = integer(idle)
    return idle_value, integer(kernel) + integer(user)


def _windows_memory() -> tuple[int, int] | None:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_uint32),
            ("memory_load", ctypes.c_uint32),
            ("total_physical", ctypes.c_uint64),
            ("available_physical", ctypes.c_uint64),
            ("total_page_file", ctypes.c_uint64),
            ("available_page_file", ctypes.c_uint64),
            ("total_virtual", ctypes.c_uint64),
            ("available_virtual", ctypes.c_uint64),
            ("available_extended_virtual", ctypes.c_uint64),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.total_physical - status.available_physical, status.total_physical


def _proc_cpu_times(path: Path = Path("/proc/stat")) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    values = path.read_text(encoding="ascii").splitlines()[0].split()
    if not values or values[0] != "cpu" or len(values) < 5:
        return None
    counters = [int(value) for value in values[1:]]
    idle = counters[3] + (counters[4] if len(counters) > 4 else 0)
    return idle, sum(counters)


def _proc_memory(path: Path = Path("/proc/meminfo")) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    values: dict[str, int] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        key, _, raw = line.partition(":")
        if key in {"MemTotal", "MemAvailable"}:
            values[key] = int(raw.strip().split()[0]) * 1024
    if not {"MemTotal", "MemAvailable"}.issubset(values):
        return None
    return values["MemTotal"] - values["MemAvailable"], values["MemTotal"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
