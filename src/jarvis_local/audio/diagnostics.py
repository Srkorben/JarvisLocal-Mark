from __future__ import annotations

import importlib.metadata
import time
from pathlib import Path

from ..config import Settings
from .devices import SoundDeviceCatalog, _sounddevice
from .providers import create_stt_provider, create_tts_provider


async def audio_diagnostics(settings: Settings) -> dict:
    input_device = SoundDeviceCatalog.resolve(
        settings.audio_input_device, direction="input"
    )
    output_device = SoundDeviceCatalog.resolve(
        settings.audio_output_device, direction="output"
    )
    sd = _sounddevice()
    sd.check_input_settings(
        device=input_device.index,
        channels=1,
        dtype="int16",
        samplerate=input_device.default_sample_rate,
    )
    sd.check_output_settings(
        device=output_device.index,
        channels=1,
        dtype="int16",
        samplerate=output_device.default_sample_rate,
    )
    stt = create_stt_provider(settings)
    tts = create_tts_provider(settings)
    started = time.monotonic()
    await stt.warmup()
    stt_load = time.monotonic() - started
    started = time.monotonic()
    await tts.warmup()
    tts_load = time.monotonic() - started
    await stt.aclose()
    await tts.aclose()
    return {
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("sounddevice", "faster-whisper", "piper-tts")
        },
        "input": input_device.model_dump(mode="json"),
        "output": output_device.model_dump(mode="json"),
        "stt": {
            "provider": settings.stt_provider,
            "model_path": str(settings.stt_model_path),
            "size_bytes": _directory_size(settings.stt_model_path),
            "device": "cpu",
            "compute_type": settings.stt_compute_type,
            "load_seconds": stt_load,
        },
        "tts": _tts_report(settings, tts_load),
        "capture_target_sample_rate": settings.audio_sample_rate,
        "resampling": {
            "input": input_device.default_sample_rate != settings.audio_sample_rate,
            "output": output_device.default_sample_rate != 22050,
        },
    }


def _directory_size(path: Path | None) -> int:
    if path is None or not path.is_dir():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _file_size(path: Path | None) -> int:
    return 0 if path is None or not path.is_file() else path.stat().st_size


def _tts_report(settings: Settings, load_seconds: float) -> dict:
    if settings.tts_provider in {"chatterbox", "xtts"}:
        return {
            "provider": settings.tts_provider,
            "model_path": str(settings.tts_clone_model_path),
            "reference_configured": bool(
                settings.tts_clone_reference_path
                and settings.tts_clone_reference_path.is_file()
            ),
            "size_bytes": _directory_size(settings.tts_clone_model_path),
            "device": settings.tts_clone_device,
            "load_seconds": load_seconds,
            "isolated_process": True,
        }
    return {
        "provider": settings.tts_provider,
        "voice_path": str(settings.tts_voice_path),
        "size_bytes": _file_size(settings.tts_voice_path),
        "device": "cpu",
        "load_seconds": load_seconds,
        "isolated_process": False,
    }
