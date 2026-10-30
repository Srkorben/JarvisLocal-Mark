"""Tests for the in-process chat session behind the Mark desktop window."""

from __future__ import annotations

import pytest

from openjarvis.core.config import JarvisConfig
from openjarvis.core.types import Role
from openjarvis.mark_desktop.session import (
    MarkChatSession,
    plain_text,
    strip_reasoning,
)


class StreamingEngine:
    def __init__(self, tokens):
        self.tokens = tokens
        self.calls = []

    async def stream(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        for token in self.tokens:
            yield token

    def generate(self, messages, **kwargs):  # pragma: no cover - not reached
        raise AssertionError("stream should be used")


class GenerateOnlyEngine:
    async def stream(self, messages, **kwargs):
        raise NotImplementedError
        yield ""  # pragma: no cover

    def generate(self, messages, **kwargs):
        return {"content": "Respuesta completa."}


def _session(engine) -> MarkChatSession:
    config = JarvisConfig()
    config.agent.context_from_memory = False
    session = MarkChatSession(config, engine=engine, model="qwen3:8b")
    session.system_prompt = config.agent.default_system_prompt
    session.reset()
    return session


def test_default_identity_is_mark():
    assert "identify yourself as Mark" in JarvisConfig().agent.default_system_prompt


def test_send_streams_visible_text_and_keeps_history():
    engine = StreamingEngine(["<think>razono</think>", "Hola, ", "soy **Mark**."])
    session = _session(engine)
    seen = []

    reply = session.send("¿Quién eres?", on_text=seen.append)

    assert reply == "Hola, soy Mark."
    assert seen[-1] == "Hola, soy Mark."
    assert all("razono" not in text for text in seen)
    roles = [m.role for m in session.history]
    assert roles == [Role.SYSTEM, Role.USER, Role.ASSISTANT]
    assert session.history[-1].content == "Hola, soy **Mark**."
    messages, kwargs = engine.calls[0]
    assert messages[0].role == Role.SYSTEM
    assert kwargs["model"] == "qwen3:8b"


def test_falls_back_to_generate_without_streaming():
    session = _session(GenerateOnlyEngine())
    assert session.send("Hola") == "Respuesta completa."


def test_failed_turn_is_not_left_in_history():
    class Broken(GenerateOnlyEngine):
        def generate(self, messages, **kwargs):
            raise ConnectionError("Ollama no responde")

    session = _session(Broken())
    with pytest.raises(ConnectionError):
        session.send("Hola")
    assert [m.role for m in session.history] == [Role.SYSTEM]


def test_reset_keeps_only_system_prompt():
    session = _session(StreamingEngine(["Hola"]))
    session.send("Hola")
    session.reset()
    assert [m.role for m in session.history] == [Role.SYSTEM]


def test_send_requires_connection():
    session = MarkChatSession(JarvisConfig())
    with pytest.raises(RuntimeError):
        session.send("Hola")


def test_text_cleanup():
    assert strip_reasoning("<think>a\nb</think>Hola") == "Hola"
    assert strip_reasoning("<think>sin cerrar") == ""
    assert (
        plain_text("## Título\n- uno\n**dos** y `tres`") == "Título\n• uno\ndos y tres"
    )
