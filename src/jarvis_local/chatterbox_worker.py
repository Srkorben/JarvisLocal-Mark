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


# Chatterbox condiciona dos cosas distintas con la misma muestra:
#   * T3 (texto → tokens de habla) recibe el embedding del hablante y, como
#     prompt, los tokens de los primeros 6 s. Ese prompt transmite ritmo,
#     entonación y pronunciación: es la vía por la que se hereda el acento.
#   * S3Gen (tokens → audio) recibe los primeros 10 s como referencia acústica:
#     es la vía principal del timbre.
# Las opciones de este módulo permiten tratar ambas vías por separado.
ACCENT_SOURCES = ("reference", "model")
REFERENCE_PROCESSING = ("raw", "clean")
REFERENCE_TARGET_DBFS = -27.0
REFERENCE_SILENCE_DB = 40.0
REFERENCE_PADDING_SECONDS = 0.1
REFERENCE_FRAME_SECONDS = 0.02
S3GEN_DERIVED_BUFFERS = frozenset({"tokenizer._mel_filters", "tokenizer.window"})


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker local aislado de Chatterbox")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--model-file", required=True)
    parser.add_argument("--s3gen-file", default="s3gen.pt")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--language", default="es")
    parser.add_argument("--accent-source", choices=ACCENT_SOURCES, default="reference")
    parser.add_argument(
        "--reference-processing", choices=REFERENCE_PROCESSING, default="raw"
    )
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args(argv)


