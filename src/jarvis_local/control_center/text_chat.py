from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


MAX_TEXT_CHAT_CHARACTERS = 4000


class TextChatError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class TextChatRequestStore:
    """Cola efímera y acotada entre la UI loopback y el runtime conversacional.

    Nunca persiste texto, no representa autoridad y admite como máximo una
    solicitud pendiente. El historial canónico sigue perteneciendo al
    Orchestrator cuando el runtime consume la solicitud.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: deque[dict[str, Any]] = deque(maxlen=1)
        self._closed = False
        self._cancel_requested = False

    def submit(self, text: object, speak: object) -> dict[str, Any]:
        if not isinstance(text, str):
            raise TextChatError("invalid_text", "El mensaje debe ser texto.")
        normalized = " ".join(text.split())
        if not normalized:
            raise TextChatError("empty_text", "Escribe un mensaje antes de enviarlo.")
        if len(normalized) > MAX_TEXT_CHAT_CHARACTERS:
            raise TextChatError(
                "text_too_long",
                f"El mensaje supera {MAX_TEXT_CHAT_CHARACTERS} caracteres.",
            )
        if not isinstance(speak, bool):
            raise TextChatError("invalid_speak", "'speak' debe ser booleano.")
        request = {
            "id": str(uuid4()),
            "text": normalized,
            "speak": speak,
            "submitted_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        with self._condition:
            if self._closed:
                raise TextChatError("chat_closed", "El canal de texto está detenido.")
            if self._pending:
                raise TextChatError(
                    "chat_busy",
                    "Ya existe un mensaje pendiente. Espera la respuesta de Mark.",
                )
            self._pending.append(request)
            self._condition.notify_all()
        return dict(request)

    def take(self, *, wait_seconds: float = 0.0) -> dict[str, Any] | None:
        """Entrega la siguiente solicitud o, con prioridad, una orden de cancelar.

        La orden de cancelación es ``{"cancel": True}``: no lleva texto y el
        runtime la aplica al turno en curso.
        """

        deadline = time.monotonic() + max(0.0, min(wait_seconds, 10.0))
        with self._condition:
            while not self._pending and not self._cancel_requested and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            if self._cancel_requested:
                self._cancel_requested = False
                return {"cancel": True}
            if not self._pending:
                return None
            return dict(self._pending.popleft())

    def cancel(self) -> dict[str, Any]:
        """Descarta lo pendiente y pide al runtime cancelar el turno activo."""

        with self._condition:
            if self._closed:
                raise TextChatError("chat_closed", "El canal de texto está detenido.")
            discarded = len(self._pending)
            self._pending.clear()
            self._cancel_requested = True
            self._condition.notify_all()
        return {"outcome": "cancel_requested", "discarded": discarded}

    def discard(self, request_id: str) -> None:
        with self._condition:
            self._pending = deque(
                (item for item in self._pending if item["id"] != request_id),
                maxlen=1,
            )

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()
