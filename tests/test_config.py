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

    def test_production_voice_profile_uses_isolated_cuda_worker(self) -> None:
        root = Path(__file__).resolve().parents[1]
        settings = Settings.load(root / "config" / "jarvis.toml")
        self.assertEqual(settings.tts_provider, "chatterbox")
        self.assertEqual(settings.tts_clone_device, "cuda")
        self.assertEqual(
            settings.tts_clone_python,
            (root / ".venv-chatterbox-cuda" / "Scripts" / "python.exe").resolve(),
        )

