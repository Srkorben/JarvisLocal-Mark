from __future__ import annotations

import argparse
import json
from pathlib import Path

from .launcher import health, launch, project_root, read_endpoint, serve, stop


def voice_check(root: Path) -> dict[str, object]:
    """Estado de la voz de Mark según el mismo catálogo que usa el botón de llamada."""

    from ..config import Settings
    from .catalog import build_tool_catalog

    settings = Settings.load(root / "config" / "jarvis.toml")
    provider, device = settings.effective_tts
    voice = build_tool_catalog(
        root,
        voice_tts_provider=provider,
        piper_voice_path=settings.tts_voice_path,
        voice_reference_path=settings.tts_clone_reference_path,
        voice_reference_text_path=settings.tts_clone_reference_text_path,
        voice_consent_path=settings.tts_clone_consent_path,
    )["voice"]
    missing = list(voice.missing_requirements())
    return {
        "ready": not missing,
        "tts_provider": provider,
        "tts_device": device,
        "reference": str(settings.tts_clone_reference_path or ""),
        "missing": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Centro de control local de JarvisLocal")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--launch", action="store_true", help="inicia/reutiliza y abre el panel")
    mode.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--status", action="store_true", help="muestra el endpoint local")
    mode.add_argument("--stop", action="store_true", help="detiene únicamente el panel web")
    mode.add_argument(
        "--voice-check",
        action="store_true",
        help="informa qué necesita la conversación por voz y qué falta (no modifica nada)",
    )
    parser.add_argument("--no-browser", action="store_true", help="no abre el navegador")
    args = parser.parse_args()
    if args.serve:
        return serve()
    if args.voice_check:
        result = voice_check(project_root())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ready"] else 1
    if args.stop:
        print("Centro de control detenido." if stop() else "El centro de control no estaba activo.")
        return 0
    if args.status:
        endpoint = read_endpoint(project_root())
        public_endpoint = None
        if endpoint is not None:
            public_endpoint = {
                key: value for key, value in endpoint.items() if key != "token"
            }
        result = {
            "running": bool(endpoint and health(endpoint)),
            "endpoint": public_endpoint,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["running"] else 1
    result = launch(open_browser=not args.no_browser)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
