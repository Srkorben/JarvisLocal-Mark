from __future__ import annotations

import argparse
import base64
import contextlib
import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np


def _coqui_pcm16(values: np.ndarray) -> np.ndarray:
    """Replica la normalizacion que usa ``Synthesizer.save_wav``.

    La vista previa validada por el usuario paso por la API publica de Coqui,
    que normaliza el pico antes de escribir PCM16. El worker no debe cambiar
    silenciosamente esa etapa porque altera mucho una voz clonada de nivel bajo.
    """

    waveform = np.asarray(values, dtype=np.float32).reshape(-1)
    if waveform.size == 0:
        return np.empty(0, dtype="<i2")
    scale = 32767.0 / max(0.01, float(np.max(np.abs(waveform))))
    return np.clip(waveform * scale, -32768.0, 32767.0).astype("<i2")


def _official_inference_settings(model, *, temperature: float, speed: float) -> dict:
    """Usa los mismos ajustes que ``Xtts.synthesize`` de la API oficial."""

    return {
        "temperature": temperature,
        "length_penalty": float(model.config.length_penalty),
        "repetition_penalty": float(model.config.repetition_penalty),
        "top_k": int(model.config.top_k),
        "top_p": float(model.config.top_p),
        "speed": speed,
        "enable_text_splitting": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker local aislado de XTTS-v2")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--language", default="es")
    return parser.parse_args()


def _reply(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _stage(name: str, started: float) -> None:
    print(
        f"[jarvis-xtts] stage={name} elapsed_seconds={time.monotonic() - started:.3f}",
        file=sys.stderr,
        flush=True,
    )


def _install_safe_audio_loader() -> None:
    """Evita que PyTorch 2.9 exija FFmpeg compartido para un WAV PCM local."""

    import soundfile as sf
    import torch
    import torchaudio

    def load_audio(path, *args, **kwargs):
        del args, kwargs
        samples, sample_rate = sf.read(
            str(path), dtype="float32", always_2d=True
        )
        return torch.from_numpy(samples.T.copy()), int(sample_rate)

    torchaudio.load = load_audio


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    with contextlib.redirect_stdout(sys.stderr):
        _stage("import", started)
        _install_safe_audio_loader()
        import torch
        from TTS.api import TTS

        _stage("model_load", started)
        api = TTS(
            model_path=str(args.model_dir),
            config_path=str(args.model_dir / "config.json"),
            progress_bar=False,
        ).to(args.device)
        model = api.synthesizer.tts_model
        _stage("conditionals", started)
        gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
            audio_path=str(args.reference),
            max_ref_length=30,
            gpt_cond_len=6,
            gpt_cond_chunk_len=6,
        )
        if args.device == "cuda":
            _stage("cuda_prime", started)
            priming = model.inference(
                "Listo.",
                args.language,
                gpt_cond_latent,
                speaker_embedding,
                **_official_inference_settings(
                    model,
                    temperature=float(model.config.temperature),
                    speed=1.0,
                ),
            )
            del priming
            torch.cuda.synchronize()

    # La vista previa aceptada se genero con TTS.tts_to_file(), que usa la
    # frecuencia expuesta por Synthesizer. Mantenerla aqui evita cambiar tono y
    # velocidad entre la prueba y la voz reproducida dentro de Mark.
    sample_rate = int(api.synthesizer.output_sample_rate)
    _stage("ready", started)
    _reply({"type": "ready", "sample_rate": sample_rate, "device": args.device})

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
            temperature = min(
                1.5,
                max(
                    0.05,
                    float(request.get("temperature", model.config.temperature)),
                ),
            )
            speed = min(2.0, max(0.5, float(request.get("speed", 1.0))))
            with contextlib.redirect_stdout(sys.stderr):
                output = model.inference(
                    text,
                    args.language,
                    gpt_cond_latent,
                    speaker_embedding,
                    **_official_inference_settings(
                        model, temperature=temperature, speed=speed
                    ),
                )
            values = np.asarray(output["wav"], dtype=np.float32).reshape(-1)
            pcm = _coqui_pcm16(values)
            _reply(
                {
                    "id": request_id,
                    "ok": True,
                    "sample_rate": sample_rate,
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