def _reply(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _stage(name: str, started: float) -> None:
    """Escribe hitos diagnósticos sin contaminar el protocolo JSONL."""

    print(
        f"[jarvis-chatterbox] stage={name} elapsed_seconds={time.monotonic() - started:.3f}",
        file=sys.stderr,
        flush=True,
    )


def clean_reference(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Recorta silencios de borde y normaliza la sonoridad de la referencia.

    El prompt de T3 son solo los primeros 6 s de la muestra. Si la grabación
    empieza con silencio, respiraciones o ruido, ese prompt contiene poca habla
    y la prosodia generada se desvía. Una sonoridad estable evita además que el
    volumen de captura cambie la expresividad. El archivo enrolado no se
    modifica: el consentimiento sigue ligado a su SHA-256 original.
    """

    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    if audio.size == 0 or not np.isfinite(audio).all():
        raise ValueError("La referencia de voz está vacía o contiene valores inválidos.")
    frame = max(1, int(sample_rate * REFERENCE_FRAME_SECONDS))
    usable = audio[: audio.size - audio.size % frame] if audio.size >= frame else audio
    frames = usable.reshape(-1, frame) if usable.size >= frame else usable.reshape(1, -1)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    peak = float(rms.max())
    if peak <= 1e-6:
        raise ValueError("La referencia de voz no contiene señal audible.")
    active = np.flatnonzero(rms >= peak * 10 ** (-REFERENCE_SILENCE_DB / 20))
    padding = int(sample_rate * REFERENCE_PADDING_SECONDS)
    start = max(0, int(active[0]) * frame - padding)
    end = min(audio.size, (int(active[-1]) + 1) * frame + padding)
    trimmed = audio[start:end]

    current = float(np.sqrt(np.mean(np.square(trimmed, dtype=np.float64))))
    gain = 10 ** (REFERENCE_TARGET_DBFS / 20) / current
    trimmed_peak = float(np.max(np.abs(trimmed)))
    # Nunca se satura: si la ganancia objetivo recortaría picos, se limita.
    gain = min(gain, 0.95 / trimmed_peak)
    return (trimmed * gain).astype(np.float32)


def load_model(model_dir: Path, model_file: str, s3gen_file: str, device: str):
    """Carga Chatterbox con un decodificador S3Gen explícito.

    ``ChatterboxMultilingualTTS.from_local`` fija ``s3gen.pt`` (decodificador
    de la generación anterior). Los T3 del Single Language Pack V3, como
    ``t3_es_mx_latam``, se publicaron junto a ``s3gen_v3.pt`` y la demo oficial
    los combina así. Mezclar generaciones degrada la articulación.
    """

    import torch
    from safetensors.torch import load_file as load_safetensors
    from chatterbox.models.s3gen import S3Gen
    from chatterbox.models.t3 import T3
    from chatterbox.models.t3.modules.t3_config import T3Config
    from chatterbox.models.tokenizers import MTLTokenizer
    from chatterbox.models.voice_encoder import VoiceEncoder
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    map_location = torch.device("cpu") if device == "cpu" else None
    ve = VoiceEncoder()
    ve.load_state_dict(
        torch.load(model_dir / "ve.pt", map_location=map_location, weights_only=True)
    )
    ve.to(device).eval()

    t3 = T3(T3Config.multilingual())
    t3_state = load_safetensors(model_dir / model_file)
    if "model" in t3_state.keys():
        t3_state = t3_state["model"][0]
    t3.load_state_dict(t3_state)
    t3.to(device).eval()

    s3gen = S3Gen()
    result = s3gen.load_state_dict(
        torch.load(model_dir / s3gen_file, map_location=map_location, weights_only=True),
        strict=False,
    )
    # s3gen_v3 no serializa dos buffers deterministas del tokenizador, que
    # S3Gen() ya calcula al construirse. Cualquier otra diferencia es un error.
    unexpected_missing = set(result.missing_keys) - S3GEN_DERIVED_BUFFERS
    if unexpected_missing or result.unexpected_keys:
        raise RuntimeError(
            f"{s3gen_file} no es compatible con S3Gen: faltan "
            f"{sorted(unexpected_missing)}, sobran {sorted(result.unexpected_keys)}"
        )
    s3gen.to(device).eval()

    tokenizer = MTLTokenizer(str(model_dir / "grapheme_mtl_merged_expanded_v1.json"))
    return ChatterboxMultilingualTTS(t3, s3gen, ve, tokenizer, device, conds=None)


def prepare_conditionals(
    model,
    reference: Path,
    *,
    accent_source: str,
    reference_processing: str,
    exaggeration: float = 0.5,
) -> None:
    """Construye los condicionantes separando timbre y pronunciación.

    ``accent_source="reference"`` reproduce el comportamiento original: los
    tokens de la muestra guían la pronunciación de T3. ``"model"`` omite ese
    prompt (opción soportada por ``T3CondEnc``): T3 conserva el embedding del
    hablante y S3Gen conserva el timbre, pero la pronunciación sigue la
    distribución aprendida por el checkpoint.
    """

    import librosa
    import torch
    from chatterbox.models.s3gen import S3GEN_SR
    from chatterbox.models.s3tokenizer import S3_SR
    from chatterbox.models.t3.modules.cond_enc import T3Cond
    from chatterbox.mtl_tts import Conditionals

    if accent_source not in ACCENT_SOURCES:
        raise ValueError(f"accent_source no soportado: {accent_source}")
    if reference_processing not in REFERENCE_PROCESSING:
        raise ValueError(f"reference_processing no soportado: {reference_processing}")

    wav_24k, _ = librosa.load(str(reference), sr=S3GEN_SR)
    if reference_processing == "clean":
        wav_24k = clean_reference(wav_24k, S3GEN_SR)
    wav_16k = librosa.resample(wav_24k, orig_sr=S3GEN_SR, target_sr=S3_SR)

    gen_ref = model.s3gen.embed_ref(
        wav_24k[: model.DEC_COND_LEN], S3GEN_SR, device=model.device
    )
    prompt_tokens = None
    prompt_length = model.t3.hp.speech_cond_prompt_len
    if accent_source == "reference" and prompt_length:
        prompt_tokens, _ = model.s3gen.tokenizer.forward(
            [wav_16k[: model.ENC_COND_LEN]], max_len=prompt_length
        )
        prompt_tokens = torch.atleast_2d(prompt_tokens).to(model.device)
    speaker = torch.from_numpy(model.ve.embeds_from_wavs([wav_16k], sample_rate=S3_SR))
    speaker = speaker.mean(axis=0, keepdim=True).to(model.device)
    t3_cond = T3Cond(
        speaker_emb=speaker,
        cond_prompt_speech_tokens=prompt_tokens,
        emotion_adv=exaggeration * torch.ones(1, 1, 1),
    ).to(device=model.device)
    model.conds = Conditionals(t3_cond, gen_ref)


def synthesize(
    model,
    text: str,
    *,
    language: str,
    exaggeration: float,
    cfg_weight: float,
    temperature: float,
    seed: int,
):
    """Genera una frase. Con semilla fija, cada frase parte del mismo estado
    aleatorio y la prosodia no cambia arbitrariamente entre frases."""

    import torch

    if seed:
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    return model.generate(
        text,
        language_id=language,
        exaggeration=exaggeration,
        cfg_weight=cfg_weight,
        temperature=temperature,
    )


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    # Las bibliotecas de investigación imprimen progreso; el stdout queda
    # reservado exclusivamente al protocolo JSONL local.
    with contextlib.redirect_stdout(sys.stderr):
        _stage("model_load", started)
        model = load_model(args.model_dir, args.model_file, args.s3gen_file, args.device)
        _stage("conditionals", started)
        prepare_conditionals(
            model,
            args.reference,
            accent_source=args.accent_source,
            reference_processing=args.reference_processing,
        )
        if args.device == "cuda":
            # La primera inferencia CUDA inicializa kernels de atención y puede
            # añadir varios segundos al primer turno. Se paga ese coste durante
            # el arranque, antes de anunciar que la voz está lista.
            _stage("cuda_prime", started)
            priming_waveform = synthesize(
                model,
                "Listo.",
                language=args.language,
                exaggeration=0.5,
                cfg_weight=0.5,
                temperature=0.8,
                seed=args.seed,
            )
            del priming_waveform
            import torch

            torch.cuda.synchronize()
    _stage("ready", started)
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
                waveform = synthesize(
                    model,
                    text,
                    language=args.language,
                    exaggeration=float(request.get("exaggeration", 0.5)),
                    cfg_weight=float(request.get("cfg_weight", 0.5)),
                    temperature=float(request.get("temperature", 0.8)),
                    seed=args.seed,
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
