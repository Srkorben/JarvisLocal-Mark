from __future__ import annotations

import asyncio
import threading


class OperationCancelled(RuntimeError):
    pass


class CancellationToken:
    """Token cooperativo apto para código síncrono ejecutado en threads."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason = ""
        self._lock = threading.Lock()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def cancel(self, reason: str = "Cancelado por el usuario.") -> None:
        with self._lock:
            if not self._event.is_set():
                self._reason = reason
                self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise OperationCancelled(self.reason or "Operación cancelada.")

    async def wait(self) -> None:
        # No delegar Event.wait() a un thread: cancelar ese Future no detendría
        # el thread subyacente. El sondeo corto mantiene cancelación predecible.
        while not self._event.is_set():
            await asyncio.sleep(0.025)


class CancellationController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current = CancellationToken()

    def begin_turn(self) -> CancellationToken:
        with self._lock:
            self._current.cancel("Sustituido por un nuevo turno.")
            self._current = CancellationToken()
            return self._current

    def cancel_current(self, reason: str = "Cancelado por el usuario.") -> None:
        with self._lock:
            self._current.cancel(reason)

    @property
    def current(self) -> CancellationToken:
        with self._lock:
            return self._current

