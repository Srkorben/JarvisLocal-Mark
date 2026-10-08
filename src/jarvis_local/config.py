from __future__ import annotations

import os
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .budgets import BudgetLimits


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_dir: Path
    assistant_name: str = "Jarvis"
    language: str = "es"
    model_provider: str = "ollama"
    model_base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.5:4b-q4_K_M"
    context_tokens: int = Field(default=8192, ge=2048, le=16384)
    max_output_tokens: int = Field(default=1024, ge=32, le=8192)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    think: bool = False
    max_tool_rounds: int = Field(default=6, ge=1, le=30)
    request_timeout_seconds: float = Field(default=180, gt=0, le=600)
    llama_server_executable: Path | None = None
    llama_model_path: Path | None = None
    llama_auto_start: bool = False
    llama_startup_timeout_seconds: float = Field(default=120, gt=0, le=600)
    llama_gpu_layers: int | str = "auto"
    llama_fit_target_mib: int = Field(default=1024, ge=256, le=4096)
    llama_log_verbosity: int = Field(default=3, ge=0, le=9)
    llama_batch_size: int = Field(default=512, ge=32, le=4096)
    llama_ubatch_size: int = Field(default=128, ge=32, le=1024)
    llama_flash_attention: bool = True
    embedding_provider: str = "llama_cpp"
    embedding_base_url: str = "http://127.0.0.1:8081/v1"
    embedding_model: str = "qwen3-embedding-0.6b-q8_0"
    embedding_model_path: Path | None = None
    embedding_auto_start: bool = True
    embedding_startup_timeout_seconds: float = Field(default=60, gt=0, le=300)
    embedding_context_tokens: int = Field(default=2048, ge=512, le=32768)
    embedding_gpu_layers: int | str = 0
    embedding_batch_size: int = Field(default=2048, ge=32, le=8192)
    embedding_dimensions: int = Field(default=1024, ge=32, le=4096)
    rag_chunk_chars: int = Field(default=1200, ge=200, le=8000)
    rag_chunk_overlap_chars: int = Field(default=160, ge=0, le=2000)
    rag_max_document_bytes: int = Field(default=10_485_760, ge=1024, le=104_857_600)
    rag_vector_scan_limit: int = Field(default=20_000, ge=100, le=200_000)
    rag_default_top_k: int = Field(default=6, ge=1, le=25)
    rag_excluded_path_parts: tuple[str, ...] = (
        ".git", ".venv*", "*.egg-info", ".pytest_cache", "node_modules",
        "benchmarks", "data", "models", "runtime"
    )
    data_dir: Path
    database_path: Path
    allowed_roots: tuple[Path, ...]
    denied_path_parts: tuple[str, ...]
    max_read_bytes: int = Field(default=16384, ge=1024, le=1048576)
    max_file_operation_bytes: int = Field(default=104_857_600, ge=1024, le=1_073_741_824)
    auto_approve_max_risk: int = Field(default=1, ge=0, le=2)
    allowed_tools: frozenset[str]
    allowed_applications: frozenset[str]
    allowed_domains: frozenset[str]
    privileged_tools_enabled: bool = False
    remote_ai_enabled: bool = False
    visual_automation_enabled: bool = False
    max_steps_per_turn: int = Field(default=8, ge=1, le=100)
    max_runtime_seconds: float = Field(default=120, gt=0, le=3600)
    max_modified_files: int = Field(default=5, ge=0, le=1000)
    max_outbound_bytes: int = Field(default=0, ge=0)
    default_tool_timeout_seconds: float = Field(default=15, gt=0, le=300)
    log_level: str = "INFO"
    store_conversation_content: bool = False
    store_tool_output: bool = False

    @field_validator("model_base_url", "embedding_base_url")
    @classmethod
    def require_loopback_model_server(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("El servidor de modelos debe usar http://127.0.0.1.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("La URL del servidor local no puede contener credenciales ni parámetros.")
        return value.rstrip("/")

    @field_validator("model_provider")
    @classmethod
    def supported_backend(cls, value: str) -> str:
        if value not in {"ollama", "llama_cpp"}:
            raise ValueError("Proveedor de modelo no soportado.")
        return value

    @field_validator("embedding_provider")
    @classmethod
    def supported_embedding_backend(cls, value: str) -> str:
        if value not in {"llama_cpp", "disabled"}:
            raise ValueError("Proveedor de embeddings no soportado.")
        return value

    @field_validator("llama_gpu_layers", "embedding_gpu_layers")
    @classmethod
    def valid_gpu_layers(cls, value: int | str) -> int | str:
        if isinstance(value, int):
            if 0 <= value <= 999:
                return value
            raise ValueError("llama_cpp.gpu_layers debe estar entre 0 y 999.")
        normalized = value.casefold().strip()
        if normalized not in {"auto", "all"}:
            raise ValueError("llama_cpp.gpu_layers debe ser un entero, 'auto' o 'all'.")
        return normalized

    @field_validator("log_level")
    @classmethod
    def valid_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Nivel de log no válido.")
        return normalized

    @model_validator(mode="after")
    def validate_security_boundaries(self) -> "Settings":
        if not self.allowed_roots:
            raise ValueError("Debe existir al menos una raíz autorizada.")
        if not self.allowed_tools:
            raise ValueError("Debe existir al menos una herramienta autorizada.")
        return self

    def budget_limits(self) -> BudgetLimits:
        return BudgetLimits(
            max_steps=self.max_steps_per_turn,
            max_runtime_seconds=self.max_runtime_seconds,
            max_modified_files=self.max_modified_files,
            max_outbound_bytes=self.max_outbound_bytes,
        )

    @classmethod
    def load(cls, config_path: Path) -> "Settings":
        config_path = config_path.resolve()
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)

        project_dir = config_path.parent.parent.resolve()
        assistant = raw.get("assistant", {})
        llm = raw.get("llm", {})
        storage = raw.get("storage", {})
        security = raw.get("security", {})
        budgets = raw.get("budgets", {})
        logging_settings = raw.get("logging", {})
        embeddings = raw.get("embeddings", {})
        rag = raw.get("rag", {})

        data_dir_raw = Path(os.path.expandvars(str(storage.get("data_dir", "data"))))
        data_dir = data_dir_raw if data_dir_raw.is_absolute() else project_dir / data_dir_raw
        database_raw = Path(os.path.expandvars(str(storage.get("database", "jarvis.db"))))
        database_path = database_raw if database_raw.is_absolute() else data_dir / database_raw

        roots = tuple(
            Path(os.path.expandvars(str(value))).expanduser().resolve()
            for value in security.get("allowed_roots", [str(project_dir)])
        )

        return cls(
            project_dir=project_dir,
            assistant_name=str(assistant.get("name", "Jarvis")),
            language=str(assistant.get("language", "es")),
            model_provider=str(llm.get("provider", llm.get("backend", "ollama"))),
            model_base_url=str(llm.get("base_url", "http://127.0.0.1:11434")),
            model=str(llm.get("model", "qwen3.5:4b-q4_K_M")),
            context_tokens=int(llm.get("context_tokens", 8192)),
            max_output_tokens=int(llm.get("max_output_tokens", 1024)),
            temperature=float(llm.get("temperature", 0.2)),
            think=bool(llm.get("think", False)),
            max_tool_rounds=int(llm.get("max_tool_rounds", 6)),
            request_timeout_seconds=float(llm.get("request_timeout_seconds", 180)),
            llama_server_executable=_optional_project_path(
                project_dir, raw.get("llama_cpp", {}).get("executable")
            ),
            llama_model_path=_optional_project_path(
                project_dir, raw.get("llama_cpp", {}).get("model_path")
            ),
            llama_auto_start=bool(raw.get("llama_cpp", {}).get("auto_start", False)),
            llama_startup_timeout_seconds=float(
                raw.get("llama_cpp", {}).get("startup_timeout_seconds", 120)
            ),
            llama_gpu_layers=raw.get("llama_cpp", {}).get("gpu_layers", "auto"),
            llama_fit_target_mib=int(
                raw.get("llama_cpp", {}).get("fit_target_mib", 1024)
            ),
            llama_log_verbosity=int(
                raw.get("llama_cpp", {}).get("log_verbosity", 3)
            ),
            llama_batch_size=int(raw.get("llama_cpp", {}).get("batch_size", 512)),
            llama_ubatch_size=int(raw.get("llama_cpp", {}).get("ubatch_size", 128)),
            llama_flash_attention=bool(
                raw.get("llama_cpp", {}).get("flash_attention", True)
            ),
            embedding_provider=str(embeddings.get("provider", "llama_cpp")),
            embedding_base_url=str(
                embeddings.get("base_url", "http://127.0.0.1:8081/v1")
            ),
            embedding_model=str(
                embeddings.get("model", "qwen3-embedding-0.6b-q8_0")
            ),
            embedding_model_path=_optional_project_path(
                project_dir, embeddings.get("model_path")
            ),
            embedding_auto_start=bool(embeddings.get("auto_start", True)),
            embedding_startup_timeout_seconds=float(
                embeddings.get("startup_timeout_seconds", 60)
            ),
            embedding_context_tokens=int(embeddings.get("context_tokens", 2048)),
            embedding_gpu_layers=embeddings.get("gpu_layers", 0),
            embedding_batch_size=int(embeddings.get("batch_size", 2048)),
            embedding_dimensions=int(embeddings.get("dimensions", 1024)),
            rag_chunk_chars=int(rag.get("chunk_chars", 1200)),
            rag_chunk_overlap_chars=int(rag.get("chunk_overlap_chars", 160)),
            rag_max_document_bytes=int(
                rag.get("max_document_bytes", 10_485_760)
            ),
            rag_vector_scan_limit=int(rag.get("vector_scan_limit", 20_000)),
            rag_default_top_k=int(rag.get("default_top_k", 6)),
            rag_excluded_path_parts=tuple(
                str(value).casefold()
                for value in rag.get(
                    "excluded_path_parts",
                    [
                        ".git", ".venv*", "*.egg-info", ".pytest_cache",
                        "node_modules", "benchmarks", "data", "models", "runtime",
                    ],
                )
            ),
            data_dir=data_dir.resolve(),
            database_path=database_path.resolve(),
            allowed_roots=roots,
            denied_path_parts=tuple(str(x).casefold() for x in security.get("denied_path_parts", [])),
            max_read_bytes=int(security.get("max_read_bytes", 16384)),
            max_file_operation_bytes=int(
                security.get("max_file_operation_bytes", 104_857_600)
            ),
            auto_approve_max_risk=int(security.get("auto_approve_max_risk", 1)),
            allowed_tools=frozenset(str(x) for x in security.get("allowed_tools", [])),
            allowed_applications=frozenset(str(x).casefold() for x in security.get("allowed_applications", [])),
            allowed_domains=frozenset(str(x).casefold() for x in security.get("allowed_domains", [])),
            privileged_tools_enabled=bool(security.get("privileged_tools_enabled", False)),
            remote_ai_enabled=bool(security.get("remote_ai_enabled", False)),
            visual_automation_enabled=bool(security.get("visual_automation_enabled", False)),
            max_steps_per_turn=int(budgets.get("max_steps_per_turn", 8)),
            max_runtime_seconds=float(budgets.get("max_runtime_seconds", 120)),
            max_modified_files=int(budgets.get("max_modified_files", 5)),
            max_outbound_bytes=int(budgets.get("max_outbound_bytes", 0)),
            default_tool_timeout_seconds=float(budgets.get("default_tool_timeout_seconds", 15)),
            log_level=str(logging_settings.get("level", "INFO")),
            store_conversation_content=bool(logging_settings.get("store_conversation_content", False)),
            store_tool_output=bool(logging_settings.get("store_tool_output", False)),
        )


def _optional_project_path(project_dir: Path, value: object) -> Path | None:
    if value is None or not str(value).strip():
        return None
    candidate = Path(os.path.expandvars(str(value))).expanduser()
    return (candidate if candidate.is_absolute() else project_dir / candidate).resolve()

