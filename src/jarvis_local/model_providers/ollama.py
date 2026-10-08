from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..cancellation import CancellationToken
from ..config import Settings
from .base import ModelProvider, ModelStreamEvent, ModelUsage, ProviderHealth
from .http import require_loopback_url, stream_json_lines


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.model
        self.base_url = require_loopback_url(settings.model_base_url)

    async def health(self) -> ProviderHealth:
        try:
            timeout = httpx.Timeout(min(self.settings.request_timeout_seconds, 10))
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                version_response = await client.get(f"{self.base_url}/api/version")
                version_response.raise_for_status()
                tags_response = await client.get(f"{self.base_url}/api/tags")
                tags_response.raise_for_status()
            version = str(version_response.json().get("version", "desconocida"))
            names = {
                str(item.get("name"))
                for item in tags_response.json().get("models", [])
                if isinstance(item, dict)
            }
            ready = self.model in names
            return ProviderHealth(
                provider=self.name,
                available=True,
                ready=ready,
                model=self.model,
                version=version,
                detail="Modelo disponible." if ready else "El modelo configurado no está instalado.",
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
            "messages": _ollama_messages(messages),
            "tools": tools,
            "stream": True,
            "think": self.settings.think,
            "options": {
                "num_ctx": self.settings.context_tokens,
                "temperature": self.settings.temperature,
                "num_predict": self.settings.max_output_tokens,
            },
        }
        tool_index = 0
        async for item in stream_json_lines(
            provider=self.name,
            url=f"{self.base_url}/api/chat",
            payload=payload,
            cancellation=cancellation,
            timeout_seconds=self.settings.request_timeout_seconds,
            sse=False,
        ):
            message = item.get("message") or {}
            if not isinstance(message, dict):
                message = {}
            content = message.get("content")
            if isinstance(content, str) and content:
                yield ModelStreamEvent(kind="text_delta", text=content)
            calls = message.get("tool_calls") or []
            if isinstance(calls, list):
                for call in calls:
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    arguments = function.get("arguments", {})
                    raw_arguments = (
                        arguments if isinstance(arguments, str)
                        else json.dumps(arguments, ensure_ascii=False)
                    )
                    yield ModelStreamEvent(
                        kind="tool_delta",
                        tool_index=tool_index,
                        tool_id=str(call.get("id")) if isinstance(call, dict) and call.get("id") else None,
                        tool_name_delta=str(function.get("name") or ""),
                        tool_arguments_delta=raw_arguments,
                    )
                    tool_index += 1
            if item.get("done"):
                prompt_tokens = _optional_int(item.get("prompt_eval_count"))
                completion_tokens = _optional_int(item.get("eval_count"))
                yield ModelStreamEvent(
                    kind="done",
                    finish_reason=str(item.get("done_reason") or "stop"),
                    usage=ModelUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=(
                            prompt_tokens + completion_tokens
                            if prompt_tokens is not None and completion_tokens is not None
                            else None
                        ),
                    ),
                    provider_metrics={
                        key: item[key]
                        for key in (
                            "total_duration",
                            "load_duration",
                            "prompt_eval_duration",
                            "eval_duration",
                        )
                        if key in item
                    },
                )


def _optional_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) else None


def _ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Adapta el historial canónico OpenAI al formato de Ollama."""

    adapted: list[dict[str, Any]] = []
    for source in messages:
        message = dict(source)
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            normalized_calls: list[dict[str, Any]] = []
            for call in calls:
                if not isinstance(call, dict):
                    continue
                normalized = dict(call)
                function = dict(normalized.get("function") or {})
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        decoded = json.loads(arguments)
                    except json.JSONDecodeError:
                        decoded = {}
                    function["arguments"] = decoded
                normalized["function"] = function
                normalized.pop("type", None)
                normalized_calls.append(normalized)
            message["tool_calls"] = normalized_calls
        if message.get("role") == "tool":
            message.pop("tool_call_id", None)
            message.pop("name", None)
        adapted.append(message)
    return adapted
