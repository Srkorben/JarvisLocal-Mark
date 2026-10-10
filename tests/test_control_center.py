import http.client
import json
import socket
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from jarvis_local.control_center.catalog import ToolSpec, build_tool_catalog
from jarvis_local.control_center import launcher as launcher_module
from jarvis_local.control_center.presence import VoicePresenceStore
from jarvis_local.control_center.modules import build_module_snapshot
from jarvis_local.control_center.runtime import (
    ConfirmationRequiredError,
    ProcessManager,
    ToolConflictError,
)
from jarvis_local.control_center.server import ControlCenterHTTPServer
from jarvis_local.control_center.system_status import SystemStatusMonitor
from tests.helpers import make_settings


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
    def test_catalog_preserves_nine_shortcuts_and_adds_3d_integration(self) -> None:
        # El catálogo se valida contra una raíz sintética: la prueba no debe
        # cambiar de resultado cuando el usuario enrola o elimina su voz real.
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            platform_executable = root / "platform-tool.exe"
            platform_executable.touch()
            with patch(
                "jarvis_local.control_center.catalog._windows_executable",
                return_value=platform_executable,
            ):
                catalog = build_tool_catalog(root)
            self.assertEqual(len(catalog), 11)
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
                    "Integración Mark Scout / Godot 4.7.2",
                    "Centro de control — chat escrito",
                },
            )
            for item in catalog.values():
                self.assertEqual(item.working_directory, root)
                if item.id not in {"voice", "chat_runtime"}:
                    self.assertTrue(item.target.is_file())
            self.assertIn(
                "Muestra de voz propia enrolada",
                catalog["voice"].missing_requirements(),
            )
            self.assertEqual(
                catalog["voice"].target,
                root / ".venv" / "Scripts" / "python.exe",
            )
            self.assertEqual(
                catalog["voice"].arguments,
                (
                    "-m",
                    "jarvis_local.cli",
                    "--config",
                    str(root / "config" / "jarvis.toml"),
                    "--voice",
                ),
            )
            self.assertFalse(catalog["voice"].visible_console)
            self.assertNotIn("-NoExit", catalog["voice"].arguments)


    def test_piper_voice_and_text_runtime_do_not_require_chatterbox(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            catalog = build_tool_catalog(root, voice_tts_provider="piper")
            voice_missing = catalog["voice"].missing_requirements()
            self.assertIn("Voz Piper local", voice_missing)
            self.assertIn("Modelo faster-whisper-small", voice_missing)
            for chatterbox_only in (
                "Entorno aislado Chatterbox",
                "Modelo Chatterbox LatAm",
                "Muestra de voz propia enrolada",
            ):
                self.assertNotIn(chatterbox_only, voice_missing)
            chat = catalog["chat_runtime"]
            self.assertEqual(
                chat.arguments,
                ("-m", "jarvis_local.cli", "--config", str(root / "config" / "jarvis.toml"), "--panel-chat"),
            )
            self.assertNotIn("Modelo faster-whisper-small", chat.missing_requirements())
            self.assertFalse(chat.visible_console)
            self.assertIn("core_runtime", chat.exclusive_groups)


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
            manager.stop_all()
            self.assertEqual(manager.list_status()[1]["status"], "available")

    def test_stop_all_preserves_non_stoppable_delegated_applications(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            fake = FakePopen()
            delegated = replace(
                make_test_tool(root, "delegated"),
                stoppable=False,
            )
            manager = ProcessManager(
                {"delegated": delegated},
                popen_factory=fake,
                process_terminator=lambda process: process.terminate(),
                cooldown_seconds=0,
            )
            manager.start("delegated")
            manager.stop_all()
            self.assertEqual(manager.list_status()[0]["status"], "running")


class PresenceTests(TestCase):
    def test_presence_is_ephemeral_bounded_and_rejects_authority_fields(self) -> None:
        store = VoicePresenceStore()
        self.assertEqual(store.snapshot()["state"], "offline")
        updated = store.update(
            {
                "state": "speaking",
                "transcript": "hola",
                "response": "respuesta",
                "error": "",
            }
        )
        self.assertEqual(updated["revision"], 1)
        self.assertEqual(updated["response"], "respuesta")
        with self.assertRaises(ValueError):
            store.update({"state": "idle", "allowed_tools": "all"})


class ModuleSnapshotTests(TestCase):
    def test_snapshot_reports_real_configuration_without_secret_fields(self) -> None:
        source = Path(__file__).parents[1] / "config" / "jarvis.toml"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            copyfile(source, root / "config" / "jarvis.toml")
            snapshot = build_module_snapshot(root)
            self.assertEqual(snapshot["identity"]["display_name"], "Mark Scout")
            self.assertEqual(
                {module["id"] for module in snapshot["modules"]},
                {"interface", "authority", "audio", "model", "memory", "security"},
            )
            rendered = json.dumps(snapshot, ensure_ascii=False).casefold()
            self.assertNotIn("auth_token", rendered)
            self.assertNotIn("secret-token", rendered)
            self.assertNotIn("password", rendered)
            self.assertIn("semidúplex", rendered)


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
        self.system_monitor = SystemStatusMonitor(
            make_settings(root, model="fixture-model"),
            manager,
            hardware_reader=lambda: {
                "cpu": {"available": True, "percent": 25.0},
                "ram": {
                    "available": True,
                    "used_mib": 1024,
                    "total_mib": 4096,
                    "percent": 25.0,
                },
                "gpu": {"available": False, "reason": "nvidia_smi_missing"},
            },
        )
        self.server = ControlCenterHTTPServer(
            ("127.0.0.1", 0),
            manager,
            auth_token="secret-token",
            csrf_token="csrf-token",
            icon_path=icon,
            system_monitor=self.system_monitor,
            module_snapshot=lambda: {
                "identity": {"display_name": "Mark Scout", "short_name": "Mark"},
                "modules": [{"id": "model", "label": "Modelo"}],
            },
            voice_importer=self._import_voice,
            version="test",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def _import_voice(self, **payload):
        self.import_payload = payload
        return {"outcome": "imported", "duration_seconds": 20.0}

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
        self.assertIn(b"Iniciar voz", body)
        self.assertIn(b"Mark Scout", body)
        self.assertIn(b'data-module="interface"', body)
        self.assertIn(b"mark.visualQuality", body)

        status, _, body = self.request(
            "GET", "/api/modules", headers=self.authenticated_headers()
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["identity"]["short_name"], "Mark")

        status, _, _ = self.request("GET", "/api/system")
        self.assertEqual(status, 401)
        status, headers, body = self.request(
            "GET", "/api/system", headers=self.authenticated_headers()
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        system = json.loads(body)["system"]
        self.assertEqual(system["model"]["name"], "fixture-model")
        self.assertEqual(system["cpu"]["percent"], 25.0)
        self.assertNotIn("project_dir", json.dumps(system))

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

    def test_voice_file_import_requires_csrf_and_typed_local_authorization(self) -> None:
        payload = json.dumps(
            {
                "filename": "muestra.wav",
                "audio_base64": "UklGRg==",
                "authorization_confirmed": True,
                "replace_existing": True,
            }
        ).encode("utf-8")
        status, _, _ = self.request(
            "POST",
            "/api/voice/reference/import",
            headers=self.authenticated_headers(),
            body=payload,
        )
        self.assertEqual(status, 403)

        status, _, body = self.request(
            "POST",
            "/api/voice/reference/import",
            headers=self.authenticated_headers(csrf=True),
            body=payload,
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"]["outcome"], "imported")
        self.assertTrue(self.import_payload["authorization_confirmed"])

        invalid = json.dumps(
            {
                "filename": "muestra.wav",
                "audio_base64": "UklGRg==",
                "authorization_confirmed": "sí",
                "replace_existing": True,
            }
        ).encode("utf-8")
        status, _, body = self.request(
            "POST",
            "/api/voice/reference/import",
            headers=self.authenticated_headers(csrf=True),
            body=invalid,
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_request")

    def test_voice_presence_requires_internal_bearer_and_cannot_change_policy(self) -> None:
        payload = json.dumps(
            {
                "state": "speaking",
                "transcript": "Hola",
                "response": "Buenas tardes",
                "error": "",
            }
        ).encode("utf-8")
        status, _, _ = self.request("POST", "/api/voice/presence", body=payload)
        self.assertEqual(status, 401)

        headers = {
            "Authorization": "Bearer secret-token",
            "Content-Type": "application/json",
        }
        status, _, body = self.request(
            "POST", "/api/voice/presence", headers=headers, body=payload
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["presence"]["state"], "speaking")

        status, _, body = self.request(
            "GET", "/api/voice/presence", headers=self.authenticated_headers()
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["presence"]["transcript"], "Hola")

        malicious = json.dumps(
            {"state": "idle", "transcript": "", "response": "", "error": "", "policy": "allow"}
        ).encode("utf-8")
        status, _, body = self.request(
            "POST", "/api/voice/presence", headers=headers, body=malicious
        )
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "invalid_presence")

    def test_presence_read_accepts_internal_bearer_for_3d_client(self) -> None:
        status, _, body = self.request(
            "GET",
            "/api/voice/presence",
            headers={"Authorization": "Bearer secret-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["presence"]["state"], "offline")

    def test_http_log_does_not_include_query_token(self) -> None:
        with self.assertLogs("jarvis_local.control_center", level="INFO") as captured:
            status, _, _ = self.request("GET", "/?token=secret-token")
        self.assertEqual(status, 303)
        rendered = "\n".join(captured.output)
        self.assertIn("path=/", rendered)
        self.assertNotIn("secret-token", rendered)


class ChatRoutingHTTPTests(TestCase):
    """El chat escrito no debe arrancar la voz (STT, TTS y micrófono)."""

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.fake = FakePopen()
        # Ambos runtimes comparten grupo exclusivo, como core_runtime.
        self.manager = ProcessManager(
            {
                "voice": make_test_tool(root, "voice"),
                "chat_runtime": make_test_tool(root, "chat_runtime"),
            },
            popen_factory=self.fake,
            process_terminator=lambda process: process.terminate(),
            cooldown_seconds=0,
        )
        icon = root / "icon.ico"
        icon.write_bytes(b"\x00\x00\x01\x00")
        self.server = ControlCenterHTTPServer(
            ("127.0.0.1", 0),
            self.manager,
            auth_token="secret-token",
            csrf_token="csrf-token",
            icon_path=icon,
            system_monitor=SystemStatusMonitor(
                make_settings(root),
                self.manager,
                hardware_reader=lambda: {},
            ),
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

    def post(self, path: str, payload: dict) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(
            "POST",
            path,
            body=json.dumps(payload).encode("utf-8"),
            headers={
                "Cookie": "jarvis_cc=secret-token",
                "Origin": f"http://127.0.0.1:{self.port}",
                "X-CSRF-Token": "csrf-token",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        body = json.loads(response.read() or b"{}")
        connection.close()
        return response.status, body

    def running(self) -> set[str]:
        return {
            item["id"] for item in self.manager.list_status() if item["status"] == "running"
        }

    def test_text_message_starts_text_runtime_not_voice(self) -> None:
        status, body = self.post("/api/chat", {"text": "hola", "speak": False})
        self.assertEqual(status, 202)
        self.assertEqual(body["result"]["runtime"], "started")
        self.assertEqual(self.running(), {"chat_runtime"})
        self.assertEqual(self.server.presence.snapshot()["state"], "queued")

    def test_active_voice_runtime_answers_text_without_second_runtime(self) -> None:
        self.manager.start("voice")
        status, body = self.post("/api/chat", {"text": "hola", "speak": True})
        self.assertEqual(status, 202)
        self.assertEqual(body["result"]["runtime"], "already_running")
        self.assertEqual(self.running(), {"voice"})
        self.assertEqual(len(self.fake.commands), 1)

    def test_starting_voice_hands_over_from_text_runtime(self) -> None:
        self.manager.start("chat_runtime")
        status, body = self.post("/api/tools/voice/start", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["outcome"], "started")
        self.assertEqual(self.running(), {"voice"})


class TextChatStoreTests(TestCase):
    def test_cancel_discards_pending_and_wakes_the_runtime(self) -> None:
        from jarvis_local.control_center.text_chat import TextChatRequestStore

        store = TextChatRequestStore()
        store.submit("hola", False)
        received: list[object] = []
        self.assertEqual(store.cancel()["discarded"], 1)
        waiter = threading.Thread(target=lambda: received.append(store.take(wait_seconds=5)))
        waiter.start()
        waiter.join(timeout=2)
        self.assertEqual(received, [{"cancel": True}])
        self.assertIsNone(store.take(wait_seconds=0))


class ChatPanelHTTPTests(ChatRoutingHTTPTests):
    def test_dashboard_includes_the_chat_panel(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("GET", "/", headers={"Cookie": "jarvis_cc=secret-token"})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        self.assertEqual(response.status, 200)
        for marker in (
            b'id="chatInput"', b'id="chatCancel"', b"/api/chat/cancel",
            b"chatPresence", b'id="corePanel"', b"/api/system",
        ):
            self.assertIn(marker, body)
        self.assertNotIn(b'style="', body)

    def test_chat_renders_markdown_without_html_injection(self) -> None:
        from jarvis_local.control_center.web import render_dashboard

        page = render_dashboard(csrf_token="c", nonce="n", version="v")
        chat = page[page.index("// --- Chat escrito"):page.index("const canvas=")]
        # El chat construye nodos con textContent; innerHTML solo aparece en
        # el comentario que lo prohíbe.
        self.assertEqual(chat.count("innerHTML"), 1)
        for marker in ("function mdRender", 'createElement("strong")', 'createElement("pre")',
                       "p.revision<=turn.minRevision", 'id="chatWide"'):
            self.assertIn(marker, page if marker.startswith("id=") else chat)

    def test_cancel_requires_csrf_and_reaches_the_runtime_queue(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(
            "POST", "/api/chat/cancel", body=b"{}",
            headers={"Cookie": "jarvis_cc=secret-token", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 403)
        status, body = self.post("/api/chat/cancel", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["outcome"], "cancel_requested")
        self.assertEqual(self.server.text_chat.take(wait_seconds=0), {"cancel": True})


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
