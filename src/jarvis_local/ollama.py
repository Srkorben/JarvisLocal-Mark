"""Compatibilidad de importación para el adaptador Ollama de Fase 0.

El núcleo usa ahora ``ModelProvider``. Código nuevo debe importar
``OllamaProvider`` desde ``jarvis_local.model_providers.ollama``.
"""

from .model_providers.base import ModelProviderError as OllamaError
from .model_providers.ollama import OllamaProvider

OllamaClient = OllamaProvider

__all__ = ["OllamaClient", "OllamaError", "OllamaProvider"]
