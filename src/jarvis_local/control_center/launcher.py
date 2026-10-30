from __future__ import annotations

import contextlib
import getpass
import json
import logging
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Iterator

from ..config import Settings
from ..database import Database
from ..policy import PolicyEngine
from ..process_lock import windows_singleton
from ..projects import ProjectService
from ..openjarvis_bridge import openjarvis_environment, prepare_openjarvis_home
from .catalog import build_tool_catalog
from .modules import build_module_snapshot
from .runtime import ProcessManager
from .server import ControlCenterHTTPServer
from .system_status import SystemStatusMonitor
from .text_chat import TextChatRequestStore
from .voice_import import VoiceReferenceImporter
from .voice_control import VoiceControlStore


LOGGER = logging.getLogger("jarvis_local.control_center")
HOST = "127.0.0.1"
PORT_RANGE = range(8765, 8775)


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def state_directory(root: Path) -> Path:
    return root / "data" / "control_center"


def endpoint_path(root: Path) -> Path:
    return state_directory(root) / "endpoint.json"


def read_endpoint(root: Path) -> dict[str, object] | None:
    try:
        value = json.loads(endpoint_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    required = {"pid", "port", "token", "started_at"}
    if not isinstance(value, dict) or not required.issubset(value):
        return None
    if not isinstance(value["port"], int) or not isinstance(value["token"], str):
        return None
    return value


def health(endpoint: dict[str, object], timeout: float = 1.0) -> bool:
    port = endpoint.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return False
    request = urllib.request.Request(f"http://{HOST}:{port}/health")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        return response.status == 200 and payload.get("status") == "ok"
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False


def launch(*, open_browser: bool = True, timeout_seconds: float = 20.0) -> dict[str, object]:
    root = project_root()
    directory = state_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    with _launch_lock(directory / "launch.lock", timeout_seconds=10):
        endpoint = read_endpoint(root)
        started = False
        if endpoint is None or not health(endpoint):
            endpoint_path(root).unlink(missing_ok=True)
            _spawn_server(root)
            started = True
            deadline = time.monotonic() + timeout_seconds
            endpoint = None
            while time.monotonic() < deadline:
                time.sleep(0.15)
                candidate = read_endpoint(root)
                if candidate is not None and health(candidate):
                    endpoint = candidate
                    break
            if endpoint is None:
                raise RuntimeError(
                    f"El centro de control no respondió. Revisa {directory / 'control-center.log'}"
                )
        if open_browser:
            url = f"http://{HOST}:{endpoint['port']}/?token={endpoint['token']}"
            if not webbrowser.open(url, new=2):
                raise RuntimeError("El navegador predeterminado rechazó la apertura del panel.")
        return {"pid": endpoint["pid"], "port": endpoint["port"], "reused": not started}


def serve() -> int:
    root = project_root()
    directory = state_directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    _configure_logging(directory / "control-center.log")
    with _server_lock(directory / "server.lock") as acquired:
        if not acquired:
            LOGGER.info("Se rechazó una segunda instancia del centro de control.")
            return 0
        auth_token = secrets.token_urlsafe(36)
        csrf_token = secrets.token_urlsafe(32)
        settings = Settings.load(root / "config" / "jarvis.toml")
        tts_provider, _ = settings.effective_tts
        try:
            openjarvis_env = openjarvis_environment(settings, prepare_openjarvis_home(settings))
        except Exception:
            # OpenJarvis es un upgrade: si su hogar no se puede preparar, el
            # resto de Mark sigue funcionando y el panel queda sin política.
            LOGGER.exception("No se pudo preparar el hogar de OpenJarvis.")
            openjarvis_env = ()
        catalog = build_tool_catalog(
            root,
            voice_tts_provider=tts_provider,
            piper_voice_path=settings.tts_voice_path,
            voice_reference_path=settings.tts_clone_reference_path,
            voice_reference_text_path=settings.tts_clone_reference_text_path,
            voice_consent_path=settings.tts_clone_consent_path,
            openjarvis_engine=settings.openjarvis_engine,
            openjarvis_model=settings.model if settings.model_provider == "openjarvis" else "",
            openjarvis_environment=openjarvis_env,
        )
        manager = ProcessManager(catalog)
        system_monitor = SystemStatusMonitor(settings, manager)
        text_chat = TextChatRequestStore()
        voice_control = VoiceControlStore()
        database = Database(settings.database_path)
        project = ProjectService(database, PolicyEngine(settings)).ensure_bootstrap_project(
            "JarvisLocal", settings.project_dir
        )
        if settings.tts_clone_reference_path is None or settings.tts_clone_consent_path is None:
            raise RuntimeError("voice_clone.reference_path/consent_path no están configurados.")
        voice_importer = VoiceReferenceImporter(
            data_dir=settings.data_dir,
            reference_path=settings.tts_clone_reference_path,
            consent_path=settings.tts_clone_consent_path,
            database=database,
            project_id=project.id,
        )
        icon = root / "assets" / "mark-scout.ico"
        server = _bind_available_server(
            manager,
            auth_token,
            csrf_token,
            icon,
            root,
            voice_importer=voice_importer.import_base64,
            text_chat=text_chat,
            voice_control=voice_control,
            system_monitor=system_monitor,
        )
        endpoint = {
            "pid": os.getpid(),
            "port": server.server_address[1],
            "token": auth_token,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bind": HOST,
        }
        _write_endpoint(root, endpoint)
        LOGGER.info("Centro de control listo en http://%s:%s", HOST, endpoint["port"])
        try:
            server.serve_forever(poll_interval=0.25)
        finally:
            text_chat.close()
            voice_control.close()
            manager.stop_all()
            server.server_close()
            current = read_endpoint(root)
            if current and current.get("pid") == os.getpid():
                endpoint_path(root).unlink(missing_ok=True)
            LOGGER.info("Centro de control detenido.")
    return 0


def stop() -> bool:
    root = project_root()
    endpoint = read_endpoint(root)
    if endpoint is None or not health(endpoint):
        endpoint_path(root).unlink(missing_ok=True)
        return False
    request = urllib.request.Request(
        f"http://{HOST}:{endpoint['port']}/api/server/stop",
        method="POST",
        data=b"{}",
        headers={"Authorization": f"Bearer {endpoint['token']}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _bind_available_server(
    manager: ProcessManager,
    auth_token: str,
    csrf_token: str,
    icon: Path,
    root: Path | None = None,
    voice_importer=None,
    text_chat: TextChatRequestStore | None = None,
    voice_control: VoiceControlStore | None = None,
    system_monitor: SystemStatusMonitor | None = None,
) -> ControlCenterHTTPServer:
    project = root or project_root()
    last_error: OSError | None = None
    for port in PORT_RANGE:
        try:
            return ControlCenterHTTPServer(
                (HOST, port),
                manager,
                auth_token=auth_token,
                csrf_token=csrf_token,
                icon_path=icon,
                module_snapshot=lambda: build_module_snapshot(project),
                voice_importer=voice_importer,
                text_chat=text_chat,
                voice_control=voice_control,
                system_monitor=system_monitor,
                version="Mark Scout · Desktop Alpha",
            )
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"No hay un puerto libre entre 8765 y 8774: {last_error}")


def _spawn_server(root: Path) -> None:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    executable = pythonw if pythonw.is_file() else Path(sys.executable)
    directory = state_directory(root)
    log = (directory / "bootstrap.log").open("ab", buffering=0)
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    try:
        subprocess.Popen(
            [str(executable), "-m", "jarvis_local.control_center", "--serve"],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            close_fds=True,
            creationflags=flags,
        )
    finally:
        log.close()


def _write_endpoint(root: Path, endpoint: dict[str, object]) -> None:
    path = endpoint_path(root)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(endpoint, indent=2), encoding="utf-8")
    temporary.replace(path)
    if os.name == "nt":
        domain = os.environ.get("USERDOMAIN", "")
        user = os.environ.get("USERNAME", getpass.getuser())
        principal = f"{domain}\\{user}" if domain else user
        completed = subprocess.run(
            ["icacls.exe", str(path), "/inheritance:r", "/grant:r", f"{principal}:(R,W)"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if completed.returncode != 0:
            LOGGER.warning("No se pudo restringir endpoint.json con icacls.")


def _configure_logging(path: Path) -> None:
    logging.basicConfig(
        filename=path,
        level=logging.INFO,
        encoding="utf-8",
        format="%(asctime)s %(levelname)s %(message)s",
    )


@contextlib.contextmanager
def _launch_lock(path: Path, *, timeout_seconds: float) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            while time.monotonic() < deadline:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError:
                    time.sleep(0.1)
            if not acquired:
                raise TimeoutError("No se pudo adquirir el bloqueo de inicio.")
        yield
    finally:
        if acquired:
            import msvcrt

            handle.seek(0)
            with contextlib.suppress(OSError):
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()


@contextlib.contextmanager
def _server_lock(path: Path) -> Iterator[bool]:
    if os.name == "nt":
        # Un nombre fijo impide que la instalación principal y una copia de
        # desarrollo controlen el mismo micrófono/altavoz simultáneamente.
        with windows_singleton(r"Local\MarkScout.ControlCenter") as acquired:
            yield acquired
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    acquired = False
    try:
        acquired = True
        yield acquired
    finally:
        handle.close()
