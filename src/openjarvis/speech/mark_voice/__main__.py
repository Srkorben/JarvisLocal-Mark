"""Manage Mark's voice: ``python -m openjarvis.speech.mark_voice <command>``.

Commands:
  status                 Show resolved paths and what is still missing.
  enroll                 Install a reference sample + transcription and bind
                         them to a consent manifest (your own voice only).
  say TEXT [--out PATH]  Synthesize TEXT with Mark's voice into a WAV file.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from openjarvis.speech.mark_voice.backend import (
    MarkVoiceSettings,
    MarkVoiceTTSBackend,
    mark_voice_home,
)
from openjarvis.speech.mark_voice.consent import create_own_voice_consent


def _status(settings: MarkVoiceSettings) -> int:
    print(f"Directorio de voz: {mark_voice_home()}")
    for name in (
        "python",
        "model_dir",
        "reference_path",
        "reference_text_path",
        "consent_path",
    ):
        print(f"  {name:20} {getattr(settings, name)}")
    issues = settings.problems()
    if not issues:
        print("Voz de Mark lista.")
        return 0
    print("Pendiente:")
    for issue in issues:
        print(f"  - {issue}")
    return 1


def _enroll(args: argparse.Namespace) -> int:
    if not args.confirm_own_voice:
        print(
            "Debes confirmar con --confirm-own-voice que la muestra es tu propia "
            "voz (o que tienes autorización de su titular).",
            file=sys.stderr,
        )
        return 2
    source = Path(args.reference).expanduser()
    if not source.is_file():
        print(f"No existe la muestra: {source}", file=sys.stderr)
        return 2
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8").strip()
    else:
        text = (args.text or "").strip()
    if not text:
        print(
            "Falta la transcripción literal de la muestra (--text o --text-file).",
            file=sys.stderr,
        )
        return 2
    home = mark_voice_home()
    home.mkdir(parents=True, exist_ok=True)
    for old in home.glob("reference.*"):
        if old.suffix != ".txt":
            old.unlink()
    reference = home / f"reference{source.suffix.lower()}"
    shutil.copyfile(source, reference)
    (home / "reference.txt").write_text(text + "\n", encoding="utf-8")
    create_own_voice_consent(
        reference_path=reference, consent_path=home / "consent.json"
    )
    print(f"Referencia enrolada en {reference}")
    return _status(MarkVoiceSettings.from_config())


def _say(args: argparse.Namespace) -> int:
    backend = MarkVoiceTTSBackend()
    try:
        result = backend.synthesize(args.text)
    finally:
        backend.close()
    out = Path(args.out)
    result.save(out)
    print(f"{out} ({result.duration_seconds:.2f} s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m openjarvis.speech.mark_voice")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    enroll = sub.add_parser("enroll")
    enroll.add_argument("--reference", required=True, help="Muestra de 15–30 s")
    enroll.add_argument("--text", help="Transcripción literal de la muestra")
    enroll.add_argument("--text-file", help="Archivo con la transcripción")
    enroll.add_argument("--confirm-own-voice", action="store_true")
    say = sub.add_parser("say")
    say.add_argument("text")
    say.add_argument("--out", default="mark.wav")
    args = parser.parse_args(argv)
    if args.command == "status":
        return _status(MarkVoiceSettings.from_config())
    if args.command == "enroll":
        return _enroll(args)
    return _say(args)


if __name__ == "__main__":
    raise SystemExit(main())
