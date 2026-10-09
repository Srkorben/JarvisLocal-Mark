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

    def test_rejects_unsupported_voice_pronunciation_options(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for field, value in (
                ("tts_clone_accent_source", "chileno"),
                ("tts_clone_reference_processing", "denoise"),
                ("tts_clone_s3gen_file", "..\\s3gen_v3.pt"),
                ("tts_clone_s3gen_file", "s3gen_v3.bin"),
                ("tts_clone_seed", -1),
            ):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError):
                        make_settings(root, **{field: value})

    def test_voice_pronunciation_profile_is_loaded_from_toml(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config" / "jarvis.toml"
            config.parent.mkdir()
            config.write_text(
                "[security]\n"
                f"allowed_roots = ['{root.as_posix()}']\n"
                "allowed_tools = ['get_current_time']\n"
                "[voice_clone]\n"
                "s3gen_file = 's3gen_v3.pt'\n"
                "accent_source = 'Model'\n"
                "reference_processing = 'clean'\n"
                "seed = 42\n",
                encoding="utf-8",
            )
            settings = Settings.load(config)
            self.assertEqual(settings.tts_clone_s3gen_file, "s3gen_v3.pt")
            self.assertEqual(settings.tts_clone_accent_source, "model")
            self.assertEqual(settings.tts_clone_reference_processing, "clean")
            self.assertEqual(settings.tts_clone_seed, 42)

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

