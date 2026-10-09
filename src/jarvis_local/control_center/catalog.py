from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Requirement:
    path: Path
    description: str


@dataclass(frozen=True, slots=True)
class ToolSpec:
    id: str
    name: str
    description: str
    category: str
    target: Path
    arguments: tuple[str, ...]
    working_directory: Path
    source: str
    requirements: tuple[Requirement, ...] = ()
    exclusive_groups: tuple[str, ...] = ()
    confirmation_required: bool = False
    visible_console: bool = False
    stoppable: bool = True

    def missing_requirements(self) -> tuple[str, ...]:
        checks = (Requirement(self.target, f"Ejecutable: {self.target}"),) + self.requirements
        return tuple(item.description for item in checks if not item.path.exists())


def _windows_executable(name: str, fallback: Path) -> Path:
    resolved = shutil.which(name)
    return Path(resolved).resolve() if resolved else fallback.resolve()


def build_tool_catalog(project_root: Path) -> dict[str, ToolSpec]:
    """Construye el catálogo cerrado que sustituye los nueve accesos originales.

    No se acepta configuración de comandos desde HTTP ni desde documentos. Cada
    ejecutable, argumento y directorio de trabajo se define aquí y se valida al
    iniciar la acción.
    """

    root = project_root.resolve()
    scripts = root / "scripts"
    config = root / "config" / "jarvis.toml"
    core_python = root / ".venv" / "Scripts" / "python.exe"
    clone_python = root / ".venv-chatterbox-cuda" / "Scripts" / "python.exe"
    voice_reference = root / "data" / "voices" / "user" / "reference.wav"
    voice_consent = root / "data" / "voices" / "user" / "consent.json"
    clone_model = root / "models" / "chatterbox-es-latam" / "t3_es_mx_latam.safetensors"
    clone_decoder = root / "models" / "chatterbox-es-latam" / "s3gen_v3.pt"
    whisper_model = root / "models" / "faster-whisper-small" / "model.bin"

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    pwsh = _windows_executable("pwsh.exe", program_files / "PowerShell" / "7" / "pwsh.exe")
    explorer = _windows_executable("explorer.exe", windows / "explorer.exe")
    notepad = _windows_executable("notepad.exe", windows / "System32" / "notepad.exe")
    local_app_data = Path(os.environ.get("LOCALAPPDATA", str(root)))
    godot = _windows_executable(
        "godot.exe", local_app_data / "Microsoft" / "WinGet" / "Links" / "godot.exe"
    )

    godot_project = root / "integrations" / "godot" / "mark-presence" / "project.godot"
    control_center_endpoint = root / "data" / "control_center" / "endpoint.json"

    def script_tool(
        *,
        tool_id: str,
        name: str,
        description: str,
        category: str,
        script_name: str,
        source: str,
        requirements: tuple[Requirement, ...],
        groups: tuple[str, ...],
        confirmation: bool = False,
        visible_console: bool = True,
    ) -> ToolSpec:
        script = scripts / script_name
        arguments = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ]
        if visible_console:
            arguments.insert(0, "-NoExit")
        return ToolSpec(
            id=tool_id,
            name=name,
            description=description,
            category=category,
            target=pwsh,
            arguments=tuple(arguments),
            working_directory=root,
            source=source,
            requirements=(Requirement(script, f"Script: scripts\\{script_name}"),) + requirements,
            exclusive_groups=groups,
            confirmation_required=confirmation,
            visible_console=visible_console,
        )

    core_requirements = (
        Requirement(core_python, "Entorno Python principal"),
        Requirement(config, "Configuración config\\jarvis.toml"),
    )
    voice_requirements = core_requirements + (
        Requirement(whisper_model, "Modelo faster-whisper-small"),
        Requirement(clone_python, "Entorno aislado Chatterbox"),
        Requirement(clone_model, "Modelo Chatterbox LatAm"),
        Requirement(clone_decoder, "Decodificador S3Gen V3 (Preparar clonación de voz)"),
        Requirement(voice_reference, "Muestra de voz propia enrolada"),
        Requirement(voice_consent, "Consentimiento de voz ligado por SHA-256"),
    )

    tools = (
        script_tool(
            tool_id="chat_text",
            name="Chat de texto",
            description="Abre la conversación local con el LLM y las herramientas autorizadas.",
            category="Asistente",
            script_name="Run-Jarvis.ps1",
            source="JarvisLocal - Chat de texto.lnk",
            requirements=core_requirements,
            groups=("core_runtime", "maintenance"),
        ),
        ToolSpec(
            id="voice",
            name="Conversación por voz",
            description="Inicia el modo push-to-talk. Mantén Ctrl+Alt+M para hablar.",
            category="Asistente",
            target=core_python,
            arguments=("-m", "jarvis_local.cli", "--config", str(config), "--voice"),
            working_directory=root,
            source="JarvisLocal - Conversación por voz.lnk",
            requirements=voice_requirements,
            exclusive_groups=("core_runtime", "audio", "maintenance"),
            visible_console=False,
        ),
        script_tool(
            tool_id="enroll_voice",
            name="Enrolar mi voz",
            description="Graba o importa localmente una muestra autorizada de unos 20 segundos.",
            category="Voz",
            script_name="Enroll-OwnVoice.ps1",
            source="JarvisLocal - Enrolar mi voz.lnk",
            requirements=core_requirements,
            groups=("audio", "maintenance"),
            confirmation=True,
        ),
        script_tool(
            tool_id="diagnostics",
            name="Diagnóstico",
            description="Comprueba núcleo, modelos, auditoría y subsistema de audio.",
            category="Mantenimiento",
            script_name="Diagnose-Jarvis.ps1",
            source="JarvisLocal - Diagnóstico.lnk",
            requirements=core_requirements,
            groups=("core_runtime", "maintenance"),
        ),
        script_tool(
            tool_id="setup_core",
            name="Instalar o reparar",
            description="Recrea dependencias del núcleo y ejecuta su validación.",
            category="Mantenimiento",
            script_name="Setup.ps1",
            source="JarvisLocal - Instalar o reparar.lnk",
            requirements=(),
            groups=("core_runtime", "audio", "maintenance"),
            confirmation=True,
        ),
        script_tool(
            tool_id="setup_audio",
            name="Preparar modelos de audio",
            description="Descarga o verifica STT y el fallback Piper.",
            category="Mantenimiento",
            script_name="Setup-AudioModels.ps1",
            source="JarvisLocal - Preparar modelos de audio.lnk",
            requirements=core_requirements,
            groups=("core_runtime", "audio", "maintenance"),
            confirmation=True,
        ),
        script_tool(
            tool_id="setup_voice_clone",
            name="Preparar clonación de voz",
            description="Instala o verifica Chatterbox LatAm en un entorno aislado.",
            category="Mantenimiento",
            script_name="Setup-VoiceClone.ps1",
            source="JarvisLocal - Preparar clonación de voz.lnk",
            requirements=(),
            groups=("core_runtime", "audio", "maintenance"),
            confirmation=True,
        ),
        ToolSpec(
            id="open_project",
            name="Abrir proyecto",
            description="Abre la carpeta técnica del proyecto en el Explorador.",
            category="Archivos",
            target=explorer,
            arguments=(str(root),),
            working_directory=root,
            source="JarvisLocal - Abrir proyecto.lnk",
            requirements=(Requirement(root, "Carpeta del proyecto"),),
            stoppable=False,
        ),
        ToolSpec(
            id="open_config",
            name="Configuración",
            description="Abre config\\jarvis.toml con el editor local predeterminado.",
            category="Archivos",
            target=notepad,
            arguments=(str(config),),
            working_directory=root,
            source="JarvisLocal - Configuración.lnk",
            requirements=(Requirement(config, "Configuración config\\jarvis.toml"),),
            stoppable=False,
        ),
        ToolSpec(
            id="presence_3d",
            name="Presencia 3D experimental",
            description="Abre una escena Godot conectada al estado efímero de Mark.",
            category="Interfaz",
            target=godot,
            arguments=(
                "--path",
                str(godot_project.parent),
                "--rendering-method",
                "gl_compatibility",
                "--",
                "--endpoint-file",
                str(control_center_endpoint),
            ),
            working_directory=root,
            source="Integración Mark Scout / Godot 4.7.2",
            requirements=(
                Requirement(godot_project, "Proyecto Godot de presencia 3D"),
                Requirement(control_center_endpoint, "Endpoint local de Mark Scout"),
            ),
            exclusive_groups=("visual_runtime",),
            visible_console=False,
        ),
    )
    return {tool.id: tool for tool in tools}
