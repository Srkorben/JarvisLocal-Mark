import socket
import threading
import time
from unittest import TestCase

from jarvis_local.control_center.presence import VoicePresenceClient


class HangingServer:
    """Acepta conexiones y nunca responde: simula un panel bloqueado."""

    def __init__(self) -> None:
        self.socket = socket.socket()
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(16)
        self.port = self.socket.getsockname()[1]
        self.connections: list[socket.socket] = []
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        while True:
            try:
                connection, _ = self.socket.accept()
            except OSError:
                return
            self.connections.append(connection)

    def close(self) -> None:
        self.socket.close()
        for connection in self.connections:
            connection.close()


class PresencePublishTests(TestCase):
    def test_updates_never_block_the_caller_when_the_panel_hangs(self) -> None:
        server = HangingServer()
        try:
            client = VoicePresenceClient(port=server.port, token="x" * 32, timeout_seconds=0.5)
            started = time.monotonic()
            client.set_state("processing")
            for index in range(20):
                client.set_transcript(f"fragmento {index}")
            self.assertLess(time.monotonic() - started, 0.1)
        finally:
            server.close()

    def test_terminal_state_waits_for_delivery_with_a_bound(self) -> None:
        server = HangingServer()
        try:
            client = VoicePresenceClient(port=server.port, token="x" * 32, timeout_seconds=0.3)
            started = time.monotonic()
            client.close(flush_timeout=0.5)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 2.0)
        finally:
            server.close()

    def test_unreachable_panel_is_ignored(self) -> None:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        client = VoicePresenceClient(port=port, token="x" * 32, timeout_seconds=0.2)
        client.set_state("idle")
        client.set_error("sin panel")
        client.close()
