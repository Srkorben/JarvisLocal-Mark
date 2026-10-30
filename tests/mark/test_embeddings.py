from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from jarvis_local.rag import EmbeddingServerManager, LlamaCppEmbeddingProvider
from tests.mark.helpers import make_settings


class EmbeddingServerTests(TestCase):
    def test_command_is_local_cpu_only_and_has_no_agent_tools(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "llama-server.exe"
            model = root / "embedding.gguf"
            executable.touch()
            model.touch()
            settings = make_settings(
                root,
                llama_server_executable=executable,
                embedding_model_path=model,
                embedding_provider="llama_cpp",
                embedding_base_url="http://127.0.0.1:18081/v1",
                embedding_gpu_layers=0,
            )

            command = EmbeddingServerManager(settings).command()

            self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
            self.assertEqual(command[command.index("--port") + 1], "18081")
            self.assertEqual(command[command.index("--n-gpu-layers") + 1], "0")
            self.assertEqual(command[command.index("--pooling") + 1], "last")
            self.assertIn("--embedding", command)
            self.assertIn("--no-webui", command)
            self.assertNotIn("--tools", command)
            self.assertNotIn("--agent", command)

    def test_qwen_query_instruction_is_applied_only_at_query_boundary(self) -> None:
        instruction = LlamaCppEmbeddingProvider.QUERY_INSTRUCTION
        self.assertTrue(instruction.startswith("Instruct:"))
        self.assertIn("\nQuery: ", instruction)

