from unittest import TestCase

import numpy as np

from jarvis_local.chatterbox_worker import (
    REFERENCE_TARGET_DBFS,
    clean_reference,
    parse_args,
)


SAMPLE_RATE = 24_000


def tone(seconds: float, amplitude: float) -> np.ndarray:
    times = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * 220 * times)).astype(np.float32)


class ReferenceCleaningTests(TestCase):
    def test_trims_edge_silence_so_prompt_window_contains_speech(self) -> None:
        silence = np.zeros(int(SAMPLE_RATE * 2.0), dtype=np.float32)
        speech = tone(3.0, 0.2)
        cleaned = clean_reference(np.concatenate([silence, speech, silence]), SAMPLE_RATE)
        # Solo se conservan 0,1 s de margen a cada lado de la voz.
        self.assertAlmostEqual(cleaned.size / SAMPLE_RATE, 3.2, delta=0.05)
        self.assertGreater(float(np.abs(cleaned[: int(SAMPLE_RATE * 0.2)]).max()), 0.01)

    def test_normalizes_loudness_without_clipping(self) -> None:
        quiet = clean_reference(tone(3.0, 0.01), SAMPLE_RATE)
        loud = clean_reference(tone(3.0, 0.9), SAMPLE_RATE)
        for audio in (quiet, loud):
            rms_dbfs = 20 * np.log10(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
            self.assertAlmostEqual(rms_dbfs, REFERENCE_TARGET_DBFS, delta=0.5)
            self.assertLessEqual(float(np.abs(audio).max()), 0.95)

    def test_limits_gain_when_peaks_would_clip(self) -> None:
        spiky = tone(3.0, 0.005)
        spiky[1000] = 0.9
        cleaned = clean_reference(spiky, SAMPLE_RATE)
        self.assertLessEqual(float(np.abs(cleaned).max()), 0.9500001)

    def test_rejects_silent_or_invalid_reference(self) -> None:
        with self.assertRaises(ValueError):
            clean_reference(np.zeros(SAMPLE_RATE, dtype=np.float32), SAMPLE_RATE)
        with self.assertRaises(ValueError):
            clean_reference(np.array([0.1, np.nan], dtype=np.float32), SAMPLE_RATE)
        with self.assertRaises(ValueError):
            clean_reference(np.array([], dtype=np.float32), SAMPLE_RATE)


class WorkerArgumentTests(TestCase):
    def test_defaults_preserve_previous_behaviour_for_direct_invocations(self) -> None:
        args = parse_args(["--model-dir", "m", "--model-file", "t3.safetensors", "--reference", "r.wav"])
        self.assertEqual(args.s3gen_file, "s3gen.pt")
        self.assertEqual(args.accent_source, "reference")
        self.assertEqual(args.reference_processing, "raw")
        self.assertEqual(args.seed, 0)

    def test_rejects_unknown_accent_source(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(
                [
                    "--model-dir", "m", "--model-file", "t3.safetensors",
                    "--reference", "r.wav", "--accent-source", "chileno",
                ]
            )


class AccentCheckTests(TestCase):
    def test_writes_three_profiles_with_the_previous_combination_as_baseline(self) -> None:
        import asyncio
        import json
        import sys
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from jarvis_local import voice_accent_check
        from jarvis_local.audio.providers import ChatterboxTTSProvider
        from tests.mark.helpers import make_settings

        worker = Path(__file__).parent / "fixtures" / "fake_chatterbox_worker.py"
        commands: list[dict] = []

        class FakeProvider(ChatterboxTTSProvider):
            def _validate_files(self) -> None:
                commands.append(
                    {
                        "s3gen": self.s3gen_file,
                        "accent": self.accent_source,
                        "processing": self.reference_processing,
                        "seed": self.seed,
                    }
                )

            def _command(self) -> list[str]:
                return [sys.executable, str(worker)]

        with TemporaryDirectory() as directory:
            settings = make_settings(
                Path(directory), tts_provider="chatterbox", tts_clone_model_path=Path(directory)
            )
            with patch.object(voice_accent_check, "ChatterboxTTSProvider", FakeProvider):
                output = asyncio.run(voice_accent_check.run(settings))
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                list(manifest["profiles"]),
                ["1_anterior", "2_configurado", "3_pronunciacion_del_modelo"],
            )
            for name in manifest["profiles"]:
                self.assertEqual(len(list((output / name).glob("*.wav"))), 5)
            self.assertEqual(
                commands[0], {"s3gen": "s3gen.pt", "accent": "reference", "processing": "raw", "seed": 0}
            )
            self.assertEqual(commands[1]["s3gen"], "s3gen_v3.pt")
            self.assertEqual(commands[2]["accent"], "model")
