from __future__ import annotations

import argparse
import base64
import contextlib
import json
import sys
import traceback
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker local aislado de Chatterbox")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--model-file", required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--language", default="es")
    return parser.parse_args()


def _reply(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    args = parse_args()
    # Las bibliotecas de investigación imprimen progreso; el stdout queda
    # reservado exclusivamente al protocolo JSONL local.
    with contextlib.redirect_stdout(sys.stderr):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        model = ChatterboxMultilingualTTS.from_local(
            args.model_dir,
            device=args.device,
            t3_model=args.model_file,
        )
        model.prepare_conditionals(args.reference)
    _reply({"type": "ready", "sample_rate": int(model.sr), "device": args.device})

    for raw_line in sys.stdin.buffer:
        request_id = None
        try:
            request = json.loads(raw_line.decode("utf-8"))
            request_id = request.get("id")
            command = request.get("command")
            if command == "close":
                _reply({"id": request_id, "ok": True})
                return 0
            if command != "synthesize":
                raise ValueError("Comando no soportado")
            text = str(request.get("text") or "").strip()
            if not text or len(text) > 1000:
                raise ValueError("El texto debe contener entre 1 y 1000 caracteres")
            with contextlib.redirect_stdout(sys.stderr):
                waveform = model.generate(
                    text,
                    language_id=args.language,
                    exaggeration=float(request.get("exaggeration", 0.5)),
                    cfg_weight=float(request.get("cfg_weight", 0.4)),
                    temperature=float(request.get("temperature", 0.8)),
                )
            values = waveform.detach().to("cpu").float().numpy().reshape(-1)
            pcm = np.clip(values, -1.0, 1.0)
            pcm = np.round(pcm * 32767.0).astype("<i2")
            _reply(
                {
                    "id": request_id,
                    "ok": True,
                    "sample_rate": int(model.sr),
                    "channels": 1,
                    "pcm16_base64": base64.b64encode(pcm.tobytes()).decode("ascii"),
                }
            )
        except Exception as exc:
            print(traceback.format_exc(), file=sys.stderr, flush=True)
            _reply(
                {
                    "id": request_id,
                    "ok": False,
                    "error": {"code": "synthesis_failed", "message": str(exc)},
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
