from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from pydantic import ValidationError

from jarvis_local.config import Settings
from tests.helpers import make_settings


class ConfigTests(TestCase):
    def test_rejects_non_loopback_model_server(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValidationError):
                make_settings(Path(directory), model_base_url="http://192.168.1.20:11434")

    def test_rejects_excessive_context_for_target_hardware(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValidationError):
                make_settings(Path(directory), context_tokens=131072)

    def test_rejects_backend_without_an_implemented_client(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValidationError):
                make_settings(Path(directory), model_provider="unknown")

    def test_accepts_adaptive_gpu_offload(self) -> None:
        with TemporaryDirectory() as directory:
            settings = make_settings(Path(directory), llama_gpu_layers="auto")
            self.assertEqual(settings.llama_gpu_layers, "auto")

    def test_rejects_unknown_gpu_offload_mode(self) -> None:
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValidationError):
                make_settings(Path(directory), llama_gpu_layers="maximum")

    def test_production_voice_profile_uses_authorized_xtts_clone(self) -> None:
        # Decisión explícita posterior: la voz propia prima durante una llamada.
        # La autorización CUDA continúa siendo visible y revocable.
        root = Path(__file__).resolve().parents[1]
        settings = Settings.load(root / "config" / "jarvis.toml")
        self.assertEqual(settings.tts_provider, "xtts")
        self.assertEqual(settings.effective_tts, ("xtts", "cuda"))
        self.assertTrue(settings.tts_clone_allow_gpu)
        self.assertEqual(settings.tts_clone_device, "cuda")
        self.assertTrue(
            settings.tts_clone_python.as_posix().replace("\\", "/").endswith(
                ".venv-xtts/Scripts/python.exe"
            )
        )

    def test_chatterbox_cuda_requires_explicit_gpu_authorization(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings = Settings.load(root / "config" / "jarvis.toml")
        blocked = settings.model_copy(
            update={"tts_provider": "chatterbox", "tts_clone_allow_gpu": False}
        )
        self.assertTrue(blocked.tts_gpu_blocked)
        self.assertEqual(blocked.effective_tts, ("piper", "cpu"))
        allowed = blocked.model_copy(update={"tts_clone_allow_gpu": True})
        self.assertEqual(allowed.effective_tts, ("chatterbox", "cuda"))
        on_cpu = blocked.model_copy(update={"tts_clone_device": "cpu"})
        self.assertEqual(on_cpu.effective_tts, ("chatterbox", "cpu"))

    def test_xtts_cuda_requires_explicit_gpu_authorization(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings = Settings.load(root / "config" / "jarvis.toml")
        blocked = settings.model_copy(update={"tts_clone_allow_gpu": False})
        self.assertTrue(blocked.tts_gpu_blocked)
        self.assertEqual(blocked.effective_tts, ("piper", "cpu"))
        allowed = blocked.model_copy(update={"tts_clone_allow_gpu": True})
        self.assertEqual(allowed.effective_tts, ("xtts", "cuda"))

