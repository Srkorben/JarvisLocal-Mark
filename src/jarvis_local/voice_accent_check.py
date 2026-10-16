"""Comparación A/B local de pronunciación para la voz clonada.

Genera, con la referencia enrolada, las mismas frases bajo el perfil anterior,
el configurado y una variante con pronunciación del modelo. Usa el mismo
``ChatterboxTTSProvider`` y worker aislado que la conversación por voz. Escribe
WAV en ``data/voice_eval/<fecha>/`` para escucha humana; no modifica la
configuración ni la referencia y no usa red.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import wave
from datetime import datetime, timezone
from pathlib import Path

from .audio.providers import ChatterboxTTSProvider
from .cancellation import CancellationToken
from .config import Settings


SENTENCES = (
    "Hola, soy Mark. ¿En qué te puedo ayudar hoy?",
    "Encontré tres archivos nuevos en la carpeta de proyectos y ya los organicé.",
    "Mañana a las nueve tienes una reunión con la directora. ¿Quieres que te lo recuerde?",
    "Los cambios están guardados, pero todavía no los he enviado al repositorio.",
    "La lluvia de ayer hizo que el tráfico estuviera bastante lento en la ciudad.",
)


def profiles(settings: Settings) -> dict[str, dict[str, object]]:
    return {
        # Combinación anterior a la corrección: decodificador de generación
        # previa, referencia sin limpiar, CFG 0,4 y muestreo sin semilla.
        "1_anterior": {
            "tts_clone_s3gen_file": "s3gen.pt",
            "tts_clone_accent_source": "reference",
            "tts_clone_reference_processing": "raw",
            "tts_clone_cfg_weight": 0.4,
            "tts_clone_seed": 0,
        },
        "2_configurado": {},
        "3_pronunciacion_del_modelo": {"tts_clone_accent_source": "model"},
    }


def _write_wav(path: Path, samples, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.astype("<i2", copy=False).tobytes())


async def run(settings: Settings) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = settings.data_dir / "voice_eval" / stamp
    output.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, object] = {"created_at": stamp, "sentences": SENTENCES, "profiles": {}}
    for name, overrides in profiles(settings).items():
        profile_settings = settings.model_copy(update=overrides)
        provider = ChatterboxTTSProvider(profile_settings)
        target = output / name
        target.mkdir()
        timings = []
        try:
            await provider.warmup()
            for index, text in enumerate(SENTENCES, start=1):
                audio = await provider.synthesize(text, CancellationToken())
                _write_wav(target / f"{index}.wav", audio.samples, audio.sample_rate)
                timings.append(round(audio.synthesis_seconds, 2))
        finally:
            await provider.aclose()
        manifest["profiles"][name] = {
            "s3gen_file": profile_settings.tts_clone_s3gen_file,
            "accent_source": profile_settings.tts_clone_accent_source,
            "reference_processing": profile_settings.tts_clone_reference_processing,
            "cfg_weight": profile_settings.tts_clone_cfg_weight,
            "exaggeration": profile_settings.tts_clone_exaggeration,
            "temperature": profile_settings.tts_clone_temperature,
            "seed": profile_settings.tts_clone_seed,
            "synthesis_seconds": timings,
        }
        print(f"{name}: {target}", flush=True)
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Comparación A/B de pronunciación de la voz clonada")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    settings = Settings.load(args.config)
    if settings.tts_provider != "chatterbox":
        raise SystemExit("tts.provider debe ser 'chatterbox' para comparar la voz clonada.")
    output = asyncio.run(run(settings))
    print(f"Muestras listas para escucha en: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
