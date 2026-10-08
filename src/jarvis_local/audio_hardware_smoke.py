from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from .audio import (
    SoundDevicePlayer,
    SoundDeviceRecorder,
    create_tts_provider,
)
from .cancellation import CancellationToken
from .cli import default_config_path
from .config import Settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prueba explícita y efímera de micrófono/altavoces"
    )
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--capture-seconds", type=float, default=2.0)
    parser.add_argument("--no-playback", action="store_true")
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    settings = Settings.load(args.config)
    recorder = SoundDeviceRecorder(
        selector=settings.audio_input_device,
        target_sample_rate=settings.audio_sample_rate,
        max_seconds=max(args.capture_seconds + 1, settings.audio_max_record_seconds),
    )
    print("MICROPHONE_ACTIVE", flush=True)
    recorder.start()
    await asyncio.sleep(max(0.1, args.capture_seconds))
    captured = recorder.stop()
    print("MICROPHONE_INACTIVE", flush=True)
    report: dict = {
        "capture": {
            "device": recorder.device.model_dump(mode="json"),
            "requested_seconds": args.capture_seconds,
            "captured_seconds": captured.duration_seconds,
            "close_seconds": captured.capture_close_seconds,
            "rms": captured.rms,
            "samples": len(captured.samples),
            "stored": False,
        }
    }
    if not args.no_playback:
        tts = create_tts_provider(settings)
        player = SoundDevicePlayer(selector=settings.audio_output_device)
        token = CancellationToken()
        started = time.monotonic()
        spoken = await tts.synthesize(
            "Prueba de audio local de Jarvis completada.", token
        )
        playback = await player.play(spoken, token)
        await tts.aclose()
        report["playback"] = {
            "device": player.device.model_dump(mode="json"),
            "synthesis_seconds": spoken.synthesis_seconds,
            "audio_seconds": spoken.duration_seconds,
            "playback_seconds": playback,
            "total_seconds": time.monotonic() - started,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
