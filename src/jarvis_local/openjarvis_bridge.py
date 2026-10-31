"""Instancia de OpenJarvis gobernada por Mark.

El panel OpenJarvis de Mark ejecuta ``jarvis serve`` con un hogar propio
(``<data>/openjarvis``) para no mezclar sus datos con otra instalación y para
que la política de capacidades la dicte Mark. En cada arranque:

- ``capabilities.json`` se regenera desde ``[security]`` de ``config/jarvis.toml``:
  lo que Mark prohíbe (escribir, ejecutar código, salir a la red, enviar por
  canales) también queda prohibido a los agentes de OpenJarvis;
- ``config.toml`` conserva lo que el usuario configure en OpenJarvis (conectores,
  agentes, skills...), pero Mark fija las claves de seguridad, el servidor en
  loopback, el modelo y la voz.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Settings

OPENJARVIS_PORT = 8790  # igual que control_center.catalog.OPENJARVIS_PORT
POLICY_FILE = "capabilities.json"
CONFIG_FILE = "config.toml"

# Capacidades de OpenJarvis (openjarvis.security.capabilities.Capability).
FILE_READ = "file:read"
FILE_WRITE = "file:write"
NETWORK_FETCH = "network:fetch"
CODE_EXECUTE = "code:execute"
MEMORY_READ = "memory:read"
MEMORY_WRITE = "memory:write"
CHANNEL_SEND = "channel:send"
TOOL_INVOKE = "tool:invoke"
SCHEDULE_CREATE = "schedule:create"
SYSTEM_ADMIN = "system:admin"


def openjarvis_home(settings: Settings) -> Path:
    return settings.data_dir / "openjarvis"


def capability_policy(settings: Settings) -> dict[str, Any]:
    """Traduce la política de Mark a una política RBAC de OpenJarvis.

    ``_default`` cubre a todo agente sin política propia (agentes del panel,
    agentes programados). ``server:api`` es la propia persona administrando
    agentes desde la interfaz (listar, crear, detener).

    OpenJarvis evalúa cada capacidad contra el *nombre de la herramienta*, no
    contra una ruta o un dominio: las rutas legibles se acotan aparte con
    ``security.allowed_dirs`` (las raíces de Mark) y la red solo se concede
    entera cuando Mark autoriza algún dominio con presupuesto de salida.
    """

    grants: list[dict[str, str]] = [
        {"capability": MEMORY_READ},
        {"capability": MEMORY_WRITE},
        {"capability": SCHEDULE_CREATE},
        {"capability": FILE_READ},
    ]
    deny = [FILE_WRITE, CHANNEL_SEND, SYSTEM_ADMIN]

    if settings.allowed_domains and settings.max_outbound_bytes > 0:
        grants.append({"capability": NETWORK_FETCH})
    else:
        deny.append(NETWORK_FETCH)

    if settings.privileged_tools_enabled:
        grants.append({"capability": CODE_EXECUTE})
        grants.append({"capability": TOOL_INVOKE})
    else:
        deny += [CODE_EXECUTE, TOOL_INVOKE]

    return {
        "managed_by": "Mark (config/jarvis.toml [security]); se regenera en cada arranque",
        "agents": [
            {"agent_id": "_default", "grants": grants, "deny": sorted(deny)},
            {
                "agent_id": "server:api",
                "grants": [
                    {"capability": SYSTEM_ADMIN},
                    {"capability": MEMORY_READ},
                    {"capability": MEMORY_WRITE},
                    {"capability": SCHEDULE_CREATE},
                ],
                "deny": [],
            },
        ],
    }


def _managed_config(
    settings: Settings, home: Path, port: int = OPENJARVIS_PORT
) -> dict[str, dict[str, Any]]:
    managed: dict[str, dict[str, Any]] = {
        "server": {"host": "127.0.0.1", "port": port},
        "analytics": {"enabled": False, "choice_recorded": True},
        "speech": {
            "language": settings.language,
            "tts_backend": "mark_voice",
            "voice_id": "mark",
        },
        "security": {
            "enabled": True,
            "profile": "personal",
            "enforce_tool_confirmation": True,
            "ssrf_protection": True,
            "allowed_dirs": [str(root) for root in settings.allowed_roots],
            "capabilities": {
                "enabled": True,
                "default_deny": True,
                "policy_path": str(home / POLICY_FILE),
            },
        },
    }
    if settings.model_provider == "openjarvis":
        managed["intelligence"] = {"default_model": settings.model}
        if settings.openjarvis_engine:
            managed["engine"] = {"default": settings.openjarvis_engine}
    return managed


def _merge(document: Any, values: dict[str, Any]) -> None:
    import tomlkit

    for key, value in values.items():
        if isinstance(value, dict):
            table = document.get(key)
            if not isinstance(table, dict):
                table = tomlkit.table()
                document[key] = table
            _merge(table, value)
        else:
            document[key] = value


def prepare_openjarvis_home(settings: Settings, port: int = OPENJARVIS_PORT) -> Path:
    """Crea o actualiza el hogar de OpenJarvis de Mark y devuelve su ruta."""

    import tomlkit

    home = openjarvis_home(settings)
    home.mkdir(parents=True, exist_ok=True)
    (home / POLICY_FILE).write_text(
        json.dumps(capability_policy(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    config_path = home / CONFIG_FILE
    try:
        document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        document = tomlkit.document()
        document.add(tomlkit.comment(
            "OpenJarvis dentro de Mark. Puedes editar este archivo; Mark vuelve a "
            "fijar [security], [server], [analytics] y la voz en cada arranque."
        ))
    _merge(document, _managed_config(settings, home, port))
    config_path.write_text(tomlkit.dumps(document), encoding="utf-8")
    return home


def openjarvis_environment(settings: Settings, home: Path) -> tuple[tuple[str, str], ...]:
    """Variables fijas del proceso ``jarvis serve`` lanzado por Mark."""

    return (
        ("OPENJARVIS_HOME", str(home)),
        ("OPENJARVIS_FRAME_ANCESTORS", "http://127.0.0.1:*"),
        # Mismo contexto que el chat de Mark: Ollama no recarga el modelo al
        # alternar entre ambos chats y no reserva KV de más en la GPU.
        ("JARVIS_NUM_CTX", str(settings.context_tokens)),
    )
