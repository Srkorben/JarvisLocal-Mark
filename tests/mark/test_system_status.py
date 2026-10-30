import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from jarvis_local.control_center.system_status import (
    SystemStatusMonitor,
    _read_nvidia_gpu,
)
from tests.mark.helpers import make_settings


class FakeManager:
    def __init__(self) -> None:
        self.tools = [
            {"id": "chat_runtime", "status": "available", "started_at": None},
            {"id": "voice", "status": "available", "started_at": None},
        ]

    def list_status(self):
        return [dict(item) for item in self.tools]


class SystemStatusMonitorTests(TestCase):
    def test_cache_and_safe_model_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            calls = []
            now = [10.0]

            def hardware():
                calls.append(True)
                return {
                    "cpu": {"available": True, "percent": 12.5},
                    "ram": {
                        "available": True,
                        "used_mib": 100,
                        "total_mib": 200,
                        "percent": 50.0,
                    },
                    "gpu": {"available": False, "reason": "nvidia_smi_missing"},
                }

            settings = make_settings(
                root,
                model_provider="llama_cpp",
                model="qwen3-8b-q4_k_m",
                context_tokens=8192,
            )
            manager = FakeManager()
            monitor = SystemStatusMonitor(
                settings,
                manager,
                cache_ttl_seconds=2,
                hardware_reader=hardware,
                clock=lambda: now[0],
            )
            first = monitor.snapshot({"state": "offline", "error": ""})
            second = monitor.snapshot({"state": "offline", "error": ""})
            self.assertEqual(len(calls), 1)
            self.assertEqual(first["model"]["name"], "qwen3-8b-q4_k_m")
            self.assertNotIn("path", str(first).casefold())
            self.assertEqual(second["cpu"]["percent"], 12.5)
            now[0] = 12.1
            monitor.snapshot({"state": "offline", "error": ""})
            self.assertEqual(len(calls), 2)

    def test_core_precedence_initializing_processing_cancelling_error(self) -> None:
        with TemporaryDirectory() as directory:
            manager = FakeManager()
            manager.tools[0]["status"] = "running"
            monitor = SystemStatusMonitor(
                make_settings(Path(directory)),
                manager,
                hardware_reader=lambda: {},
            )
            expected = {
                "offline": "initializing",
                "loading": "initializing",
                "idle": "available",
                "processing": "processing",
                "cancelling": "cancelling",
                "error": "error",
            }
            for presence, state in expected.items():
                with self.subTest(presence=presence):
                    snapshot = monitor.snapshot({"state": presence, "error": "fallo"})
                    self.assertEqual(snapshot["core"]["state"], state)
            manager.tools[0]["status"] = "available"
            self.assertEqual(
                monitor.snapshot({"state": "idle", "error": ""})["core"]["state"],
                "off",
            )

    def test_nvidia_parser_and_timeout(self) -> None:
        def successful(command, **kwargs):
            self.assertEqual(command[0], "nvidia-smi")
            self.assertEqual(kwargs["timeout"], 0.8)
            return subprocess.CompletedProcess(
                command, 0, "NVIDIA RTX 5060 Laptop GPU, 42, 3072, 8192\n", ""
            )

        gpu = _read_nvidia_gpu(successful)
        self.assertTrue(gpu["available"])
        self.assertEqual(gpu["memory_percent"], 37.5)
        self.assertEqual(gpu["name"], "NVIDIA RTX 5060 Laptop GPU")

        def timeout(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        self.assertEqual(_read_nvidia_gpu(timeout)["reason"], "timeout")

    def test_hardware_failure_is_reported_without_exception_details(self) -> None:
        with TemporaryDirectory() as directory:
            monitor = SystemStatusMonitor(
                make_settings(Path(directory)),
                FakeManager(),
                hardware_reader=lambda: (_ for _ in ()).throw(RuntimeError("private path")),
            )
            snapshot = monitor.snapshot({"state": "offline"})
            for name in ("cpu", "ram", "gpu"):
                self.assertFalse(snapshot[name]["available"])
                self.assertEqual(snapshot[name]["reason"], "measurement_failed")
            self.assertNotIn("private path", str(snapshot))
