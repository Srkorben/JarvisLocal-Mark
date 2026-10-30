from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from pydantic import ValidationError

from jarvis_local.config import Settings
from tests.mark.helpers import make_settings


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

    def test_production_voice_profile_uses_authorized_qwen_clone(self) -> None:
        # Decisión explícita posterior: la voz propia prima durante una llamada.
        # La autorización CUDA continúa siendo visible y revocable.
        root = Path(__file__).resolve().parents[2]
        settings = Settings.load(root / "config" / "jarvis.toml")
        self.assertEqual(settings.tts_provider, "qwen3_tts")
        self.assertEqual(settings.effective_tts, ("qwen3_tts", "cuda"))
        self.assertTrue(settings.tts_clone_allow_gpu)
        self.assertEqual(settings.tts_clone_device, "cuda")
        self.assertEqual(settings.tts_clone_temperature, 0.65)
        self.assertEqual(settings.tts_clone_top_k, 30)
        self.assertEqual(settings.tts_clone_top_p, 0.9)
        self.assertEqual(settings.tts_clone_subtalker_temperature, 0.65)
        self.assertEqual(settings.tts_clone_subtalker_top_k, 30)
        self.assertEqual(settings.tts_clone_subtalker_top_p, 0.9)
        self.assertTrue(
            settings.tts_clone_python.as_posix().replace("\\", "/").endswith(
                ".venv-qwen3-tts/Scripts/python.exe"
            )
        )

    def test_chatterbox_cuda_requires_explicit_gpu_authorization(self) -> None:
        root = Path(__file__).resolve().parents[2]
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
        root = Path(__file__).resolve().parents[2]
        settings = Settings.load(root / "config" / "jarvis.toml")
        blocked = settings.model_copy(
            update={"tts_provider": "xtts", "tts_clone_allow_gpu": False}
        )
        self.assertTrue(blocked.tts_gpu_blocked)
        self.assertEqual(blocked.effective_tts, ("piper", "cpu"))
        allowed = blocked.model_copy(update={"tts_clone_allow_gpu": True})
        self.assertEqual(allowed.effective_tts, ("xtts", "cuda"))

    def test_qwen_cuda_requires_explicit_gpu_authorization(self) -> None:
        root = Path(__file__).resolve().parents[2]
        settings = Settings.load(root / "config" / "jarvis.toml")
        blocked = settings.model_copy(update={"tts_clone_allow_gpu": False})
        self.assertTrue(blocked.tts_gpu_blocked)
        self.assertEqual(blocked.effective_tts, ("piper", "cpu"))
        allowed = blocked.model_copy(update={"tts_clone_allow_gpu": True})
        self.assertEqual(allowed.effective_tts, ("qwen3_tts", "cuda"))

