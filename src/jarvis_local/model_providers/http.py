from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..cancellation import CancellationToken, OperationCancelled
from .base import ModelProviderError, next_line_or_cancel


def require_loopback_url(url: str) -> str:
    parsed = httpx.URL(url)
    if parsed.scheme != "http" or parsed.host != "127.0.0.1":
        raise ValueError("Los proveedores locales deben usar http://127.0.0.1.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("La URL local no admite credenciales, query ni fragmentos.")
    return str(parsed).rstrip("/")


async def stream_json_lines(
    *,
    provider: str,
    url: str,
    payload: dict[str, Any],
    cancellation: CancellationToken,
    timeout_seconds: float,
    sse: bool,
) -> AsyncIterator[dict[str, Any]]:
    timeout = httpx.Timeout(timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            async with client.stream("POST", url, json=payload) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")[:4000]
                    raise ModelProviderError(
                        "http_error",
                        f"El servidor respondió HTTP {response.status_code}: {body}",
                        provider=provider,
                        retryable=response.status_code >= 500,
                        status_code=response.status_code,
                    )
                lines = response.aiter_lines()
                while True:
                    try:
                        line = await next_line_or_cancel(lines, cancellation)
                    except StopAsyncIteration:
                        break
                    if not line:
                        continue
                    if sse:
                        if line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        line = line[5:].strip()
                        if line == "[DONE]":
                            break
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ModelProviderError(
                            "invalid_response",
                            f"El servidor emitió JSON inválido: {exc}",
                            provider=provider,
                        ) from exc
                    if not isinstance(item, dict):
                        raise ModelProviderError(
                            "invalid_response",
                            "El servidor emitió un elemento que no es objeto JSON.",
                            provider=provider,
                        )
                    yield item
    except OperationCancelled:
        raise
    except ModelProviderError:
        raise
    except httpx.TimeoutException as exc:
        raise ModelProviderError(
            "timeout",
            f"El proveedor excedió {timeout_seconds:g} segundos.",
            provider=provider,
            retryable=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise ModelProviderError(
            "unavailable",
            f"Proveedor local no disponible: {exc}",
            provider=provider,
            retryable=True,
        ) from exc
