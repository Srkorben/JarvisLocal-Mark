"""Ciclo de vida del servidor de OpenJarvis que Mark muestra en sus pestañas.

- Elige un puerto de loopback libre (8765 o siguientes): en Windows el puerto
  puede estar reservado o tomado por otro programa.
- Cierra instancias huérfanas de una sesión anterior de Mark, que seguían
  ocupando el puerto con otra configuración.
- Diagnostica si el servidor responde y si permite que Mark lo muestre
  (cabeceras de incrustación), para explicar en pantalla por qué no carga.
"""

from __future__ import annotations

import logging
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("jarvis_local.control_center")

HOST = "127.0.0.1"
# Nunca 8765-8774: ese rango es del centro de control de Mark.
FIRST_PORT = 8790
PORT_CANDIDATES = tuple(range(FIRST_PORT, FIRST_PORT + 20))
MARK_CONTROL_CENTER = "Mark Scout Control Center"


def origin_for(port: int) -> str:
    return f"http://{HOST}:{port}"


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def _is_mark_openjarvis(process: Any, root: Path) -> bool:
    """Un ``openjarvis.cli serve`` lanzado desde la .venv de este proyecto."""

    try:
        cmdline = [str(part) for part in process.cmdline()]
        exe = str(process.exe() or "")
    except Exception:
        return False
    if "openjarvis.cli" not in cmdline or "serve" not in cmdline:
        return False
    venv = str((root / ".venv").resolve()).casefold()
    return exe.casefold().startswith(venv) or any(
        part.casefold().startswith(venv) for part in cmdline[:1]
    )


def stop_orphans(root: Path) -> list[int]:
    """Termina servidores de OpenJarvis de Mark que quedaron de otra sesión."""

    try:
        import psutil
    except ImportError:
        return []
    stopped: list[int] = []
    for process in psutil.process_iter():
        if not _is_mark_openjarvis(process, root):
            continue
        try:
            for child in process.children(recursive=True):
                child.kill()
            process.kill()
            stopped.append(process.pid)
        except Exception:
            continue
    if stopped:
        LOGGER.info("Servidores de OpenJarvis huérfanos detenidos: %s", stopped)
    return stopped


def choose_port(root: Path) -> int:
    stop_orphans(root)
    for port in PORT_CANDIDATES:
        if port_is_free(port):
            return port
    LOGGER.warning("Puertos %s-%s ocupados; se usa %s", PORT_CANDIDATES[0], PORT_CANDIDATES[-1], FIRST_PORT)
    return FIRST_PORT


def diagnose(origin: str, timeout: float = 1.5) -> dict[str, Any]:
    """¿Responde el servidor y deja que Mark lo incruste?"""

    try:
        with urllib.request.urlopen(f"{origin}/health", timeout=timeout) as response:
            healthy = response.status == 200
            body = response.read(4096).decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return {"ready": False, "reachable": False, "framable": False, "detail": ""}
    if MARK_CONTROL_CENTER in body:
        return {
            "ready": False,
            "reachable": True,
            "framable": False,
            "detail": f"En {origin} responde el centro de control de Mark, no OpenJarvis.",
        }
    if not healthy:
        return {"ready": False, "reachable": True, "framable": False, "detail": "OpenJarvis no está sano."}
    try:
        with urllib.request.urlopen(f"{origin}/?shell=mark", timeout=timeout) as response:
            frame_options = response.headers.get("X-Frame-Options", "")
            csp = response.headers.get("Content-Security-Policy", "")
    except (urllib.error.URLError, OSError, ValueError):
        frame_options, csp = "", ""
    framable = not frame_options and "frame-ancestors" in csp
    detail = "" if framable else (
        f"El servidor en {origin} no permite que Mark lo muestre "
        f"(X-Frame-Options: {frame_options or 'ausente'}). "
        "Suele ser otra instancia de OpenJarvis abierta fuera de Mark: ciérrala o reinicia Mark."
    )
    return {"ready": healthy and framable, "reachable": True, "framable": framable, "detail": detail}


__all__ = ["choose_port", "diagnose", "origin_for", "port_is_free", "stop_orphans"]
