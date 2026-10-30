from __future__ import annotations

import asyncio
import inspect
import json
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from pydantic import Field

from ..cancellation import CancellationToken, OperationCancelled
from ..models import StrictModel


TextDeltaCallback = Callable[[str], None | Awaitable[None]]


class ModelProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        provider: str,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.retryable = retryable
        self.status_code = status_code

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "provider": self.provider,
            "retryable": self.retryable,
            "status_code": self.status_code,
        }


class ProviderHealth(StrictModel):
    provider: str
    available: bool
    ready: bool
    model: str
    version: str | None = None
    detail: str = ""


class ModelToolCall(StrictModel):
    id: str | None = None
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    arguments: dict[str, Any]


class ModelUsage(StrictModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ModelMetrics(StrictModel):
    started_at_monotonic: float
    first_token_seconds: float | None = None
    total_seconds: float
    tokens_per_second: float | None = None
    provider_metrics: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(StrictModel):
    content: str = ""
    tool_calls: tuple[ModelToolCall, ...] = ()
    finish_reason: str | None = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    metrics: ModelMetrics


class ModelStreamEvent(StrictModel):
    kind: str
    text: str = ""
    tool_index: int | None = None
    tool_id: str | None = None
    tool_name_delta: str = ""
    tool_arguments_delta: str = ""
    finish_reason: str | None = None
    usage: ModelUsage | None = None
    provider_metrics: dict[str, Any] = Field(default_factory=dict)


class ModelProvider(ABC):
    name: str
    model: str

    @abstractmethod
    async def health(self) -> ProviderHealth:
        raise NotImplementedError

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        cancellation: CancellationToken,
    ) -> AsyncIterator[ModelStreamEvent]:
        raise NotImplementedError

    async def complete_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        cancellation: CancellationToken,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> ModelResponse:
        started = time.monotonic()
        first_token_seconds: float | None = None
        content_parts: list[str] = []
        tool_parts: dict[int, dict[str, str | None]] = {}
        finish_reason: str | None = None
        usage = ModelUsage()
        provider_metrics: dict[str, Any] = {}

        async for event in self.stream_chat(messages, tools, cancellation):
            cancellation.raise_if_cancelled()
            if event.kind == "text_delta" and event.text:
                if first_token_seconds is None:
                    first_token_seconds = time.monotonic() - started
                safe_delta = _utf8_safe_text(event.text)
                content_parts.append(safe_delta)
                if on_text_delta is not None:
                    callback_result = on_text_delta(safe_delta)
                    if inspect.isawaitable(callback_result):
                        await callback_result
            elif event.kind == "tool_delta":
                if first_token_seconds is None:
                    first_token_seconds = time.monotonic() - started
                if event.tool_index is None:
                    raise ModelProviderError(
                        "invalid_response",
                        "El proveedor emitió una herramienta sin índice.",
                        provider=self.name,
                    )
                part = tool_parts.setdefault(
                    event.tool_index,
                    {"id": None, "name": "", "arguments": ""},
                )
                part["id"] = event.tool_id or part["id"]
                part["name"] = str(part["name"] or "") + event.tool_name_delta
                part["arguments"] = str(part["arguments"] or "") + event.tool_arguments_delta
            elif event.kind == "done":
                finish_reason = event.finish_reason
                usage = event.usage or usage
                provider_metrics.update(event.provider_metrics)

        cancellation.raise_if_cancelled()
        tool_calls: list[ModelToolCall] = []
        for index in sorted(tool_parts):
            part = tool_parts[index]
            raw_arguments = str(part["arguments"] or "{}")
            try:
                arguments = _utf8_safe_value(json.loads(raw_arguments))
            except json.JSONDecodeError as exc:
                raise ModelProviderError(
                    "invalid_tool_arguments",
                    f"La herramienta devolvió JSON inválido: {exc}",
                    provider=self.name,
                ) from exc
            if not isinstance(arguments, dict):
                raise ModelProviderError(
                    "invalid_tool_arguments",
                    "Los argumentos de herramienta deben ser un objeto JSON.",
                    provider=self.name,
                )
            try:
                tool_calls.append(
                    ModelToolCall(
                        id=str(part["id"]) if part["id"] else None,
                        name=str(part["name"] or ""),
                        arguments=arguments,
                    )
                )
            except ValueError as exc:
                raise ModelProviderError(
                    "invalid_tool_call",
                    f"Llamada de herramienta inválida: {exc}",
                    provider=self.name,
                ) from exc

        total_seconds = time.monotonic() - started
        completion_tokens = usage.completion_tokens
        tokens_per_second = (
            completion_tokens / total_seconds
            if completion_tokens is not None and total_seconds > 0
            else None
        )
        return ModelResponse(
            content="".join(content_parts),
            tool_calls=tuple(tool_calls),
            finish_reason=finish_reason,
            usage=usage,
            metrics=ModelMetrics(
                started_at_monotonic=started,
                first_token_seconds=first_token_seconds,
                total_seconds=total_seconds,
                tokens_per_second=tokens_per_second,
                provider_metrics=provider_metrics,
            ),
        )

    async def aclose(self) -> None:
        return None


def _utf8_safe_text(value: str) -> str:
    """Reemplaza sustitutos aislados que no pueden serializarse como UTF-8."""

    return value.encode("utf-8", errors="replace").decode("utf-8")


def _utf8_safe_value(value: Any) -> Any:
    """Limpia recursivamente datos no confiables antes de reutilizarlos en JSON."""

    if isinstance(value, str):
        return _utf8_safe_text(value)
    if isinstance(value, dict):
        return {
            _utf8_safe_text(str(key)): _utf8_safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_utf8_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_utf8_safe_value(item) for item in value)
    return value


async def next_line_or_cancel(
    iterator: AsyncIterator[str],
    cancellation: CancellationToken,
) -> str:
    line_task = asyncio.create_task(anext(iterator))
    cancel_task = asyncio.create_task(cancellation.wait())
    try:
        done, pending = await asyncio.wait(
            {line_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_task in done:
            line_task.cancel()
            await asyncio.gather(line_task, return_exceptions=True)
            raise OperationCancelled(cancellation.reason or "Generación cancelada.")
        cancel_task.cancel()
        await asyncio.gather(cancel_task, return_exceptions=True)
        return line_task.result()
    finally:
        for task in (line_task, cancel_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(line_task, cancel_task, return_exceptions=True)
