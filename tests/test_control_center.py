import http.client
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from jarvis_local.control_center.catalog import ToolSpec, build_tool_catalog
from jarvis_local.control_center import launcher as launcher_module
from jarvis_local.control_center.runtime import (
    ConfirmationRequiredError,
    ProcessManager,
    ToolConflictError,
)
from jarvis_local.control_center.server import ControlCenterHTTPServer


class FakeProcess:
    next_pid = 4100

    def __init__(self) -> None:
        type(self).next_pid += 1
        self.pid = type(self).next_pid
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakePopen:
    def __init__(self) -> None:
        self.commands: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.commands.append((list(command), kwargs))
        return FakeProcess()


def make_test_tool(root: Path, tool_id: str = "test", *, confirmation: bool = False) -> ToolSpec:
    return ToolSpec(
        id=tool_id,
        name=tool_id,
        description="fixture",
        category="Prueba",
        target=Path(sys.executable),
        arguments=("--version",),
        working_directory=root,
        source="fixture.lnk",
        exclusive_groups=("fixture",),
        confirmation_required=confirmation,
        visible_console=False,
    )


class CatalogTests(TestCase):
    def test_catalog_exactly_reconstructs_nine_project_shortcuts(self) -> None:
        # El catálogo se valida contra una raíz sintética: la prueba no debe
        # cambiar de resultado cuando el usuario enrola o elimina su voz real.
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            catalog = build_tool_catalog(root)
            self.assertEqual(len(catalog), 9)
            self.assertEqual(
                {item.source for item in catalog.values()},
                {
                    "JarvisLocal - Abrir proyecto.lnk",
                    "JarvisLocal - Chat de texto.lnk",
                    "JarvisLocal - Configuración.lnk",
                    "JarvisLocal - Conversación por voz.lnk",
                    "JarvisLocal - Diagnóstico.lnk",
                    "JarvisLocal - Enrolar mi voz.lnk",
                    "JarvisLocal - Instalar o reparar.lnk",
                    "JarvisLocal - Preparar clonación de voz.lnk",
                    "JarvisLocal - Preparar modelos de audio.lnk",
                },
            )
            for item in catalog.values():
                self.assertEqual(item.working_directory, root)
                self.assertTrue(item.target.is_file())
            self.assertIn(
                "Muestra de voz propia enrolada",
                catalog["voice"].missing_requirements(),
            )


class ProcessManagerTests(TestCase):
    def test_confirmation_duplicate_conflict_and_stop(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fake = FakePopen()
            first = make_test_tool(root, "first", confirmation=True)
            second = make_test_tool(root, "second")
            manager = ProcessManager(
                {"first": first, "second": second},
                popen_factory=fake,
                process_terminator=lambda process: process.terminate(),
                cooldown_seconds=0,
            )
            with self.assertRaises(ConfirmationRequiredError):
                manager.start("first")
            started = manager.start("first", confirmed=True)
            self.assertEqual(started["outcome"], "started")
            duplicate = manager.start("first", confirmed=True)
            self.assertEqual(duplicate["outcome"], "already_running")
            with self.assertRaises(ToolConflictError):
                manager.start("second")
            stopped = manager.stop("first")
            self.assertEqual(stopped["outcome"], "stopped")
            self.assertEqual(manager.start("second")["outcome"], "started")
            self.assertEqual(fake.commands[0][0], [sys.executable, "--version"])
            self.assertFalse(fake.commands[0][1]["shell"])


class HTTPTests(TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.fake = FakePopen()
        manager = ProcessManager(
            {"sample": make_test_tool(root, "sample", confirmation=True)},
            popen_factory=self.fake,
            process_terminator=lambda process: process.terminate(),
            cooldown_seconds=0,
        )
        icon = root / "icon.ico"
        icon.write_bytes(b"\x00\x00\x01\x00")
        self.server = ControlCenterHTTPServer(
            ("127.0.0.1", 0),
            manager,
            auth_token="secret-token",
            csrf_token="csrf-token",
            icon_path=icon,
            version="test",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(self, method: str, path: str, *, headers=None, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        result = response.status, dict(response.getheaders()), data
        connection.close()
        return result

    def authenticated_headers(self, *, csrf: bool = False) -> dict[str, str]:
        headers = {"Cookie": "jarvis_cc=secret-token"}
        if csrf:
            headers.update(
                {
                    "Origin": f"http://127.0.0.1:{self.port}",
                    "X-CSRF-Token": "csrf-token",
                    "Content-Type": "application/json",
                }
            )
        return headers

    def test_loopback_authentication_security_headers_and_api(self) -> None:
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, _, _ = self.request("GET", "/api/tools")
        self.assertEqual(status, 401)

        status, headers, _ = self.request("GET", "/?token=secret-token")
        self.assertEqual(status, 303)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])

        status, headers, body = self.request("GET", "/", headers=self.authenticated_headers())
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertIn(b"Centro de control", body)

        status, _, _ = self.request(
            "POST", "/api/tools/sample/start", headers=self.authenticated_headers(), body=b"{}"
        )
        self.assertEqual(status, 403)

        status, _, body = self.request(
            "POST",
            "/api/tools/sample/start",
            headers=self.authenticated_headers(csrf=True),
            body=b'{"confirmed":false}',
        )
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"]["code"], "confirmation_required")

        status, _, body = self.request(
            "POST",
            "/api/tools/sample/start",
            headers=self.authenticated_headers(csrf=True),
            body=b'{"confirmed":true}',
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"]["outcome"], "started")

        status, _, _ = self.request(
            "POST",
            "/api/tools/arbitrary/start",
            headers=self.authenticated_headers(csrf=True),
            body=b"{}",
        )
        self.assertEqual(status, 404)

    def test_rejects_host_injection_and_untyped_arguments(self) -> None:
        status, _, _ = self.request("GET", "/health", headers={"Host": "attacker.invalid"})
        self.assertEqual(status, 400)
        status, _, body = self.request(
            "POST",
            "/api/tools/sample/start",
            headers=self.authenticated_headers(csrf=True),
            body=b'{"command":"whoami"}',
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_request")

    def test_http_log_does_not_include_query_token(self) -> None:
        with self.assertLogs("jarvis_local.control_center", level="INFO") as captured:
            status, _, _ = self.request("GET", "/?token=secret-token")
        self.assertEqual(status, 303)
        rendered = "\n".join(captured.output)
        self.assertIn("path=/", rendered)
        self.assertNotIn("secret-token", rendered)


class StatusCLITests(TestCase):
    def test_status_never_prints_authentication_token(self) -> None:
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, "-m", "jarvis_local.control_center", "--status"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotIn('"token"', completed.stdout)

    def test_port_selection_skips_an_occupied_port(self) -> None:
        occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        occupied_port = occupied.getsockname()[1]
        with TemporaryDirectory() as directory:
            root = Path(directory)
            icon = root / "icon.ico"
            icon.write_bytes(b"\x00\x00\x01\x00")
            original = launcher_module.PORT_RANGE
            launcher_module.PORT_RANGE = (occupied_port, 0)
            server = None
            try:
                server = launcher_module._bind_available_server(
                    ProcessManager({}), "token", "csrf", icon
                )
                self.assertEqual(server.server_address[0], "127.0.0.1")
                self.assertNotEqual(server.server_address[1], occupied_port)
            finally:
                launcher_module.PORT_RANGE = original
                if server is not None:
                    server.server_close()
                occupied.close()
