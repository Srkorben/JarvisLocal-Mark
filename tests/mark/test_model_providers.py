import asyncio
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from jarvis_local.cancellation import CancellationToken, OperationCancelled
from jarvis_local.model_providers import ModelProviderError, create_model_provider
from jarvis_local.model_providers.llama_cpp import LlamaCppProvider
from jarvis_local.model_providers.ollama import OllamaProvider
from tests.mark.helpers import make_settings


class _SseServer:
    def __init__(self, events: list[dict], delay_seconds: float = 0.0):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                return None

            def do_GET(self):
                if self.path == "/health":
                    self._json({"status": "ok"})
                elif self.path == "/v1/models":
                    self._json({"data": [{"id": "test-model"}]})
                else:
                    self.send_error(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for event in owner.events:
                        if owner.delay_seconds:
                            time.sleep(owner.delay_seconds)
                        data = json.dumps(event).encode("utf-8")
                        self.wfile.write(b"data: " + data + b"\n\n")
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except OSError:
                    owner.client_disconnected.set()

            def _json(self, payload):
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.events = events
        self.delay_seconds = delay_seconds
        self.client_disconnected = threading.Event()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01),
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class ModelProviderTests(IsolatedAsyncioTestCase):
    async def test_factory_switches_between_providers(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ollama = await create_model_provider(make_settings(root), allow_start=False)
            llama = await create_model_provider(
                make_settings(
                    root,
                    model_provider="llama_cpp",
                    model_base_url="http://127.0.0.1:8080/v1",
                ),
                allow_start=False,
            )
            self.assertIsInstance(ollama, OllamaProvider)
            self.assertIsInstance(llama, LlamaCppProvider)

    async def test_unavailable_provider_has_structured_health(self) -> None:
        with TemporaryDirectory() as directory:
            port = _unused_port()
            provider = LlamaCppProvider(
                make_settings(
                    Path(directory),
                    model_provider="llama_cpp",
                    model_base_url=f"http://127.0.0.1:{port}/v1",
                )
            )
            health = await provider.health()
            self.assertFalse(health.available)
            self.assertFalse(health.ready)
            self.assertEqual(health.provider, "llama_cpp")

    async def test_streams_normal_response_and_usage(self) -> None:
        events = [
            {"choices": [{"delta": {"content": "Hola "}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": "mundo"}, "finish_reason": "stop"}]},
            {
                "choices": [],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        ]
        with TemporaryDirectory() as directory, _SseServer(events) as server:
            settings = make_settings(
                Path(directory),
                model_provider="llama_cpp",
                model_base_url=f"http://127.0.0.1:{server.port}/v1",
            )
            response = await LlamaCppProvider(settings).complete_chat(
                [{"role": "user", "content": "Hola"}],
                [],
                CancellationToken(),
            )
            self.assertEqual(response.content, "Hola mundo")
            self.assertEqual(response.usage.completion_tokens, 2)
            self.assertIsNotNone(response.metrics.first_token_seconds)

    async def test_streams_valid_tool_call(self) -> None:
        events = [
            {
                "choices": [{
                    "delta": {"tool_calls": [{
                        "index": 0,
                        "id": "call-1",
                        "function": {"name": "get_current_time", "arguments": "{\"expected_"},
                    }]},
                    "finish_reason": None,
                }]
            },
            {
                "choices": [{
                    "delta": {"tool_calls": [{
                        "index": 0,
                        "function": {"arguments": "result\":\"hora local\"}"},
                    }]},
                    "finish_reason": "tool_calls",
                }]
            },
        ]
        with TemporaryDirectory() as directory, _SseServer(events) as server:
            settings = make_settings(
                Path(directory),
                model_provider="llama_cpp",
                model_base_url=f"http://127.0.0.1:{server.port}/v1",
            )
            response = await LlamaCppProvider(settings).complete_chat(
                [{"role": "user", "content": "hora"}], [], CancellationToken()
            )
            self.assertEqual(response.tool_calls[0].name, "get_current_time")
            self.assertEqual(response.tool_calls[0].arguments["expected_result"], "hora local")

    async def test_invalid_unicode_from_model_is_safe_for_next_json_round(self) -> None:
        events = [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-unicode",
                                    "function": {
                                        "name": "get_current_time",
                                        "arguments": '{"expected_result":"hora \\udced local"}',
                                    },
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        ]
        with TemporaryDirectory() as directory, _SseServer(events) as server:
            settings = make_settings(
                Path(directory),
                model_provider="llama_cpp",
                model_base_url=f"http://127.0.0.1:{server.port}/v1",
            )
            response = await LlamaCppProvider(settings).complete_chat(
                [{"role": "user", "content": "hora"}], [], CancellationToken()
            )
            value = response.tool_calls[0].arguments["expected_result"]
            self.assertEqual(value, "hora ? local")
            json.dumps(response.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")

    async def test_invalid_tool_json_is_structured_error(self) -> None:
        events = [{
            "choices": [{
                "delta": {"tool_calls": [{
                    "index": 0,
                    "function": {"name": "get_current_time", "arguments": "{invalid"},
                }]},
                "finish_reason": "tool_calls",
            }]
        }]
        with TemporaryDirectory() as directory, _SseServer(events) as server:
            settings = make_settings(
                Path(directory),
                model_provider="llama_cpp",
                model_base_url=f"http://127.0.0.1:{server.port}/v1",
            )
            with self.assertRaises(ModelProviderError) as caught:
                await LlamaCppProvider(settings).complete_chat([], [], CancellationToken())
            self.assertEqual(caught.exception.code, "invalid_tool_arguments")

    async def test_cancellation_closes_generation_stream(self) -> None:
        events = [
            {"choices": [{"delta": {"content": str(index)}, "finish_reason": None}]}
            for index in range(20)
        ]
        with TemporaryDirectory() as directory, _SseServer(events, 0.1) as server:
            settings = make_settings(
                Path(directory),
                model_provider="llama_cpp",
                model_base_url=f"http://127.0.0.1:{server.port}/v1",
                request_timeout_seconds=5,
            )
            token = CancellationToken()
            task = asyncio.create_task(
                LlamaCppProvider(settings).complete_chat([], [], token)
            )
            await asyncio.sleep(0.15)
            token.cancel("prueba de cancelación")
            with self.assertRaises(OperationCancelled):
                await asyncio.wait_for(task, timeout=1)

    async def test_stream_timeout_is_structured(self) -> None:
        events = [{"choices": [{"delta": {"content": "tarde"}, "finish_reason": "stop"}]}]
        with TemporaryDirectory() as directory, _SseServer(events, 0.2) as server:
            settings = make_settings(
                Path(directory),
                model_provider="llama_cpp",
                model_base_url=f"http://127.0.0.1:{server.port}/v1",
                request_timeout_seconds=0.05,
            )
            with self.assertRaises(ModelProviderError) as caught:
                await LlamaCppProvider(settings).complete_chat([], [], CancellationToken())
            self.assertEqual(caught.exception.code, "timeout")
