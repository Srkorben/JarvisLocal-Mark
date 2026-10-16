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


MAX_TRANSCRIPT_TURNS = 50
_ACTIVE_STATES = frozenset({"processing", "speaking", "transcribing"})


class ChatTranscript:
    """Historial visible del chat, solo en memoria del centro de control.

    Permite recuperar la conversación al recargar el panel o la app WPF sin
    escribir nada en disco: se pierde al cerrar el centro de control. Se
    alimenta de lo que el servidor ya ve (mensajes enviados y presencia).
    """

    def __init__(self, *, max_turns: int = MAX_TRANSCRIPT_TURNS) -> None:
        self._lock = threading.Lock()
        self._turns: deque[dict[str, Any]] = deque(maxlen=max_turns)

    def start(self, request: dict[str, Any]) -> None:
        with self._lock:
            self._turns.append(
                {
                    "id": request["id"],
                    "user": request["text"],
                    "assistant": "",
                    "outcome": "pending",
                    "error": "",
                    "started_at": request.get("submitted_at"),
                    "finished_at": None,
                    "_active": False,
                    "_cancel": False,
                }
            )

    def discard(self, request_id: str) -> None:
        with self._lock:
            self._turns = deque(
                (turn for turn in self._turns if turn["id"] != request_id),
                maxlen=self._turns.maxlen,
            )

    def mark_cancel(self) -> None:
        with self._lock:
            turn = self._pending()
            if turn is not None:
                turn["_cancel"] = True

    def observe(self, presence: dict[str, Any]) -> None:
        """Actualiza el turno pendiente con un estado de presencia."""

        with self._lock:
            turn = self._pending()
            if turn is None:
                return
            state = presence.get("state")
            transcript = presence.get("transcript") or ""
            response = presence.get("response") or ""
            if state == "offline":
                self._finish(turn, "error", "El núcleo se detuvo antes de responder.")
                return
            if transcript and transcript != turn["user"]:
                return
            if state in _ACTIVE_STATES:
                turn["_active"] = True
            if response and (turn["_active"] or state in {"idle", "cancelling"}):
                turn["assistant"] = response
            if state == "cancelling":
                turn["_cancel"] = True
            elif state == "error":
                self._finish(turn, "error", str(presence.get("error") or "El núcleo informó un error."))
            elif state == "idle" and (turn["_active"] or response):
                self._finish(turn, "cancelled" if turn["_cancel"] else "done", "")

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {key: value for key, value in turn.items() if not key.startswith("_")}
                for turn in self._turns
            ]

    def clear(self) -> int:
        """Borra los turnos terminados; conserva el que sigue en curso."""

        with self._lock:
            pending = [turn for turn in self._turns if turn["outcome"] == "pending"]
            removed = len(self._turns) - len(pending)
            self._turns = deque(pending, maxlen=self._turns.maxlen)
            return removed

    def _pending(self) -> dict[str, Any] | None:
        for turn in reversed(self._turns):
            if turn["outcome"] == "pending":
                return turn
        return None

    @staticmethod
    def _finish(turn: dict[str, Any], outcome: str, error: str) -> None:
        turn["outcome"] = outcome
        turn["error"] = error
        turn["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
