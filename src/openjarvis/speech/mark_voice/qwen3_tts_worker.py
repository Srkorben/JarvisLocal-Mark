from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import random
import sys
import time
import traceback
from pathlib import Path

import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker local aislado de Qwen3-TTS")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--reference-text", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--language", default="Spanish")
    parser.add_argument("--temperature", type=float, default=0.65)
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--subtalker-temperature", type=float, default=0.65)
    parser.add_argument("--subtalker-top-k", type=int, default=30)
    parser.add_argument("--subtalker-top-p", type=float, default=0.9)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def _reply(payload: dict) -> None:
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
    )
    sys.stdout.flush()


def _stage(name: str, started: float) -> None:
    print(
        f"[mark-qwen3-tts] stage={name} "
        f"elapsed_seconds={time.monotonic() - started:.3f}",
        file=sys.stderr,
        flush=True,
    )


@contextlib.contextmanager
def _native_stdout_to_stderr():
    """Mantiene limpio stdout JSONL incluso si una dependencia inicia SoX."""

    stdout_fd = sys.stdout.fileno()
    saved_stdout = os.dup(stdout_fd)
    try:
        os.dup2(sys.stderr.fileno(), stdout_fd)
        yield
    finally:
        os.dup2(saved_stdout, stdout_fd)
        os.close(saved_stdout)


def _pcm16(values: np.ndarray) -> np.ndarray:
    waveform = np.asarray(values, dtype=np.float32).reshape(-1)
    return np.round(np.clip(waveform, -1.0, 1.0) * 32767.0).astype("<i2")


def _quality_metrics(values: np.ndarray) -> tuple[float, float, float]:
    """Detecta colapsos ruidosos observados en el muestreo de Qwen3-TTS.

    El modelo es estocástico: con la misma voz produjo una toma limpia y otra
    con ruido robótico de alta frecuencia. No intentamos puntuar naturalidad;
    solo rechazamos señales globalmente anómalas antes de reproducirlas.
    """

    waveform = np.asarray(values, dtype=np.float32).reshape(-1)
    if waveform.size < 2:
        return 0.0, 0.0, 1.0
    rms = float(np.sqrt(np.mean(np.square(waveform), dtype=np.float64)))
    peak = float(np.max(np.abs(waveform)))
    zero_crossing_rate = float(
        np.mean(np.signbit(waveform[1:]) != np.signbit(waveform[:-1]))
    )
    return rms, peak, zero_crossing_rate


def _is_usable_speech(values: np.ndarray) -> bool:
    rms, peak, zero_crossing_rate = _quality_metrics(values)
    return 0.008 <= rms <= 0.45 and 0.02 <= peak <= 0.99 and zero_crossing_rate <= 0.16


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    with _native_stdout_to_stderr(), contextlib.redirect_stdout(sys.stderr):
        _stage("import", started)
        import torch
        from qwen_tts import Qwen3TTSModel

        reference_text = args.reference_text.read_text(encoding="utf-8").strip()
        if not reference_text:
            raise ValueError("La transcripción de referencia está vacía")
        _stage("model_load", started)
        model = Qwen3TTSModel.from_pretrained(
            str(args.model_dir),
            device_map="cuda:0" if args.device == "cuda" else "cpu",
            dtype=torch.bfloat16 if args.device == "cuda" else torch.float32,
            attn_implementation="sdpa",
        )
        if args.device == "cuda":
            torch.cuda.synchronize()

    _stage("ready", started)
    _reply({"type": "ready", "sample_rate": 24000, "device": args.device})

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
            text = " ".join(str(request.get("text") or "").split())
            if not text or len(text) > 1000:
                raise ValueError("El texto debe contener entre 1 y 1000 caracteres")
            selected = None
            for attempt in range(3):
                attempt_seed = args.seed + attempt
                random.seed(attempt_seed)
                np.random.seed(attempt_seed)
                torch.manual_seed(attempt_seed)
                if args.device == "cuda":
                    torch.cuda.manual_seed_all(attempt_seed)
                with contextlib.redirect_stdout(sys.stderr):
                    wavs, sample_rate = model.generate_voice_clone(
                        text=text,
                        language=args.language,
                        ref_audio=str(args.reference),
                        ref_text=reference_text,
                        x_vector_only_mode=False,
                        non_streaming_mode=True,
                        temperature=args.temperature,
                        top_k=args.top_k,
                        top_p=args.top_p,
                        subtalker_temperature=args.subtalker_temperature,
                        subtalker_top_k=args.subtalker_top_k,
                        subtalker_top_p=args.subtalker_top_p,
                    )
                candidate = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
                rms, peak, zcr = _quality_metrics(candidate)
                print(
                    f"[mark-qwen3-tts] attempt={attempt + 1} "
                    f"rms={rms:.5f} peak={peak:.5f} zcr={zcr:.5f}",
                    file=sys.stderr,
                    flush=True,
                )
                selected = candidate
                if _is_usable_speech(candidate):
                    break
            if selected is None or not _is_usable_speech(selected):
                raise RuntimeError(
                    "Qwen3-TTS produjo audio anómalo después de tres intentos"
                )
            pcm = _pcm16(selected)
            _reply(
                {
                    "id": request_id,
                    "ok": True,
                    "sample_rate": int(sample_rate),
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
