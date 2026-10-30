from __future__ import annotations

from ..config import Settings
from .base import ModelProvider
from .llama_cpp import LlamaCppProvider
from .llama_server import LlamaServerManager
from .ollama import OllamaProvider
from .openjarvis_engine import OpenJarvisProvider


async def create_model_provider(
    settings: Settings,
    *,
    allow_start: bool = True,
) -> ModelProvider:
    if settings.model_provider == "openjarvis":
        return OpenJarvisProvider(settings)
    if settings.model_provider == "ollama":
        return OllamaProvider(settings)
    if settings.model_provider == "llama_cpp":
        manager = LlamaServerManager(settings)
        if allow_start and settings.llama_auto_start:
            await manager.ensure_running()
        return LlamaCppProvider(settings, manager)
    raise ValueError(f"Proveedor no soportado: {settings.model_provider}")
