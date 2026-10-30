"""In-process chat session for the Mark desktop app.

No API server, no port and no login: the window talks to the inference engine
directly, the same way ``jarvis chat`` does, with Mark's system prompt and the
configured security guardrails.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, List, Optional

from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.core.events import EventBus
from openjarvis.core.types import Message, Role

logger = logging.getLogger(__name__)

_THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)


def strip_reasoning(text: str) -> str:
    """Hide ``<think>…</think>`` reasoning blocks (also while still open)."""
    return _THINK_BLOCK.sub("", text).lstrip()


def plain_text(text: str) -> str:
    """Readable/speakable text: no reasoning and no Markdown markers."""
    text = strip_reasoning(text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*)[-*]\s+", r"\1• ", text, flags=re.MULTILINE)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    return re.sub(r"`([^`]+)`", r"\1", text)


class _StatusConsole:
    """Adapter for helpers that expect a Rich console: forward plain text."""

    def __init__(self, sink: Callable[[str], None]) -> None:
        self._sink = sink

    def print(self, message: Any = "", *args: Any, **kwargs: Any) -> None:
        text = re.sub(r"\[/?[a-z][^\]]*\]", "", str(message)).strip()
        if text:
            self._sink(text)


class MarkChatSession:
    """One conversation with Mark, kept in memory while the window is open."""

    def __init__(
        self,
        config: Optional[JarvisConfig] = None,
        *,
        engine: Any = None,
        model: str = "",
        engine_name: str = "",
    ) -> None:
        self.config = config or load_config()
        self.bus = EventBus(record_history=False)
        self.engine = engine
        self.model = model
        self.engine_name = engine_name
        self.system_prompt = ""
        self.history: List[Message] = []
        self._memory_service: Any = None

    # -- setup ---------------------------------------------------------------

    def connect(self, status: Callable[[str], None] = lambda _msg: None) -> None:
        """Resolve engine + model and build Mark's system prompt."""
        if self.engine is None:
            from openjarvis.engine import get_engine
            from openjarvis.intelligence import register_builtin_models
            from openjarvis.mark_desktop.ollama_launcher import ensure_ollama
            from openjarvis.security import setup_security

            register_builtin_models()
            ensure_ollama(self.config, status)
            resolved = get_engine(self.config)
            if resolved is None:
                raise RuntimeError(
                    "No hay un motor de IA local disponible. Abre Ollama "
                    "(https://ollama.com) y vuelve a intentarlo."
                )
            self.engine_name, engine = resolved
            self.engine = setup_security(self.config, engine, self.bus).engine
        if not self.model:
            from openjarvis.cli._model_switch import resolve_chat_cli_model

            self.model = resolve_chat_cli_model(
                console=_StatusConsole(status),
                config=self.config,
                engine=self.engine,
                engine_name=self.engine_name,
                cli_model=None,
                chat_variant="chat",
            )
            if not self.model:
                raise RuntimeError(
                    "Ollama no tiene modelos. Descarga uno, por ejemplo: "
                    "ollama pull qwen3:8b"
                )
        from openjarvis.prompt.builder import SystemPromptBuilder

        self.system_prompt = SystemPromptBuilder(
            agent_template=self.config.agent.default_system_prompt or "",
            memory_files_config=self.config.memory_files,
            system_prompt_config=self.config.system_prompt,
        ).build()
        self.reset()
        try:
            from openjarvis.memory import build_memory_service

            self._memory_service = build_memory_service(
                self.config, self.engine, self.model, event_bus=self.bus
            )
            if self._memory_service is not None:
                self._memory_service.start()
        except Exception:
            logger.debug("Memory service unavailable", exc_info=True)
            self._memory_service = None

    def reset(self) -> None:
        """Start a new conversation."""
        self.history = []
        if self.system_prompt:
            self.history.append(Message(role=Role.SYSTEM, content=self.system_prompt))

    def close(self) -> None:
        if self._memory_service is not None:
            try:
                self._memory_service.stop()
            except Exception:
                logger.debug("Memory service stop failed", exc_info=True)
            self._memory_service = None

    # -- chat ----------------------------------------------------------------

    def _messages_for(self, user_text: str) -> List[Message]:
        if not self.config.agent.context_from_memory:
            return self.history
        try:
            from openjarvis.memory import load_configured_facts
            from openjarvis.tools.storage.context import ContextConfig, inject_context

            service = self._memory_service
            facts = (
                service.list_facts()
                if service is not None and hasattr(service, "list_facts")
                else load_configured_facts(self.config)
            )
            ctx = ContextConfig(
                top_k=self.config.memory.context_top_k,
                min_score=self.config.memory.context_min_score,
                max_context_tokens=self.config.memory.context_max_tokens,
            )
            return inject_context(
                user_text, self.history, None, config=ctx, facts=facts
            )
        except Exception:
            logger.debug("Memory context unavailable", exc_info=True)
            return self.history

    def send(
        self,
        user_text: str,
        on_text: Callable[[str], None] = lambda _text: None,
    ) -> str:
        """Send *user_text* and return the visible reply.

        ``on_text`` receives the visible reply so far while it streams.
        """
        if self.engine is None:
            raise RuntimeError("La sesión no está conectada")
        self.history.append(Message(role=Role.USER, content=user_text))
        messages = list(self._messages_for(user_text))
        kwargs = {
            "model": self.model,
            "temperature": self.config.intelligence.temperature,
            "max_tokens": self.config.intelligence.max_tokens,
        }
        try:
            raw = self._stream(messages, kwargs, on_text)
        except Exception:
            self.history.pop()
            raise
        reply = strip_reasoning(raw).strip()
        visible = plain_text(reply).strip()
        on_text(visible)
        self.history.append(Message(role=Role.ASSISTANT, content=reply))
        try:
            from openjarvis.memory import publish_completed_exchange

            publish_completed_exchange(
                self.bus, user_text, reply, source="mark.desktop"
            )
        except Exception:
            logger.debug("Could not publish exchange", exc_info=True)
        return visible

    def _stream(
        self,
        messages: List[Message],
        kwargs: dict,
        on_text: Callable[[str], None],
    ) -> str:
        parts: List[str] = []

        async def collect() -> None:
            async for token in self.engine.stream(messages, **kwargs):
                if token:
                    parts.append(token)
                    on_text(plain_text("".join(parts)))

        try:
            asyncio.run(collect())
        except NotImplementedError:
            parts = []
        if parts:
            return "".join(parts)
        result = self.engine.generate(messages, **kwargs)
        return result.get("content", "") if isinstance(result, dict) else str(result)


__all__ = ["MarkChatSession", "plain_text", "strip_reasoning"]
