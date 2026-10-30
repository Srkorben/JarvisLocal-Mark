import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase

import numpy as np

from jarvis_local.audio.models import SynthesizedAudio, TranscriptionResult
from jarvis_local.latency_benchmark import percentile, render_markdown, run_suite, summarize
from jarvis_local.model_providers import ModelStreamEvent
from tests.mark.helpers import make_settings
from tests.mark.test_orchestrator import SequenceProvider

RESPONSE_TEXT = "Contenido de respuesta que no debe aparecer en el informe."


class StreamingProvider(SequenceProvider):
    async def stream_chat(self, messages, tools, cancellation):
        self.calls += 1
        for piece in ("Contenido de respuesta ", "que no debe aparecer ", "en el informe."):
            await asyncio.sleep(0.005)
            yield ModelStreamEvent(kind="text_delta", text=piece)
        yield ModelStreamEvent(kind="done", finish_reason="stop", provider_metrics={"predicted_per_second": 40.0})


class FakeSTT:
    name = "fake_stt"

    async def warmup(self):
        return None

    async def aclose(self):
        return None

    async def transcribe(self, audio, cancellation):
        return TranscriptionResult(
            text="Mark, saluda.",
            language="es",
            language_probability=0.99,
            average_log_probability=-0.1,
            processing_seconds=0.01,
            segments=(),
            ambiguous=False,
            ambiguity_reasons=(),
        )


class FakeTTS:
    name = "fake_tts"

    async def warmup(self):
        return None

    async def aclose(self):
        return None

    async def synthesize(self, text, cancellation):
        return SynthesizedAudio(
            samples=(np.sin(np.arange(24000) / 5) * 8000).astype(np.int16),
            sample_rate=24000,
            channels=1,
            synthesis_seconds=0.001,
        )


class StatisticsTests(TestCase):
    def test_nearest_rank_percentile(self) -> None:
        self.assertEqual(percentile([5, 1, 3, 2, 4], 0.9), 5)
        self.assertEqual(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9), 9)
        self.assertIsNone(percentile([], 0.5))

    def test_summary_counts_errors_and_ignores_missing_values(self) -> None:
        summary = summarize(
            [
                {"total_seconds": 2.0, "first_token_seconds": 0.5},
                {"total_seconds": 4.0, "first_token_seconds": None},
                {"error": "TimeoutError"},
            ]
        )
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(summary["total_seconds"]["median"], 3.0)
        self.assertEqual(summary["first_token_seconds"]["median"], 0.5)


class SuiteTests(IsolatedAsyncioTestCase):
    async def test_suite_separates_cold_and_warm_and_stores_no_content(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            settings = make_settings(root, audio_sample_rate=16000)
            real_db = settings.database_path

            async def provider_factory(_settings, allow_start=True):
                return StreamingProvider([])

            result = await run_suite(
                settings,
                profile="voice",
                repeat=2,
                provider_factory=provider_factory,
                stt_factory=lambda _settings: FakeSTT(),
                tts_factory=lambda _settings: FakeTTS(),
                resource_probe=lambda: {"vram_used_mib": None},
            )
            self.assertEqual(
                set(result["scenarios"]),
                {"text_short", "text_long", "text_tool", "voice_short", "voice_long"},
            )
            for name, data in result["scenarios"].items():
                self.assertEqual(data["cold"]["phase"], "cold")
                self.assertEqual(data["warm"]["runs"], 2)
                self.assertEqual(data["warm"]["errors"], 0, name)
                self.assertIsNotNone(data["cold"]["first_token_seconds"])
            voice = result["scenarios"]["voice_short"]["warm"]
            self.assertIn("first_audio_seconds", voice)
            self.assertIn("stt_seconds", voice)
            self.assertIn("estimated_sequential_first_audio_seconds", voice)
            dumped = json.dumps(result, ensure_ascii=False) + render_markdown(result)
            self.assertNotIn("que no debe aparecer", dumped)
            # La base real nunca se toca: el benchmark usa un directorio temporal.
            self.assertFalse(real_db.exists())

    async def test_text_profile_never_loads_voice(self) -> None:
        with TemporaryDirectory() as directory:
            settings = make_settings(Path(directory).resolve())

            async def provider_factory(_settings, allow_start=True):
                return StreamingProvider([])

            def forbidden(_settings):
                raise AssertionError("el perfil de texto no debe cargar voz")

            result = await run_suite(
                settings,
                profile="text",
                repeat=1,
                scenarios=["text_short"],
                provider_factory=provider_factory,
                stt_factory=forbidden,
                tts_factory=forbidden,
                resource_probe=lambda: {},
            )
            self.assertEqual(list(result["scenarios"]), ["text_short"])
            self.assertNotIn("tts_load_seconds", result["startup"])
