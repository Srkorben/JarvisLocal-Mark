import asyncio
import tempfile
import unittest
from pathlib import Path

from openjarvis.core.types import Role
from openjarvis.engine._stubs import StreamChunk

from jarvis_local.cancellation import CancellationToken, OperationCancelled
from jarvis_local.config import Settings
from jarvis_local.model_providers import create_model_provider
from jarvis_local.model_providers.openjarvis_engine import (
    OpenJarvisProvider,
    to_openjarvis_messages,
)
from tests.mark.helpers import make_settings


class FakeEngine:
    def __init__(self, chunks, models=("qwen3:8b",), delay=0.0):
        self.chunks = chunks
        self.models = list(models)
        self.delay = delay
        self.calls = []

    def list_models(self):
        return self.models

    async def stream_full(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk


def provider_with(engine, root, engine_name="ollama", **updates):
    settings = make_settings(root, model_provider="openjarvis", model="qwen3:8b", **updates)
    return OpenJarvisProvider(settings, engine=engine, engine_name=engine_name)


class OpenJarvisProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_text_streaming_through_openjarvis_engine(self):
        engine = FakeEngine(
            [
                StreamChunk(content="Hola, "),
                StreamChunk(content="soy Mark."),
                StreamChunk(
                    finish_reason="stop",
                    usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
                ),
            ]
        )
        provider = provider_with(engine, self.root, think=False)
        deltas = []
        response = await provider.complete_chat(
            [{"role": "system", "content": "Eres Mark."}, {"role": "user", "content": "Hola"}],
            [],
            CancellationToken(),
            deltas.append,
        )
        self.assertEqual(response.content, "Hola, soy Mark.")
        self.assertEqual(deltas, ["Hola, ", "soy Mark."])
        self.assertEqual(response.usage.total_tokens, 14)
        messages, kwargs = engine.calls[0]
        self.assertEqual(messages[0].role, Role.SYSTEM)
        self.assertEqual(kwargs["model"], "qwen3:8b")
        self.assertIs(kwargs["think"], False)
        self.assertNotIn("tools", kwargs)

    async def test_tool_calls_reach_mark_orchestrator_format(self):
        engine = FakeEngine(
            [
                StreamChunk(
                    tool_calls=[
                        {
                            "index": 0,
                            "id": "call_0",
                            "type": "function",
                            "function": {
                                "name": "get_current_time",
                                "arguments": '{"timezone": "America/Bogota"}',
                            },
                        }
                    ]
                ),
                StreamChunk(finish_reason="tool_calls"),
            ]
        )
        provider = provider_with(engine, self.root)
        tools = [{"type": "function", "function": {"name": "get_current_time", "parameters": {}}}]
        response = await provider.complete_chat(
            [{"role": "user", "content": "¿Qué hora es?"}], tools, CancellationToken()
        )
        self.assertEqual(response.finish_reason, "tool_calls")
        self.assertEqual(len(response.tool_calls), 1)
        call = response.tool_calls[0]
        self.assertEqual(call.name, "get_current_time")
        self.assertEqual(call.arguments, {"timezone": "America/Bogota"})
        self.assertEqual(engine.calls[0][1]["tools"], tools)

    async def test_cancellation_stops_generation(self):
        engine = FakeEngine([StreamChunk(content="x")] * 50, delay=0.05)
        provider = provider_with(engine, self.root)
        token = CancellationToken()
        asyncio.get_running_loop().call_later(0.12, token.cancel, "Colgado")
        with self.assertRaises(OperationCancelled):
            await provider.complete_chat([{"role": "user", "content": "Hola"}], [], token)

    async def test_health_reports_missing_model(self):
        provider = provider_with(FakeEngine([], models=["llama3:8b"]), self.root)
        health = await provider.health()
        self.assertTrue(health.available)
        self.assertFalse(health.ready)
        ok = await provider_with(FakeEngine([]), self.root).health()
        self.assertTrue(ok.ready)
        self.assertEqual(ok.version, "OpenJarvis/ollama")

    async def test_factory_and_settings_accept_openjarvis(self):
        settings = make_settings(self.root, model_provider="openjarvis", openjarvis_engine="vllm")
        provider = await create_model_provider(settings)
        self.assertIsInstance(provider, OpenJarvisProvider)
        self.assertEqual(provider._engine_name, "vllm")

    def test_project_config_uses_openjarvis_brain(self):
        root = Path(__file__).resolve().parents[2]
        settings = Settings.load(root / "config" / "jarvis.toml")
        self.assertEqual(settings.model_provider, "openjarvis")
        self.assertEqual(settings.openjarvis_engine, "ollama")
        self.assertEqual(settings.model, "qwen3:8b")

    def test_history_with_tool_results_converts(self):
        converted = to_openjarvis_messages(
            [
                {"role": "user", "content": "hora"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "get_current_time", "arguments": {}},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "10:00"},
            ]
        )
        self.assertEqual([m.role for m in converted], [Role.USER, Role.ASSISTANT, Role.TOOL])
        self.assertEqual(converted[1].tool_calls[0].arguments, "{}")
        self.assertEqual(converted[2].tool_call_id, "c1")


if __name__ == "__main__":
    unittest.main()


class RealOllamaEngineTests(unittest.IsolatedAsyncioTestCase):
    """Mark -> OpenJarvis OllamaEngine -> HTTP (mocked), end to end."""

    async def test_streams_text_and_tools_from_ollama_engine(self):
        import json as _json

        import httpx
        import respx

        from openjarvis.engine.ollama import OllamaEngine

        lines = [
            {"message": {"content": "Revisando "}, "done": False},
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "git_status", "arguments": {"path": "."}}}
                    ],
                },
                "done": False,
            },
            {"message": {"content": ""}, "done": True, "done_reason": "stop",
             "prompt_eval_count": 12, "eval_count": 3},
        ]
        body = "\n".join(_json.dumps(line) for line in lines) + "\n"
        with tempfile.TemporaryDirectory() as directory, respx.mock(
            base_url="http://127.0.0.1:11434"
        ) as router:
            route = router.post("/api/chat").mock(
                return_value=httpx.Response(200, text=body)
            )
            engine = OllamaEngine(host="http://127.0.0.1:11434")
            provider = provider_with(engine, Path(directory), context_tokens=8192)
            response = await provider.complete_chat(
                [{"role": "user", "content": "estado del repo"}],
                [{"type": "function", "function": {"name": "git_status", "parameters": {}}}],
                CancellationToken(),
            )
            payload = _json.loads(route.calls[0].request.content)
        self.assertEqual(response.content, "Revisando ")
        self.assertEqual(response.tool_calls[0].name, "git_status")
        self.assertEqual(response.tool_calls[0].arguments, {"path": "."})
        self.assertEqual(response.finish_reason, "tool_calls")
        self.assertEqual(payload["model"], "qwen3:8b")
        self.assertIs(payload["think"], False)
        self.assertEqual(payload["options"]["num_ctx"], 8192)
        self.assertEqual(payload["tools"][0]["function"]["name"], "git_status")
