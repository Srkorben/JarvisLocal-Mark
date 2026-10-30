"""Start Ollama in the background when Mark opens and it is not running.

Ollama's own ``ollama serve`` prints its log to a console window; closing that
window stops the engine. Mark launches it hidden and detached instead, so the
user never sees a console and Ollama keeps serving after Mark closes (like
Ollama's tray app does).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

DEFAULT_HOST = "http://127.0.0.1:11434"


def ollama_host(config: Any = None) -> str:
    """Resolve the Ollama URL: config, then ``OLLAMA_HOST``, then default."""
    configured = ""
    try:
        configured = config.engine.ollama.host or ""
    except AttributeError:
        pass
    host = (configured or os.environ.get("OLLAMA_HOST", "") or DEFAULT_HOST).strip()
    if "://" not in host:
        host = f"http://{host}"
    scheme, rest = host.split("://", 1)
    # A server bound to all interfaces is reached through loopback.
    rest = rest.replace("0.0.0.0", "127.0.0.1", 1)
    if ":" not in rest.split("/", 1)[0]:
        rest = rest.replace("/", ":11434/", 1) if "/" in rest else f"{rest}:11434"
    return f"{scheme}://{rest}".rstrip("/")


def ollama_running(host: str, timeout: float = 1.5) -> bool:
    import httpx

    try:
        return httpx.get(f"{host}/api/tags", timeout=timeout).status_code == 200
    except httpx.HTTPError:
        return False


def find_ollama() -> Optional[Path]:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"
        candidate = local / "ollama.exe"
        if candidate.is_file():
            return candidate
    return None


def start_hidden(executable: Path) -> None:
    """Run ``ollama serve`` with no window, detached from Mark's lifetime."""
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        # A hidden console (not DETACHED_PROCESS): the GPU runners Ollama
        # spawns inherit it, so none of them pops up a window either.
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([str(executable), "serve"], **kwargs)


def ensure_ollama(
    config: Any = None,
    status: Callable[[str], None] = lambda _msg: None,
    *,
    wait_seconds: float = 30.0,
) -> bool:
    """Make sure Ollama answers; start it hidden if needed. Returns success."""
    host = ollama_host(config)
    if ollama_running(host):
        return True
    executable = find_ollama()
    if executable is None:
        return False
    status("Iniciando Ollama…")
    start_hidden(executable)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if ollama_running(host):
            return True
        time.sleep(0.5)
    return False


__all__ = ["ensure_ollama", "find_ollama", "ollama_host", "ollama_running"]
