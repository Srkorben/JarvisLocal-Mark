import asyncio
import time
from unittest import IsolatedAsyncioTestCase, TestCase

import numpy as np

from jarvis_local.audio.base import AudioError
from jarvis_local.audio.models import SynthesizedAudio
from jarvis_local.audio.speech_stream import SentenceChunker, SpeechPipeline, clean_for_speech
from jarvis_local.cancellation import CancellationToken, OperationCancelled


class TimedTTS:
    def __init__(self, seconds: float = 0.05, fail_on: str | None = None) -> None:
        self.seconds = seconds
        self.fail_on = fail_on
        self.texts: list[str] = []
        self.events: list[tuple[str, float]] = []

    async def synthesize(self, text, cancellation):
        self.events.append(("synth_start", time.monotonic()))
        if self.fail_on is not None and self.fail_on in text:
            raise AudioError("synthesis_failed", "fallo de prueba", component="tts")
        await asyncio.sleep(self.seconds)
        cancellation.raise_if_cancelled()
        self.texts.append(text)
        self.events.append(("synth_end", time.monotonic()))
        return SynthesizedAudio(
            samples=np.zeros(10, dtype=np.int16),
            sample_rate=24000,
            channels=1,
            synthesis_seconds=self.seconds,
        )


class TimedPlayer:
    def __init__(self, seconds: float = 0.05) -> None:
        self.seconds = seconds
        self.events: list[tuple[str, float]] = []
        self.stopped = False

    async def play(self, audio, cancellation) -> float:
        self.events.append(("play_start", time.monotonic()))
        try:
            for _ in range(10):
                await asyncio.sleep(self.seconds / 10)
                cancellation.raise_if_cancelled()
        finally:
            self.events.append(("play_end", time.monotonic()))
        return self.seconds

    def stop(self) -> None:
        self.stopped = True


class ChunkerTests(TestCase):
    def test_emits_complete_sentences_as_they_arrive(self) -> None:
        chunker = SentenceChunker()
        self.assertEqual(chunker.feed("Hola, soy Ma"), [])
        self.assertEqual(chunker.feed("rk. ¿En qué te "), ["Hola, soy Mark."])
        self.assertEqual(chunker.feed("ayudo?\nLista:"), ["¿En qué te ayudo?"])
        self.assertEqual(chunker.flush(), ["Lista:"])
        self.assertEqual(chunker.flush(), [])

    def test_long_sentence_is_split_at_a_natural_pause(self) -> None:
        chunker = SentenceChunker(max_characters=80)
        text = "Primero revisé los documentos del proyecto activo, " * 3
        chunks = chunker.feed(text) + chunker.flush()
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 80 for chunk in chunks))
        self.assertEqual(" ".join(chunks), " ".join(text.split()))

    def test_markdown_is_not_read_aloud(self) -> None:
        self.assertEqual(clean_for_speech("**Hola** [Mark](https://x) `ok` #"), "Hola Mark ok")


class SpeechPipelineTests(IsolatedAsyncioTestCase):
    async def test_first_audio_starts_before_the_response_finishes(self) -> None:
        tts, player = TimedTTS(0.02), TimedPlayer(0.02)
        token = CancellationToken()
        first_audio: list[float] = []
        pipeline = SpeechPipeline(
            tts=tts, player=player, cancellation=token,
            on_first_audio=lambda: first_audio.append(time.monotonic()),
        )
        pipeline.feed("Primera frase completa. ")
        await asyncio.sleep(0.2)  # el LLM sigue generando
        generation_end = time.monotonic()
        pipeline.feed("Segunda frase.")
        await pipeline.finish()
        self.assertEqual(tts.texts, ["Primera frase completa.", "Segunda frase."])
        self.assertEqual(len(first_audio), 1)
        self.assertLess(first_audio[0], generation_end)
        self.assertEqual(pipeline.sentences, 2)
        self.assertAlmostEqual(pipeline.playback_seconds, 0.04, places=6)

    async def test_synthesis_of_next_sentence_overlaps_playback(self) -> None:
        tts, player = TimedTTS(0.05), TimedPlayer(0.2)
        pipeline = SpeechPipeline(tts=tts, player=player, cancellation=CancellationToken())
        pipeline.feed("Una. Dos. Tres.")
        await pipeline.finish()
        first_play_end = next(t for name, t in player.events if name == "play_end")
        second_synth_end = [t for name, t in tts.events if name == "synth_end"][1]
        self.assertLess(second_synth_end, first_play_end)

    async def test_cancellation_stops_synthesis_and_playback(self) -> None:
        tts, player = TimedTTS(0.05), TimedPlayer(1.0)
        token = CancellationToken()
        pipeline = SpeechPipeline(tts=tts, player=player, cancellation=token)
        pipeline.feed("Una frase larga de reproducción. Otra frase pendiente. Y otra más.")
        await asyncio.sleep(0.15)
        token.cancel("prueba")
        started = time.monotonic()
        with self.assertRaises(OperationCancelled):
            await pipeline.finish()
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(player.stopped)
        self.assertLess(len(tts.texts), 3)

    async def test_synthesis_error_is_raised_and_stops_playback(self) -> None:
        tts, player = TimedTTS(0.01, fail_on="Dos"), TimedPlayer(0.01)
        pipeline = SpeechPipeline(tts=tts, player=player, cancellation=CancellationToken())
        pipeline.feed("Una. Dos. Tres.")
        with self.assertRaises(AudioError):
            await asyncio.wait_for(pipeline.finish(), timeout=2)
        self.assertNotIn("Tres.", tts.texts)

    async def test_no_text_means_no_audio(self) -> None:
        tts, player = TimedTTS(), TimedPlayer()
        pipeline = SpeechPipeline(tts=tts, player=player, cancellation=CancellationToken())
        pipeline.feed("   ")
        await pipeline.finish()
        self.assertEqual(tts.texts, [])
        self.assertIsNone(pipeline.first_audio_at)


