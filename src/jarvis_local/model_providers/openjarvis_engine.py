from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from ..cancellation import CancellationToken, OperationCancelled
from ..config import Settings
from .base import (
    ModelProvider,
    ModelProviderError,
    ModelStreamEvent,
    ModelUsage,
    ProviderHealth,
    _utf8_safe_value,
)


class OpenJarvisProvider(ModelProvider):
    """Usa los motores de inferencia de OpenJarvis como cerebro de Mark.

    Mark conserva su orquestador, política, presupuestos, memoria y voz; este
    proveedor solo sustituye la llamada al modelo por un motor de OpenJarvis
    (Ollama, vLLM, llama.cpp, MLX, ...), con streaming, tool calling y
    cancelación. Si el motor es Ollama y no está corriendo, se inicia oculto.
    """

    name = "openjarvis"

    def __init__(self, settings: Settings, *, engine: Any = None, engine_name: str = "") -> None:
        self.settings = settings
        self.model = settings.model
        self._engine = engine
        self._engine_name = engine_name or settings.openjarvis_engine
        self._lock = asyncio.Lock()

    async def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        async with self._lock:
            if self._engine is None:
                self._engine_name, self._engine = await asyncio.to_thread(self._resolve_engine)
        return self._engine

    def _resolve_engine(self) -> tuple[str, Any]:
        from openjarvis.core.config import load_config
        from openjarvis.engine import get_engine

        # Misma configuración que el panel OpenJarvis de Mark (hogar propio en
        # data/openjarvis); sin ella, la instalación de OpenJarvis del usuario.
        from ..openjarvis_bridge import CONFIG_FILE, openjarvis_home

        mark_config = openjarvis_home(self.settings) / CONFIG_FILE
        config = load_config(mark_config) if mark_config.is_file() else load_config()
        if self._engine_name in ("", "ollama"):
            from .ollama_launcher import ensure_ollama

            ensure_ollama(config)
        resolved = get_engine(config, self._engine_name or None)
        if resolved is None:
            raise ModelProviderError(
                "engine_unavailable",
                "OpenJarvis no encontró un motor de IA local. Abre Ollama o configura "
                "[llm] engine en config/jarvis.toml.",
                provider=self.name,
                retryable=True,
            )
        return resolved

    async def health(self) -> ProviderHealth:
        try:
            engine = await self._ensure_engine()
            models = [str(name) for name in await asyncio.to_thread(engine.list_models)]
        except Exception as exc:
            return ProviderHealth(
                provider=self.name,
                available=False,
                ready=False,
                model=self.model,
                detail=str(exc),
            )
        ready = _model_installed(self.model, models)
        return ProviderHealth(
            provider=self.name,
            available=True,
            ready=ready,
            model=self.model,
            version=f"OpenJarvis/{self._engine_name}",
            detail="Modelo disponible." if ready else "El modelo configurado no está instalado.",
        )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        cancellation: CancellationToken,
    ) -> AsyncIterator[ModelStreamEvent]:
        engine = await self._ensure_engine()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_output_tokens,
        }
        if tools:
            kwargs["tools"] = _utf8_safe_value(tools)
        if self._engine_name == "ollama":
            kwargs["think"] = self.settings.think
            kwargs["num_ctx"] = self.settings.context_tokens
        stream = engine.stream_full(to_openjarvis_messages(messages), **kwargs)
        done = False
        try:
            while True:
                chunk = await _next_or_cancel(stream, cancellation)
                if chunk is None:
                    break
                if chunk.content:
                    yield ModelStreamEvent(kind="text_delta", text=chunk.content)
                for position, call in enumerate(chunk.tool_calls or []):
                    function = call.get("function") or {}
                    arguments = function.get("arguments", "")
                    yield ModelStreamEvent(
                        kind="tool_delta",
                        tool_index=int(call.get("index", position)),
                        tool_id=str(call["id"]) if call.get("id") else None,
                        tool_name_delta=str(function.get("name") or ""),
                        tool_arguments_delta=(
                            arguments if isinstance(arguments, str)
                            else json.dumps(arguments, ensure_ascii=False)
                        ),
                    )
                if chunk.finish_reason:
                    done = True
                    yield ModelStreamEvent(
                        kind="done",
                        finish_reason=chunk.finish_reason,
                        usage=_usage(chunk.usage),
                    )
        except (OperationCancelled, ModelProviderError):
            raise
        except Exception as exc:
            raise ModelProviderError(
                "engine_error",
                f"El motor de OpenJarvis falló: {exc}",
                provider=self.name,
                retryable=True,
            ) from exc
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                try:
                    await close()
                except RuntimeError:
                    pass
        if not done:
            yield ModelStreamEvent(kind="done", finish_reason="stop")


def to_openjarvis_messages(messages: list[dict[str, Any]]) -> list[Any]:
    """Convierte el historial canónico OpenAI de Mark a mensajes de OpenJarvis."""

    from openjarvis.core.types import Message, Role, ToolCall

    converted = []
    for item in messages:
        calls = None
        if item.get("tool_calls"):
            calls = []
            for index, call in enumerate(item["tool_calls"]):
                function = call.get("function") or {}
                arguments = function.get("arguments", "{}")
                calls.append(
                    ToolCall(
                        id=str(call.get("id") or f"call_{index}"),
                        name=str(function.get("name") or ""),
                        arguments=(
                            arguments if isinstance(arguments, str)
                            else json.dumps(arguments, ensure_ascii=False)
                        ),
                    )
                )
        converted.append(
            Message(
                role=Role(str(item.get("role", "user"))),
                content=item.get("content") or "",
                name=item.get("name"),
                tool_calls=calls,
                tool_call_id=item.get("tool_call_id"),
            )
        )
    return converted


async def _next_or_cancel(stream: AsyncIterator[Any], cancellation: CancellationToken) -> Any:
    next_task = asyncio.ensure_future(anext(stream, None))
    cancel_task = asyncio.ensure_future(cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            {next_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if cancel_task in done:
            next_task.cancel()
            await asyncio.gather(next_task, return_exceptions=True)
            raise OperationCancelled(cancellation.reason or "Generación cancelada.")
        return next_task.result()
    finally:
        cancel_task.cancel()
        await asyncio.gather(cancel_task, return_exceptions=True)


def _usage(raw: dict[str, Any] | None) -> ModelUsage:
    raw = raw or {}

    def number(key: str) -> int | None:
        value = raw.get(key)
        return int(value) if isinstance(value, int) else None

    return ModelUsage(
        prompt_tokens=number("prompt_tokens"),
        completion_tokens=number("completion_tokens"),
        total_tokens=number("total_tokens"),
    )


def _model_installed(model: str, available: list[str]) -> bool:
    if model in available:
        return True
    # Ollama etiqueta "qwen3:8b" y acepta "qwen3" como "qwen3:latest".
    return ":" not in model and f"{model}:latest" in available
