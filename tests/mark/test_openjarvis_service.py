import json
import socket
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis_local.control_center import launcher
from jarvis_local.control_center.openjarvis_service import (
    PORT_CANDIDATES,
    choose_port,
    diagnose,
    port_is_free,
)
from jarvis_local.control_center.runtime import (
    ProcessManager,
    ToolConflictError,
    ToolUnavailableError,
)
from jarvis_local.control_center.catalog import ToolSpec


def _serve(headers, body):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802
            payload = body.encode()
            self.send_response(200)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class PortTests(unittest.TestCase):
    def test_openjarvis_never_shares_the_control_center_range(self):
        """Causa raíz: ambos usaban 8765 y el panel mostraba la página de Mark."""
        self.assertFalse(set(PORT_CANDIDATES) & set(launcher.PORT_RANGE))

    def test_choose_port_skips_busy_ports(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", PORT_CANDIDATES[0]))
            busy.listen()
            self.assertFalse(port_is_free(PORT_CANDIDATES[0]))
            with TemporaryDirectory() as directory:
                chosen = choose_port(Path(directory))
            self.assertNotEqual(chosen, PORT_CANDIDATES[0])
            self.assertIn(chosen, PORT_CANDIDATES)


class DiagnoseTests(unittest.TestCase):
    def test_unreachable(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        state = diagnose(f"http://127.0.0.1:{port}", timeout=0.5)
        self.assertEqual((state["ready"], state["reachable"]), (False, False))

    def test_rejects_mark_control_center_answering_on_the_port(self):
        server, origin = _serve(
            {"X-Frame-Options": "DENY"},
            json.dumps({"status": "ok", "service": "Mark Scout Control Center"}),
        )
        try:
            state = diagnose(origin)
        finally:
            server.shutdown()
        self.assertFalse(state["ready"])
        self.assertIn("centro de control de Mark", state["detail"])

    def test_rejects_a_server_that_forbids_framing(self):
        server, origin = _serve({"X-Frame-Options": "DENY"}, '{"status":"ok"}')
        try:
            state = diagnose(origin)
        finally:
            server.shutdown()
        self.assertFalse(state["ready"])
        self.assertTrue(state["reachable"])
        self.assertIn("no permite que Mark lo muestre", state["detail"])

    def test_accepts_openjarvis_with_loopback_frame_ancestors(self):
        server, origin = _serve(
            {"Content-Security-Policy": "default-src 'self'; frame-ancestors http://127.0.0.1:*"},
            '{"status":"ok"}',
        )
        try:
            state = diagnose(origin)
        finally:
            server.shutdown()
        self.assertTrue(state["ready"])


class ProcessDiagnosticsTests(unittest.TestCase):
    def _tool(self, root, code):
        return ToolSpec(
            id="svc",
            name="Servicio",
            description="",
            category="Asistente",
            target=Path(sys.executable),
            arguments=("-c", code),
            working_directory=root,
            source="test",
        )

    def test_hidden_tool_output_is_logged_and_explains_early_exit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ProcessManager(
                {"svc": self._tool(root, "print('No inference engine available.'); raise SystemExit(1)")},
                log_directory=root / "logs",
                cooldown_seconds=60,
            )
            manager.start("svc")
            manager._records["svc"].process.wait(timeout=20)
            self.assertFalse(manager.is_running("svc"))
            self.assertEqual(manager.last_result("svc")["exit_code"], 1)
            self.assertIn("No inference engine available.", manager.log_tail("svc"))
            with self.assertRaises(ToolUnavailableError) as raised:
                manager.start("svc")
            message = str(raised.exception)
            self.assertIn("se cerró al iniciar (código 1)", message)
            self.assertIn("No inference engine available.", message)
            self.assertNotIn("espera un momento", message)

    def test_double_start_of_a_live_tool_is_not_an_error(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ProcessManager(
                {"svc": self._tool(root, "import time; time.sleep(30)")},
                log_directory=root / "logs",
                cooldown_seconds=60,
            )
            manager.start("svc")
            try:
                self.assertEqual(manager.start("svc")["outcome"], "already_running")
            finally:
                manager.stop_all()

    def test_prestart_failure_blocks_launch_with_its_reason(self):
        def no_ollama():
            raise ToolUnavailableError("Ollama no responde.")

        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ProcessManager(
                {"svc": self._tool(root, "pass")}, prestart={"svc": no_ollama}
            )
            with self.assertRaises(ToolUnavailableError) as raised:
                manager.start("svc")
            self.assertIn("Ollama no responde", str(raised.exception))
            self.assertFalse(manager.is_running("svc"))


if __name__ == "__main__":
    unittest.main()