class StreamingOrchestrator:
    """Emite la respuesta frase a frase con retardo, como un LLM real."""

    def __init__(self, pieces: list[str], delay: float = 0.15, final: str | None = None):
        self.pieces = pieces
        self.delay = delay
        self.final = final
        self.finished_at: float | None = None

    async def chat(self, session_id, project, text, cancellation, on_text_delta=None, trace=None):
        for piece in self.pieces:
            await asyncio.sleep(self.delay)
            cancellation.raise_if_cancelled()
            if on_text_delta:
                on_text_delta(piece)
        self.finished_at = time.monotonic()
        if trace is not None:
            trace.mark("llm_done")
        return self.final if self.final is not None else "".join(self.pieces)


class VoiceSessionStreamingTests(IsolatedAsyncioTestCase):
    def build(self, root, orchestrator, tts, player):
        from pathlib import Path

        from jarvis_local.audio import VoiceSessionManager
        from jarvis_local.cancellation import CancellationController
        from jarvis_local.database import Database
        from jarvis_local.latency import LatencyLog
        from tests.test_audio import FakeRecorder, FakeSTT, audio_buffer

        root = Path(root)
        database = Database(root / "voice.db")
        project = database.create_project("Voz", root, make_active=True)
        manager = VoiceSessionManager(
            database=database,
            orchestrator=orchestrator,
            project=project,
            session_id=database.create_session(project_id=project.id),
            cancellation=CancellationController(),
            recorder=FakeRecorder(audio_buffer()),
            player=player,
            stt=FakeSTT(),
            tts=tts,
            min_record_seconds=0.25,
            min_rms=0.003,
            max_turn_seconds=5,
            max_record_seconds=30,
            latency_log=LatencyLog(root / "latency.jsonl"),
        )
        return manager, root / "latency.jsonl"

    async def test_voice_turn_speaks_before_the_llm_finishes(self) -> None:
        import json
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            orchestrator = StreamingOrchestrator(
                ["Hola, soy Mark. ", "Te cuento algo más ", "largo. ", "Y termino aquí."]
            )
            tts, player = TimedTTS(0.02), TimedPlayer(0.02)
            manager, log_path = self.build(directory, orchestrator, tts, player)
            self.assertTrue(await manager.start_recording())
            result = await (await manager.finish_recording())
            self.assertEqual(result.outcome, "success")
            first_play = next(t for name, t in player.events if name == "play_start")
            self.assertLess(first_play, orchestrator.finished_at)
            self.assertEqual(
                tts.texts, ["Hola, soy Mark.", "Te cuento algo más largo.", "Y termino aquí."]
            )
            self.assertIsNotNone(result.metrics.first_audio_seconds)
            record = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertEqual(record["interface"], "push_to_talk")
            self.assertEqual(record["outcome"], "success")
            self.assertLess(record["stages"]["first_audio"], record["stages"]["llm_done"])
            self.assertEqual(record["sentences_spoken"], 3)

    async def test_unstreamed_orchestrator_message_is_still_spoken(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            orchestrator = StreamingOrchestrator(
                [], final="Detuve la tarea porque alcanzó el límite seguro."
            )
            tts, player = TimedTTS(0.01), TimedPlayer(0.01)
            manager, _ = self.build(directory, orchestrator, tts, player)
            self.assertTrue(await manager.start_recording())
            result = await (await manager.finish_recording())
            self.assertEqual(result.outcome, "success")
            self.assertEqual(tts.texts, ["Detuve la tarea porque alcanzó el límite seguro."])

    async def test_text_turn_without_speech_never_calls_tts(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            tts, player = TimedTTS(0.01), TimedPlayer(0.01)
            manager, _ = self.build(
                directory, StreamingOrchestrator(["Respuesta escrita."], delay=0.01), tts, player
            )
            task = await manager.submit_text("hola", speak=False, queued_seconds=0.2)
            result = await task
            self.assertEqual(result.outcome, "success")
            self.assertEqual(tts.texts, [])
            self.assertEqual(player.events, [])

    async def test_cancel_during_speech_returns_quickly_and_idles(self) -> None:
        from tempfile import TemporaryDirectory

        from jarvis_local.audio import VoiceState

        with TemporaryDirectory() as directory:
            tts, player = TimedTTS(0.02), TimedPlayer(2.0)
            manager, _ = self.build(
                directory,
                StreamingOrchestrator(["Una frase. ", "Otra frase. ", "Fin."], delay=0.02),
                tts,
                player,
            )
            self.assertTrue(await manager.start_recording())
            task = await manager.finish_recording()
            await asyncio.sleep(0.3)
            started = time.monotonic()
            await manager.cancel_active("prueba")
            result = await asyncio.wait_for(task, timeout=1.5)
            self.assertEqual(result.outcome, "cancelled")
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertIs(manager.state, VoiceState.IDLE)
