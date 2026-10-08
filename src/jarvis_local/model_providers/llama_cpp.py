from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..cancellation import CancellationToken
from ..config import Settings
from .base import ModelProvider, ModelStreamEvent, ModelUsage, ProviderHealth
from .http import require_loopback_url, stream_json_lines
from .llama_server import LlamaServerManager


class LlamaCppProvider(ModelProvider):
    name = "llama_cpp"

    def __init__(self, settings: Settings, manager: LlamaServerManager | None = None):
        self.settings = settings
        self.model = settings.model
        self.base_url = require_loopback_url(settings.model_base_url)
        self.api_root = self.base_url.removesuffix("/v1")
        self.manager = manager

    async def health(self) -> ProviderHealth:
        try:
            timeout = httpx.Timeout(min(self.settings.request_timeout_seconds, 10))
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.get(f"{self.api_root}/health")
                if response.status_code == 503:
                    return ProviderHealth(
                        provider=self.name,
                        available=True,
                        ready=False,
                        model=self.model,
                        detail="llama-server está cargando el modelo.",
                    )
                response.raise_for_status()
                models_response = await client.get(f"{self.base_url}/models")
                models_response.raise_for_status()
            model_ids = {
                str(item.get("id"))
                for item in models_response.json().get("data", [])
                if isinstance(item, dict)
            }
            ready = not model_ids or self.model in model_ids
            return ProviderHealth(
                provider=self.name,
                available=True,
                ready=ready,
                model=self.model,
                detail=(
                    "Servidor y modelo listos."
                    if ready
                    else f"El servidor no publicó el alias esperado; modelos: {sorted(model_ids)}"
                ),
            )
        except (httpx.HTTPError, ValueError) as exc:
            return ProviderHealth(
                provider=self.name,
                available=False,
                ready=False,
                model=self.model,
                detail=str(exc),
            )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        cancellation: CancellationToken,
    ) -> AsyncIterator[ModelStreamEvent]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_output_tokens,
            "chat_template_kwargs": {"enable_thinking": self.settings.think},
        }
        async for item in stream_json_lines(
            provider=self.name,
            url=f"{self.base_url}/chat/completions",
            payload=payload,
            cancellation=cancellation,
            timeout_seconds=self.settings.request_timeout_seconds,
            sse=True,
        ):
            choices = item.get("choices") or []
            if isinstance(choices, list):
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta") or {}
                    if not isinstance(delta, dict):
                        delta = {}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield ModelStreamEvent(kind="text_delta", text=content)
                    tool_calls = delta.get("tool_calls") or []
                    if isinstance(tool_calls, list):
                        for call in tool_calls:
                            if not isinstance(call, dict):
                                continue
                            function = call.get("function") or {}
                            if not isinstance(function, dict):
                                function = {}
                            yield ModelStreamEvent(
                                kind="tool_delta",
                                tool_index=int(call.get("index", 0)),
                                tool_id=str(call.get("id")) if call.get("id") else None,
                                tool_name_delta=str(function.get("name") or ""),
                                tool_arguments_delta=str(function.get("arguments") or ""),
                            )
                    finish_reason = choice.get("finish_reason")
                    if finish_reason:
                        yield ModelStreamEvent(
                            kind="done",
                            finish_reason=str(finish_reason),
                            provider_metrics=_timings(item),
                        )
            usage = item.get("usage")
            if isinstance(usage, dict):
                yield ModelStreamEvent(
                    kind="done",
                    usage=ModelUsage(
                        prompt_tokens=_optional_int(usage.get("prompt_tokens")),
                        completion_tokens=_optional_int(usage.get("completion_tokens")),
                        total_tokens=_optional_int(usage.get("total_tokens")),
                    ),
                    provider_metrics=_timings(item),
                )

    async def aclose(self) -> None:
        if self.manager is not None:
            await self.manager.stop()


def _timings(item: dict[str, Any]) -> dict[str, Any]:
    timings = item.get("timings")
    return dict(timings) if isinstance(timings, dict) else {}


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) else None
