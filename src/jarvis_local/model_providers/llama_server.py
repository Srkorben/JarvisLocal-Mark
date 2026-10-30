from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import Settings
from .base import ModelProviderError


class LlamaServerManager:
    """Inicia un llama-server no elevado con argumentos cerrados y loopback."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None
        parsed = urlparse(settings.model_base_url)
        self.host = "127.0.0.1"
        self.port = parsed.port or 8080
        self.health_url = f"http://{self.host}:{self.port}/health"
        self.log_path = settings.data_dir / "logs" / "llama-server.log"

    def command(self) -> tuple[str, ...]:
        executable = self.settings.llama_server_executable
        model_path = self.settings.llama_model_path
        if executable is None:
            raise ModelProviderError(
                "server_not_configured",
                "No se configuró llama_cpp.executable.",
                provider="llama_cpp",
            )
        if model_path is None:
            raise ModelProviderError(
                "model_not_configured",
                "No se configuró llama_cpp.model_path.",
                provider="llama_cpp",
            )
        if not executable.is_file():
            raise ModelProviderError(
                "server_not_found",
                f"No existe llama-server: {executable}",
                provider="llama_cpp",
            )
        if not model_path.is_file():
            raise ModelProviderError(
                "model_not_found",
                f"No existe el GGUF configurado: {model_path}",
                provider="llama_cpp",
            )
        command = [
            str(executable),
            "--model",
            str(model_path),
            "--alias",
            self.settings.model,
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--ctx-size",
            str(self.settings.context_tokens),
            "--n-gpu-layers",
            str(self.settings.llama_gpu_layers),
            "--fit",
            "on",
            "--fit-target",
            str(self.settings.llama_fit_target_mib),
            "--parallel",
            "1",
            "--batch-size",
            str(self.settings.llama_batch_size),
            "--ubatch-size",
            str(self.settings.llama_ubatch_size),
            "--jinja",
            "--metrics",
            "--cors-origins",
            "localhost",
            "--no-webui",
            "--log-verbosity",
            str(self.settings.llama_log_verbosity),
        ]
        if self.settings.llama_flash_attention:
            command.extend(("--flash-attn", "on"))
        return tuple(command)

    async def is_ready(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                response = await client.get(self.health_url)
            return response.status_code == 200 and response.json().get("status") == "ok"
        except (httpx.HTTPError, ValueError):
            return False

    async def ensure_running(self) -> bool:
        """Devuelve True si inició un proceso; False si ya había uno listo."""

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

        deadline = time.monotonic() + self.settings.llama_startup_timeout_seconds
        while time.monotonic() < deadline:
            if self.process.returncode is not None:
                raise ModelProviderError(
                    "server_start_failed",
                    f"llama-server terminó con código {self.process.returncode}. "
                    f"Revisa {self.log_path}",
                    provider="llama_cpp",
                )
            if await self.is_ready():
                return True
            await asyncio.sleep(0.25)
        await self.stop()
        raise ModelProviderError(
            "server_start_timeout",
            f"llama-server no quedó listo en {self.settings.llama_startup_timeout_seconds:g}s.",
            provider="llama_cpp",
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
