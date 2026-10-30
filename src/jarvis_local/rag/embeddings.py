from __future__ import annotations

import asyncio
import math
import os
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import Field

from ..cancellation import CancellationToken, OperationCancelled
from ..config import Settings
from ..models import StrictModel
from ..model_providers.http import require_loopback_url


class EmbeddingProviderError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class EmbeddingHealth(StrictModel):
    provider: str
    model: str
    available: bool
    ready: bool
    detail: str = ""


class EmbeddingBatch(StrictModel):
    vectors: tuple[tuple[float, ...], ...]
    model: str
    dimensions: int = Field(ge=1)


class EmbeddingProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def health(self) -> EmbeddingHealth:
        raise NotImplementedError

    @abstractmethod
    async def embed_documents(
        self, texts: list[str], cancellation: CancellationToken
    ) -> EmbeddingBatch:
        raise NotImplementedError

    @abstractmethod
    async def embed_query(
        self, query: str, cancellation: CancellationToken
    ) -> tuple[float, ...]:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class EmbeddingServerManager:
    """Proceso de embeddings separado para no desplazar el LLM de la GPU."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None
        parsed = urlparse(settings.embedding_base_url)
        self.host = "127.0.0.1"
        self.port = parsed.port or 8081
        self.health_url = f"http://{self.host}:{self.port}/health"
        self.log_path = settings.data_dir / "logs" / "embedding-server.log"

    def command(self) -> tuple[str, ...]:
        executable = self.settings.llama_server_executable
        model_path = self.settings.embedding_model_path
        if executable is None or not executable.is_file():
            raise EmbeddingProviderError(
                "server_not_found", f"No existe llama-server: {executable}"
            )
        if model_path is None or not model_path.is_file():
            raise EmbeddingProviderError(
                "model_not_found", f"No existe el GGUF de embeddings: {model_path}"
            )
        command = [
            str(executable),
            "--model",
            str(model_path),
            "--alias",
            self.settings.embedding_model,
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--ctx-size",
            str(self.settings.embedding_context_tokens),
            "--n-gpu-layers",
            str(self.settings.embedding_gpu_layers),
            "--parallel",
            "1",
            "--batch-size",
            str(self.settings.embedding_batch_size),
            "--ubatch-size",
            str(min(self.settings.embedding_batch_size, 512)),
            "--embedding",
            "--pooling",
            "last",
            "--cors-origins",
            "localhost",
            "--no-webui",
            "--log-verbosity",
            str(self.settings.llama_log_verbosity),
        ]
        if self.settings.embedding_gpu_layers != 0:
            command.extend(("--fit", "on", "--fit-target", str(self.settings.llama_fit_target_mib)))
        return tuple(command)

    async def is_ready(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                response = await client.get(self.health_url)
            return response.status_code == 200 and response.json().get("status") == "ok"
        except (httpx.HTTPError, ValueError):
            return False

    async def ensure_running(self) -> bool:
        if await self.is_ready():
            return False
        command = self.command()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = self.log_path.open("ab", buffering=0)
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(Path(command[0]).parent),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log_handle,
                stderr=asyncio.subprocess.STDOUT,
                creationflags=creation_flags,
            )
        finally:
            log_handle.close()

        deadline = time.monotonic() + self.settings.embedding_startup_timeout_seconds
        while time.monotonic() < deadline:
            if self.process.returncode is not None:
                raise EmbeddingProviderError(
                    "server_start_failed",
                    f"El servidor de embeddings terminó con código {self.process.returncode}; "
                    f"revisa {self.log_path}.",
                )
            if await self.is_ready():
                return True
            await asyncio.sleep(0.25)
        await self.stop()
        raise EmbeddingProviderError(
            "server_start_timeout",
            "El servidor de embeddings no quedó listo a tiempo.",
            retryable=True,
        )

    async def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()
            await process.wait()


class LlamaCppEmbeddingProvider(EmbeddingProvider):
    name = "llama_cpp"
    QUERY_INSTRUCTION = (
        "Instruct: Retrieve passages from the same local project that answer the "
        "user's question. Prefer direct evidence and Spanish-language relevance.\nQuery: "
    )

    def __init__(
        self,
        settings: Settings,
        manager: EmbeddingServerManager | None = None,
    ):
        self.settings = settings
        self.model = settings.embedding_model
        self.base_url = require_loopback_url(settings.embedding_base_url)
        self.api_root = self.base_url.removesuffix("/v1")
        self.manager = manager

    async def health(self) -> EmbeddingHealth:
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                response = await client.get(f"{self.api_root}/health")
                if response.status_code == 503:
                    return EmbeddingHealth(
                        provider=self.name,
                        model=self.model,
                        available=True,
                        ready=False,
                        detail="El modelo de embeddings se está cargando.",
                    )
                response.raise_for_status()
                models = await client.get(f"{self.base_url}/models")
                models.raise_for_status()
            ids = {
                str(item.get("id"))
                for item in models.json().get("data", [])
                if isinstance(item, dict)
            }
            ready = not ids or self.model in ids
            return EmbeddingHealth(
                provider=self.name,
                model=self.model,
                available=True,
                ready=ready,
                detail="Servidor de embeddings listo." if ready else f"Alias inesperado: {sorted(ids)}",
            )
        except (httpx.HTTPError, ValueError) as exc:
            return EmbeddingHealth(
                provider=self.name,
                model=self.model,
                available=False,
                ready=False,
                detail=str(exc),
            )

    async def embed_documents(
        self, texts: list[str], cancellation: CancellationToken
    ) -> EmbeddingBatch:
        return await self._embed(texts, cancellation)

    async def embed_query(
        self, query: str, cancellation: CancellationToken
    ) -> tuple[float, ...]:
        batch = await self._embed(
            [self.QUERY_INSTRUCTION + query.strip()], cancellation
        )
        return batch.vectors[0]

    async def _embed(
        self, texts: list[str], cancellation: CancellationToken
    ) -> EmbeddingBatch:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Los textos para embeddings no pueden estar vacíos.")
        cancellation.raise_if_cancelled()
        if (
            self.manager is not None
            and self.settings.embedding_auto_start
            and not await self.manager.is_ready()
        ):
            await self.manager.ensure_running()

        async def request() -> dict[str, Any]:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout_seconds, trust_env=False
            ) as client:
                response = await client.post(
                    f"{self.base_url}/embeddings",
                    json={
                        "model": self.model,
                        "input": texts,
                        "encoding_format": "float",
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Respuesta de embeddings no válida.")
                return payload

        request_task = asyncio.create_task(request())
        cancel_task = asyncio.create_task(cancellation.wait())
        try:
            done, _ = await asyncio.wait(
                {request_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancel_task in done:
                request_task.cancel()
                await asyncio.gather(request_task, return_exceptions=True)
                raise OperationCancelled(cancellation.reason or "Embeddings cancelados.")
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)
            payload = request_task.result()
        except OperationCancelled:
            raise
        except httpx.TimeoutException as exc:
            raise EmbeddingProviderError(
                "timeout", "El proveedor de embeddings excedió el timeout.", retryable=True
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingProviderError(
                "unavailable", f"Proveedor de embeddings no disponible: {exc}", retryable=True
            ) from exc
        finally:
            for task in (request_task, cancel_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(request_task, cancel_task, return_exceptions=True)

        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise EmbeddingProviderError(
                "invalid_response", "Cantidad inesperada de embeddings devueltos."
            )
        ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
        vectors: list[tuple[float, ...]] = []
        for item in ordered:
            raw = item.get("embedding") if isinstance(item, dict) else None
            if not isinstance(raw, list) or not raw:
                raise EmbeddingProviderError("invalid_response", "Vector de embedding vacío.")
            vectors.append(_normalize(tuple(float(value) for value in raw)))
        dimensions = len(vectors[0])
        if any(len(vector) != dimensions for vector in vectors):
            raise EmbeddingProviderError("invalid_response", "Dimensiones inconsistentes.")
        return EmbeddingBatch(
            vectors=tuple(vectors), model=self.model, dimensions=dimensions
        )

    async def aclose(self) -> None:
        if self.manager is not None:
            await self.manager.stop()


async def create_embedding_provider(
    settings: Settings, *, allow_start: bool = True
) -> EmbeddingProvider:
    if settings.embedding_provider == "disabled":
        raise EmbeddingProviderError(
            "disabled", "El proveedor de embeddings está deshabilitado."
        )
    if settings.embedding_provider == "llama_cpp":
        manager = EmbeddingServerManager(settings)
        if allow_start and settings.embedding_auto_start:
            await manager.ensure_running()
        return LlamaCppEmbeddingProvider(settings, manager)
    raise EmbeddingProviderError("unsupported", "Proveedor de embeddings no soportado.")


def _normalize(vector: tuple[float, ...]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise EmbeddingProviderError("invalid_response", "Embedding con norma cero.")
    return tuple(value / norm for value in vector)

