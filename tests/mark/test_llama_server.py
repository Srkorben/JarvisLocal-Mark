from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, TestCase

from jarvis_local.model_providers import ModelProviderError
from jarvis_local.model_providers.llama_server import LlamaServerManager
from tests.mark.helpers import make_settings


class LlamaServerCommandTests(TestCase):
    def test_command_is_loopback_fixed_and_adaptive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "llama-server.exe"
            model = root / "model.gguf"
            executable.touch()
            model.touch()
            settings = make_settings(
                root,
                model_provider="llama_cpp",
                model_base_url="http://127.0.0.1:18080/v1",
                llama_server_executable=executable,
                llama_model_path=model,
                llama_gpu_layers="auto",
                llama_fit_target_mib=1024,
            )

            command = LlamaServerManager(settings).command()

            self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
            self.assertEqual(command[command.index("--port") + 1], "18080")
            self.assertEqual(command[command.index("--n-gpu-layers") + 1], "auto")
            self.assertEqual(command[command.index("--fit") + 1], "on")
            self.assertEqual(command[command.index("--fit-target") + 1], "1024")
            self.assertIn("--no-webui", command)
            self.assertNotIn("--tools", command)
            self.assertNotIn("--mcp", command)

    def test_missing_binary_is_structured_error(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            model = root / "model.gguf"
            model.touch()
            settings = make_settings(
                root,
                model_provider="llama_cpp",
                llama_server_executable=root / "missing.exe",
                llama_model_path=model,
            )
            with self.assertRaises(ModelProviderError) as caught:
                LlamaServerManager(settings).command()
            self.assertEqual(caught.exception.code, "server_not_found")


class LlamaServerReadinessTests(IsolatedAsyncioTestCase):
    async def test_unavailable_server_is_not_ready(self) -> None:
        with TemporaryDirectory() as directory:
            settings = make_settings(
                Path(directory),
                model_provider="llama_cpp",
                model_base_url="http://127.0.0.1:1/v1",
            )
            self.assertFalse(await LlamaServerManager(settings).is_ready())
