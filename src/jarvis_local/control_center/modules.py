from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..config import Settings
from ..database import Database


PUBLIC_IDENTITY = {
    "display_name": "Mark Scout",
    "short_name": "Mark",
    "technical_name": "JarvisLocal",
}


def build_module_snapshot(project_root: Path) -> dict[str, Any]:
    """Devuelve una vista segura y de solo lectura de la configuración real.

    No expone tokens, contenido de conversaciones, rutas de modelos, credenciales
    ni mecanismos para modificar la autoridad. Los cambios operativos siguen
    pasando por las interfaces confiables existentes.
    """

    settings = Settings.load(project_root / "config" / "jarvis.toml")
    tts_provider, tts_device = settings.effective_tts
    counts = Database(settings.database_path).counts()
    engines = _engine_status()
    return {
        "identity": dict(PUBLIC_IDENTITY),
        "modules": [
            {
                "id": "interface",
                "label": "Interfaz",
                "status": "partial",
                "status_label": "Alpha operativa",
                "summary": "Shell WPF/WebView2 adaptable y presencia 3D experimental.",
                "description": (
                    "Presenta los estados del agente sin duplicar el núcleo. "
                    "La calidad visual puede ajustarse localmente y baja durante inferencia."
                ),
                "facts": [
                    ["Shell", "WPF .NET 8"],
                    ["Render principal", "Canvas 2D en WebView2"],
                    ["Red", "Solo 127.0.0.1"],
                    ["Godot 3D", engines["godot"]],
                    ["Unity Editor", engines["unity"]],
                    ["Unreal Editor", engines["unreal"]],
                ],
                "capabilities": [
                    "Estados animados de voz y procesamiento",
                    "Paneles interactivos y diseño adaptable",
                    "Gobernador visual Auto / Equilibrado / Eco",
                    "Cliente Godot autenticado para presencia efímera",
                ],
                "limitations": [
                    "Godot es todavía un prototipo externo, no el render principal",
                    "Sin telemetría DXGI de GPU en esta versión",
                ],
                "controls": ["visual_quality"],
            },
            {
                "id": "authority",
                "label": "Autoridad",
                "status": "operational",
                "status_label": "Operativa",
                "summary": "Límites de autonomía recalculados fuera del modelo.",
                "description": (
                    "Define qué puede proponer Mark y qué debe permitir, confirmar "
                    "o denegar el motor local de políticas."
                ),
                "facts": [
                    ["Autoaprobación máxima", f"Riesgo {settings.auto_approve_max_risk}"],
                    ["Rondas de herramientas", str(settings.max_tool_rounds)],
                    ["Pasos por turno", str(settings.max_steps_per_turn)],
                    ["Privilegiadas", _on_off(settings.privileged_tools_enabled)],
                ],
                "capabilities": [
                    "Confirmación vinculada a una acción concreta",
                    "Presupuestos y cancelación por turno",
                    "Riesgo calculado por código, no por el LLM",
                ],
                "limitations": [
                    "La interfaz solo consulta; cambiar autoridad exige la CLI confiable",
                ],
                "controls": [],
            },
            {
                "id": "audio",
                "label": "Audio",
                "status": "operational",
                "status_label": "Operativo",
                "summary": "Conversación local semidúplex continua o pulsar-para-hablar.",
                "description": (
                    "En llamada detecta cada intervención y vuelve a escuchar tras responder; "
                    "el modo manual captura solo mientras mantienes pulsado el micrófono."
                ),
                "facts": [
                    ["Entrada", _device(settings.audio_input_device)],
                    ["Salida", _device(settings.audio_output_device)],
                    ["STT", f"{settings.stt_provider} / {settings.stt_compute_type}"],
                    ["STT en", "CPU"],
                    ["TTS", f"{tts_provider} / {tts_device.upper()}"],
                    ["Chat escrito", "Sin STT; TTS solo al pedir voz"],
                    ["Modos", "Conversación / Pulsar para hablar"],
                    ["Control", "Iniciar, silenciar, interrumpir y colgar"],
                    ["Cancelar", "Control visible en la interfaz"],
                    ["Muestreo", f"{settings.audio_sample_rate} Hz"],
                    ["VAD", _on_off(settings.stt_vad_filter)],
                ],
                "capabilities": [
                    "WASAPI compartido y selección configurable",
                    "faster-whisper local y voz ligera Piper en CPU",
                    "Voz propia Chatterbox conservada (GPU solo con autorización)",
                    "Detección local de inicio y final de cada intervención",
                    "Cancelación de captura, LLM, TTS y reproducción",
                ],
                "limitations": [
                    "Semidúplex: Mark no escucha mientras responde",
                    "Sin wake word ni barge-in natural",
                ],
                "controls": [],
            },
            {
                "id": "model",
                "label": "Modelo",
                "status": "operational",
                "status_label": "Configurado",
                "summary": "LLM local sustituible, aislado de la autoridad del sistema.",
                "description": (
                    "Genera conversación y solicitudes tipadas. Cambiar proveedor o "
                    "modelo no modifica permisos efectivos."
                ),
                "facts": [
                    ["Proveedor", settings.model_provider],
                    ["Modelo", settings.model],
                    ["Contexto", f"{settings.context_tokens} tokens"],
                    ["Salida máxima", f"{settings.max_output_tokens} tokens"],
                    ["Temperatura", f"{settings.temperature:g}"],
                    ["Thinking", _on_off(settings.think)],
                    ["GPU layers", str(settings.llama_gpu_layers)],
                    ["Reserva VRAM", f"{settings.llama_fit_target_mib} MiB"],
                    ["GPU", "Reservada para el LLM" if tts_device == "cpu" else "Compartida con la voz"],
                ],
                "capabilities": [
                    "Streaming y cancelación real",
                    "Tool calling validado por esquemas",
                    "Offload adaptativo para 8 GB de VRAM",
                ],
                "limitations": [
                    "La vista informa la configuración, no edita el TOML todavía",
                    "Un modelo 8B no iguala siempre a los mejores servicios cloud",
                ],
                "controls": [],
            },
            {
                "id": "memory",
                "label": "Memoria",
                "status": "operational",
                "status_label": "Operativa",
                "summary": "Memoria y recuperación local aisladas por proyecto.",
                "description": (
                    "Separa trabajo, episodios, documentos y perfil explícito. "
                    "La evidencia recuperada nunca adquiere autoridad."
                ),
                "facts": [
                    ["Proyectos", str(counts["projects"])],
                    ["Sesiones", str(counts["sessions"])],
                    ["Mensajes", str(counts["messages"])],
                    ["Eventos auditados", str(counts["audit_events"])],
                    ["Embeddings", settings.embedding_model],
                    ["Resultados RAG", str(settings.rag_default_top_k)],
                    ["Límite vectorial", f"{settings.rag_vector_scan_limit:,}"],
                ],
                "capabilities": [
                    "FTS5 + embeddings locales con citas",
                    "Decisiones temporales con vigencia y procedencia",
                    "Corrección y eliminación explícitas",
                ],
                "limitations": [
                    "No vigila la pantalla ni indexa el disco completo",
                    "No convierte inferencias del modelo en perfil permanente",
                ],
                "controls": [],
            },
            {
                "id": "security",
                "label": "Seguridad",
                "status": "operational",
                "status_label": "Activa",
                "summary": "Política local, aislamiento, auditoría y denegación por defecto.",
                "description": (
                    "Protege archivos, herramientas y servicios con allowlists, niveles "
                    "de riesgo, loopback y auditoría encadenada."
                ),
                "facts": [
                    ["Raíces autorizadas", str(len(settings.allowed_roots))],
                    ["Herramientas autorizadas", str(len(settings.allowed_tools))],
                    ["Aplicaciones autorizadas", str(len(settings.allowed_applications))],
                    ["Dominios autorizados", str(len(settings.allowed_domains))],
                    ["IA remota", _on_off(settings.remote_ai_enabled)],
                    ["Automatización visual", _on_off(settings.visual_automation_enabled)],
                    ["Salida por turno", f"{settings.max_outbound_bytes} bytes"],
                ],
                "capabilities": [
                    "Cadena de auditoría verificable",
                    "Prompt injection tratada como datos no confiables",
                    "Servicios ligados exclusivamente a loopback",
                ],
                "limitations": [
                    "DPAPI/Credential Manager y broker C# siguen pendientes",
                    "No automatiza UAC ni pantallas protegidas",
                ],
                "controls": [],
            },
        ],
    }


def _on_off(value: bool) -> str:
    return "Activado" if value else "Desactivado"


def _device(value: str) -> str:
    return "Predeterminado de Windows (WASAPI)" if value == "wasapi_default" else value


def _engine_status() -> dict[str, str]:
    unity_roots = (
        Path(r"C:\Program Files\Unity\Hub\Editor"),
        Path(r"C:\Program Files\Unity\Editor"),
    )
    unity_versions = sorted(
        editor.parent.parent.name
        for root in unity_roots
        if root.is_dir()
        for editor in root.glob("*/Editor/Unity.exe")
    )
    unreal_roots = (Path(r"C:\Program Files\Epic Games"), Path(r"D:\Epic Games"))
    unreal_versions = sorted(
        editor.parents[3].name
        for root in unreal_roots
        if root.is_dir()
        for editor in root.glob("UE_*/Engine/Binaries/Win64/UnrealEditor.exe")
    )
    return {
        "godot": "4.7.2 · integrado" if shutil.which("godot.exe") else "No detectado",
        "unity": ", ".join(unity_versions) if unity_versions else "No detectado",
        "unreal": ", ".join(unreal_versions) if unreal_versions else "No detectado",
    }
