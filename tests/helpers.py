from pathlib import Path
import hashlib
import math

from jarvis_local.cancellation import CancellationToken
from jarvis_local.config import Settings
from jarvis_local.rag import EmbeddingBatch, EmbeddingHealth, EmbeddingProvider


def make_settings(root: Path, **updates) -> Settings:
    values = {
        "project_dir": root,
        "assistant_name": "Mark",
        "language": "es",
        "model_provider": "ollama",
        "model_base_url": "http://127.0.0.1:11434",
        "model": "test",
        "context_tokens": 4096,
        "max_output_tokens": 256,
        "temperature": 0.0,
        "think": False,
        "max_tool_rounds": 3,
        "request_timeout_seconds": 10,
        "llama_server_executable": None,
        "llama_model_path": None,
        "llama_auto_start": False,
        "llama_startup_timeout_seconds": 10,
        "llama_gpu_layers": "auto",
        "llama_fit_target_mib": 1024,
        "llama_log_verbosity": 3,
        "llama_batch_size": 128,
        "llama_ubatch_size": 64,
        "llama_flash_attention": True,
        "embedding_provider": "disabled",
        "embedding_base_url": "http://127.0.0.1:8081/v1",
        "embedding_model": "test-embedding",
        "embedding_model_path": None,
        "embedding_auto_start": False,
        "embedding_startup_timeout_seconds": 10,
        "embedding_context_tokens": 1024,
        "embedding_gpu_layers": 0,
        "embedding_batch_size": 256,
        "embedding_dimensions": 32,
        "rag_chunk_chars": 400,
        "rag_chunk_overlap_chars": 40,
        "rag_max_document_bytes": 1_048_576,
        "rag_vector_scan_limit": 1000,
        "rag_default_top_k": 5,
        "rag_excluded_path_parts": (
            ".git", ".venv*", "*.egg-info", ".pytest_cache", "benchmarks",
            "data", "models", "runtime",
        ),
        "data_dir": root / "data",
        "database_path": root / "data" / "test.db",
        "allowed_roots": (root,),
        # TemporaryDirectory on Windows is normally created below AppData. Keep
        # the test root usable and exercise denylisted components explicitly in
        # policy tests instead of weakening the production defaults.
        "denied_path_parts": (".ssh",),
        "max_read_bytes": 4096,
        "max_file_operation_bytes": 10_485_760,
        "auto_approve_max_risk": 1,
        "allowed_tools": frozenset({"get_current_time", "list_directory", "search_files", "read_text_file"}),
        "allowed_applications": frozenset(),
        "allowed_domains": frozenset(),
        "privileged_tools_enabled": False,
        "remote_ai_enabled": False,
        "visual_automation_enabled": False,
        "max_steps_per_turn": 4,
        "max_runtime_seconds": 10,
        "max_modified_files": 2,
        "max_outbound_bytes": 0,
        "default_tool_timeout_seconds": 2,
        "log_level": "INFO",
        "store_conversation_content": False,
        "store_tool_output": False,
    }
    values.update(updates)
    return Settings(**values)


class DeterministicEmbeddingProvider(EmbeddingProvider):
    name = "deterministic"
    model = "deterministic-test-v1"

    def __init__(self, dimensions: int = 32):
        self.dimensions = dimensions

    async def health(self) -> EmbeddingHealth:
        return EmbeddingHealth(
            provider=self.name,
            model=self.model,
            available=True,
            ready=True,
        )

    async def embed_documents(
        self, texts: list[str], cancellation: CancellationToken
    ) -> EmbeddingBatch:
        vectors = tuple(self._vector(text, cancellation) for text in texts)
        return EmbeddingBatch(
            vectors=vectors,
            model=self.model,
            dimensions=self.dimensions,
        )

    async def embed_query(
        self, query: str, cancellation: CancellationToken
    ) -> tuple[float, ...]:
        return self._vector(query, cancellation)

    def _vector(self, text: str, cancellation: CancellationToken) -> tuple[float, ...]:
        cancellation.raise_if_cancelled()
        aliases = {
            "automóvil": "coche",
            "automovil": "coche",
            "vehículo": "coche",
            "vehiculo": "coche",
            "carro": "coche",
        }
        values = [0.0] * self.dimensions
        for raw in text.casefold().replace(".", " ").replace(",", " ").split():
            token = aliases.get(raw.strip("¿?¡!:#*"), raw.strip("¿?¡!:#*"))
            if not token:
                continue
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            values[index] += -1.0 if digest[4] & 1 else 1.0
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return tuple(value / norm for value in values)
