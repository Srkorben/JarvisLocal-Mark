import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase

from jarvis_local.audio import (
    LazyAudioPlayer,
    LazySTTProvider,
    LazyTTSProvider,
    NoMicrophoneRecorder,
    VoiceSessionManager,
    VoiceState,
    run_text_request_loop,
)
from jarvis_local.audio.base import AudioError
from jarvis_local.audio.providers import PiperTTSProvider, create_tts_provider
from jarvis_local.cancellation import CancellationController, CancellationToken
from jarvis_local.database import Database
from tests.mark.helpers import make_settings
from tests.mark.test_audio import FakeOrchestrator, FakeSTT
from tests.mark.test_speech_stream import TimedPlayer, TimedTTS


class WarmTimedTTS(TimedTTS):
    async def warmup(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class Factory:
    """Cuenta cuántas veces se crea el servicio real."""

    def __init__(self, make):
        self.make = make
        self.calls = 0
        self.instances = []

    def __call__(self):
        self.calls += 1
        instance = self.make()
        self.instances.append(instance)
        return instance


class LazyProviderTests(IsolatedAsyncioTestCase):
    async def test_tts_is_created_on_first_synthesis_only(self) -> None:
        factory = Factory(lambda: WarmTimedTTS(0.0))
        tts = LazyTTSProvider(factory)
        self.assertFalse(tts.loaded)
        await tts.aclose()
        self.assertEqual(factory.calls, 0)
        await tts.synthesize("Hola.", CancellationToken())
        await tts.synthesize("Otra.", CancellationToken())
        self.assertEqual(factory.calls, 1)
        self.assertEqual(factory.instances[0].texts, ["Hola.", "Otra."])

    async def test_cancelled_turn_never_loads_the_model(self) -> None:
        factory = Factory(lambda: WarmTimedTTS(0.0))
        token = CancellationToken()
        token.cancel("prueba")
        with self.assertRaises(Exception):
            await LazyTTSProvider(factory).synthesize("Hola.", token)
        self.assertEqual(factory.calls, 0)

    async def test_stt_and_player_are_lazy(self) -> None:
        stt_factory = Factory(FakeSTT)
        player_factory = Factory(lambda: TimedPlayer(0.0))
        stt = LazySTTProvider(stt_factory)
        player = LazyAudioPlayer(player_factory)
        player.stop()
        await stt.aclose()
        self.assertEqual((stt_factory.calls, player_factory.calls), (0, 0))

    def test_text_runtime_recorder_never_opens_microphone(self) -> None:
        recorder = NoMicrophoneRecorder()
        with self.assertRaises(AudioError):
            recorder.start()
        recorder.abort()
        self.assertEqual(recorder.elapsed_seconds, 0.0)


class TextRuntimeTests(IsolatedAsyncioTestCase):
    def build(self, root: Path):
        database = Database(root / "text.db")
        project = database.create_project("Texto", root, make_active=True)
        self.stt_factory = Factory(FakeSTT)
        self.tts_factory = Factory(lambda: WarmTimedTTS(0.0))
        self.player_factory = Factory(lambda: TimedPlayer(0.0))
        self.orchestrator = FakeOrchestrator("Respuesta escrita.")
        return VoiceSessionManager(
            database=database,
            orchestrator=self.orchestrator,
            project=project,
            session_id=database.create_session(project_id=project.id),
            cancellation=CancellationController(),
            recorder=NoMicrophoneRecorder(),
            player=LazyAudioPlayer(self.player_factory),
            stt=LazySTTProvider(self.stt_factory),
            tts=LazyTTSProvider(self.tts_factory),
            min_record_seconds=0.25,
            min_rms=0.003,
            max_turn_seconds=5,
            max_record_seconds=30,
        )

    async def test_silent_text_turn_loads_no_audio_service(self) -> None:
        with TemporaryDirectory() as directory:
            manager = self.build(Path(directory))
            result = await (await manager.submit_text("hola", speak=False))
            self.assertEqual(result.outcome, "success")
            self.assertEqual(
                (self.stt_factory.calls, self.tts_factory.calls, self.player_factory.calls),
                (0, 0, 0),
            )
            await manager.close()

    async def test_spoken_text_turn_loads_only_tts_and_output(self) -> None:
        with TemporaryDirectory() as directory:
            manager = self.build(Path(directory))
            result = await (await manager.submit_text("hola", speak=True))
            self.assertEqual(result.outcome, "success")
            self.assertEqual(self.stt_factory.calls, 0)
            self.assertEqual(self.tts_factory.calls, 1)
            self.assertEqual(self.player_factory.calls, 1)
            self.assertEqual(self.tts_factory.instances[0].texts, ["Respuesta escrita."])
            await manager.close()

    async def test_loop_answers_panel_requests_and_closes_cleanly(self) -> None:
        with TemporaryDirectory() as directory:
            manager = self.build(Path(directory))
            requests = [
                {"text": "primero", "speak": False},
                {"text": "segundo", "speak": False},
            ]

            async def source():
                await asyncio.sleep(0.01)
                return requests.pop(0) if requests else None

            loop = asyncio.create_task(
                run_text_request_loop(manager, text_request_source=source, poll_seconds=0.01)
            )
            for _ in range(200):
                if len(self.orchestrator.calls) == 2 and manager.state is VoiceState.IDLE:
                    break
                await asyncio.sleep(0.01)
            loop.cancel()
            await asyncio.gather(loop, return_exceptions=True)
            self.assertEqual([text for _, text in self.orchestrator.calls], ["primero", "segundo"])
            self.assertEqual(self.tts_factory.calls, 0)


class TtsGpuGateTests(TestCase):
    def test_chatterbox_cuda_without_authorization_uses_piper_on_cpu(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = make_settings(
                root,
                tts_provider="chatterbox",
                tts_voice_path=root / "voice.onnx",
                tts_clone_device="cuda",
            )
            provider = create_tts_provider(settings)
            self.assertIsInstance(provider, PiperTTSProvider)


class PanelChatCLITests(IsolatedAsyncioTestCase):
    async def test_panel_chat_starts_llm_without_loading_audio(self) -> None:
        import re
        from unittest import mock

        from jarvis_local import audio, cli

        import logging

        # async_main instala su propio registro global; se restaura al final
        # y se cierra el archivo para que Windows pueda borrar el temporal.
        root_logger = logging.getLogger()
        saved_handlers, saved_level = list(root_logger.handlers), root_logger.level

        def restore_logging() -> None:
            for handler in root_logger.handlers:
                if handler not in saved_handlers:
                    handler.close()
            root_logger.handlers[:] = saved_handlers
            root_logger.setLevel(saved_level)

        self.addCleanup(restore_logging)
        source = Path(__file__).resolve().parents[2] / "config" / "jarvis.toml"
        with TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory).resolve()
            (root / "config").mkdir()
            # Cadena literal TOML: las rutas de Windows llevan barras inversas.
            # El temporal de Windows vive bajo AppData, que la política deniega.
            config = re.sub(
                r"allowed_roots = \[[^\]]*\]",
                lambda _: f"allowed_roots = ['{root}']",
                source.read_text(encoding="utf-8"),
            )
            config = re.sub(
                r"denied_path_parts = \[[^\]]*\]",
                lambda _: 'denied_path_parts = [".ssh"]',
                config,
            )
            (root / "config" / "jarvis.toml").write_text(config, encoding="utf-8")

            class FakeProvider:
                name = "fake"

                async def aclose(self) -> None:
                    return None

            started: list[bool] = []

            async def fake_model_provider(settings, *, allow_start):
                started.append(allow_start)
                return FakeProvider()

            def forbidden(settings):
                raise AssertionError("el chat escrito no debe crear STT ni TTS")

            with (
                mock.patch.object(cli, "create_model_provider", fake_model_provider),
                mock.patch.object(audio, "create_stt_provider", forbidden),
                mock.patch.object(audio, "create_tts_provider", forbidden),
            ):
                # Sin centro de control no hay cola de mensajes: termina sin
                # haber cargado audio y con el LLM ya cerrado.
                code = await cli.async_main(
                    ["--config", str(root / "config" / "jarvis.toml"), "--panel-chat"]
                )
            self.assertEqual(code, 1)
            self.assertEqual(started, [True])


class PanelCancelTests(IsolatedAsyncioTestCase):
    async def test_panel_cancel_stops_the_active_text_turn(self) -> None:
        with TemporaryDirectory() as directory:
            manager = TextRuntimeTests.build(self, Path(directory))
            self.orchestrator.wait_for_cancel = True
            requests = [{"text": "tarea larga", "speak": False}]
            cancel_now = asyncio.Event()

            async def source():
                if requests:
                    return requests.pop(0)
                await cancel_now.wait()
                cancel_now.clear()
                return {"cancel": True}

            loop = asyncio.create_task(
                run_text_request_loop(manager, text_request_source=source, poll_seconds=0.01)
            )
            for _ in range(200):
                if manager.state is VoiceState.PROCESSING:
                    break
                await asyncio.sleep(0.01)
            self.assertIs(manager.state, VoiceState.PROCESSING)
            cancel_now.set()
            for _ in range(200):
                if manager.last_result is not None:
                    break
                await asyncio.sleep(0.01)
            loop.cancel()
            await asyncio.gather(loop, return_exceptions=True)
            self.assertEqual(manager.last_result.outcome, "cancelled")


class ChatTranscriptTests(TestCase):
    def request(self, text="hola", request_id="r1"):
        return {"id": request_id, "text": text, "speak": False, "submitted_at": "2026-10-11T00:00:00+00:00"}

    def test_tracks_a_turn_until_the_final_answer(self) -> None:
        from jarvis_local.control_center.text_chat import ChatTranscript

        transcript = ChatTranscript()
        transcript.start(self.request())
        # Antes de procesar, un "idle" del arranque no cierra el turno.
        transcript.observe({"state": "idle", "transcript": "", "response": ""})
        self.assertEqual(transcript.snapshot()[0]["outcome"], "pending")
        transcript.observe({"state": "processing", "transcript": "hola", "response": "Ho"})
        transcript.observe({"state": "processing", "transcript": "hola", "response": "Hola, soy Mark."})
        transcript.observe({"state": "idle", "transcript": "hola", "response": "Hola, soy Mark."})
        turn = transcript.snapshot()[0]
        self.assertEqual((turn["outcome"], turn["assistant"]), ("done", "Hola, soy Mark."))
        self.assertNotIn("_active", turn)

    def test_ignores_foreign_voice_turns_and_records_cancel_and_errors(self) -> None:
        from jarvis_local.control_center.text_chat import ChatTranscript

        transcript = ChatTranscript()
        transcript.start(self.request("primero", "r1"))
        transcript.observe({"state": "processing", "transcript": "turno de voz", "response": "otra cosa"})
        self.assertEqual(transcript.snapshot()[0]["assistant"], "")
        transcript.mark_cancel()
        transcript.observe({"state": "processing", "transcript": "primero", "response": "parcial"})
        transcript.observe({"state": "idle", "transcript": "primero", "response": "parcial"})
        self.assertEqual(transcript.snapshot()[0]["outcome"], "cancelled")
        transcript.start(self.request("segundo", "r2"))
        transcript.observe({"state": "error", "transcript": "segundo", "error": "fallo del modelo"})
        self.assertEqual(transcript.snapshot()[1]["error"], "fallo del modelo")
        transcript.start(self.request("tercero", "r3"))
        transcript.observe({"state": "offline"})
        self.assertEqual(transcript.snapshot()[2]["outcome"], "error")

    def test_clear_keeps_the_running_turn_and_history_is_bounded(self) -> None:
        from jarvis_local.control_center.text_chat import ChatTranscript

        transcript = ChatTranscript(max_turns=3)
        for index in range(4):
            transcript.start(self.request(f"m{index}", f"r{index}"))
            transcript.observe({"state": "processing", "transcript": f"m{index}", "response": "ok"})
            transcript.observe({"state": "idle", "transcript": f"m{index}", "response": "ok"})
        self.assertEqual([turn["user"] for turn in transcript.snapshot()], ["m1", "m2", "m3"])
        transcript.start(self.request("en curso", "r9"))  # desplaza a "m1" (límite 3)
        self.assertEqual(transcript.clear(), 2)
        self.assertEqual([turn["user"] for turn in transcript.snapshot()], ["en curso"])
