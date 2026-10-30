"""Mark voice TTS backend — Mark's own cloned voice via Qwen3-TTS.

Qwen3-TTS (torch + CUDA) lives in its own Python environment so it never
conflicts with the main OpenJarvis install. This backend starts
``qwen3_tts_worker.py`` with that interpreter and talks to it over a JSONL
pipe: one ``{"command": "synthesize", ...}`` line in, one line with base64
PCM16 out. The model loads once and stays resident between turns.

The backend fails closed: ``health()`` is ``False`` until the isolated env,
the model files, the reference sample, its transcription and a consent
manifest bound to the sample's SHA-256 are all present. OpenJarvis then falls
back to the next TTS backend (Kokoro, local).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.mark_voice.consent import (
    VoiceConsentError,
    validate_own_voice_consent,
)
from openjarvis.speech.tts import TTSBackend, TTSResult

logger = logging.getLogger(__name__)

WORKER_SCRIPT = Path(__file__).with_name("qwen3_tts_worker.py")
MODEL_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer_config.json",
    "speech_tokenizer/config.json",
    "speech_tokenizer/model.safetensors",
)
# The worker rejects requests over 1000 characters; leave headroom.
_MAX_CHUNK_CHARS = 900
_SENTENCE_END = re.compile(r"(?<=[.!?¡¿;:…])\s+")


def mark_voice_home() -> Path:
    from openjarvis.core.paths import get_config_dir

    return get_config_dir() / "mark-voice"


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _default_reference(home: Path) -> Path:
    for suffix in (".wav", ".mp3", ".flac", ".m4a", ".ogg"):
        candidate = home / f"reference{suffix}"
        if candidate.is_file():
            return candidate
    return home / "reference.wav"


@dataclass(frozen=True)
class MarkVoiceSettings:
    python: Path
    model_dir: Path
    reference_path: Path
    reference_text_path: Path
    consent_path: Path
    log_path: Path
    device: str = "cuda"
    language: str = "Spanish"
    timeout_seconds: float = 240.0
    temperature: float = 0.65
    top_k: int = 30
    top_p: float = 0.9
    subtalker_temperature: float = 0.65
    subtalker_top_k: int = 30
    subtalker_top_p: float = 0.9
    seed: int = 42

    @classmethod
    def from_config(cls, cfg: Any = None) -> "MarkVoiceSettings":
        """Build settings from ``[speech.mark_voice]``, filling default paths."""
        if cfg is None:
            try:
                from openjarvis.core.config import load_config

                cfg = load_config().speech.mark_voice
            except Exception:
                logger.debug("Could not load [speech.mark_voice]", exc_info=True)
                from openjarvis.core.config import MarkVoiceConfig

                cfg = MarkVoiceConfig()
        home = mark_voice_home()

        def path(value: str, default: Path) -> Path:
            return Path(value).expanduser() if value else default

        return cls(
            python=path(cfg.python, _venv_python(home / ".venv")),
            model_dir=path(cfg.model_dir, home / "models" / "qwen3-tts-12hz-0.6b-base"),
            reference_path=path(cfg.reference_path, _default_reference(home)),
            reference_text_path=path(cfg.reference_text_path, home / "reference.txt"),
            consent_path=path(cfg.consent_path, home / "consent.json"),
            log_path=home / "logs" / "qwen3-tts-worker.log",
            device=cfg.device,
            language=cfg.language,
            timeout_seconds=float(cfg.timeout_seconds),
            temperature=cfg.temperature,
            top_k=cfg.top_k,
            top_p=cfg.top_p,
            subtalker_temperature=cfg.subtalker_temperature,
            subtalker_top_k=cfg.subtalker_top_k,
            subtalker_top_p=cfg.subtalker_top_p,
            seed=cfg.seed,
        )

    def problems(self) -> List[str]:
        """Return human-readable reasons the voice cannot run (empty = ready)."""
        issues: List[str] = []
        if not self.python.is_file():
            issues.append(f"No existe el Python aislado de Qwen3-TTS: {self.python}")
        absent = [n for n in MODEL_FILES if not (self.model_dir / n).is_file()]
        if absent:
            issues.append("Faltan archivos de Qwen3-TTS: " + ", ".join(absent))
        if not self.reference_text_path.is_file():
            issues.append("Falta la transcripción de la referencia de voz.")
        elif not self.reference_text_path.read_text(encoding="utf-8").strip():
            issues.append("La transcripción de la referencia de voz está vacía.")
        try:
            validate_own_voice_consent(self.reference_path, self.consent_path)
        except VoiceConsentError as exc:
            issues.append(str(exc))
        return issues

    def command(self) -> List[str]:
        return [
            str(self.python),
            str(WORKER_SCRIPT),
            "--model-dir",
            str(self.model_dir),
            "--reference",
            str(self.reference_path),
            "--reference-text",
            str(self.reference_text_path),
            "--device",
            self.device,
            "--language",
            self.language,
            "--temperature",
            str(self.temperature),
            "--top-k",
            str(self.top_k),
            "--top-p",
            str(self.top_p),
            "--subtalker-temperature",
            str(self.subtalker_temperature),
            "--subtalker-top-k",
            str(self.subtalker_top_k),
            "--subtalker-top-p",
            str(self.subtalker_top_p),
            "--seed",
            str(self.seed),
        ]


def split_for_synthesis(text: str, limit: int = _MAX_CHUNK_CHARS) -> List[str]:
    """Split *text* into chunks of at most *limit* chars on sentence breaks."""
    text = " ".join(text.split())
    if not text:
        return []
    chunks: List[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        chunks.append(current)
    return chunks


def pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm)
    return buffer.getvalue()


class _Worker:
    """A running ``qwen3_tts_worker.py`` process with a JSONL channel."""

    def __init__(self, settings: MarkVoiceSettings) -> None:
        self._settings = settings
        self._next_id = 0
        settings.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = settings.log_path.open("ab")
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        env = dict(os.environ, PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1")
        self._process = subprocess.Popen(
            settings.command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._log,
            env=env,
            creationflags=creation_flags,
        )
        self._lines: "queue.Queue[Optional[bytes]]" = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        ready = self._read(settings.timeout_seconds)
        if ready.get("type") != "ready":
            self.close()
            raise RuntimeError(f"Worker de voz de Mark no inició: {ready}")

    def _pump(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _read(self, timeout: float) -> dict:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise TimeoutError("El worker de voz de Mark no respondió a tiempo")
        if line is None:
            raise RuntimeError(
                f"El worker de voz de Mark terminó; revisa {self._settings.log_path}"
            )
        return json.loads(line.decode("utf-8"))

    @property
    def alive(self) -> bool:
        return self._process.poll() is None

    def synthesize(self, text: str) -> tuple[bytes, int]:
        assert self._process.stdin is not None
        self._next_id += 1
        request = {"id": self._next_id, "command": "synthesize", "text": text}
        self._process.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        self._process.stdin.flush()
        reply = self._read(self._settings.timeout_seconds)
        if not reply.get("ok"):
            error = reply.get("error") or {}
            raise RuntimeError(error.get("message") or "Síntesis fallida")
        pcm = base64.b64decode(reply["pcm16_base64"])
        return pcm, int(reply.get("sample_rate", 24000))

    def close(self) -> None:
        if self._process.poll() is None:
            try:
                assert self._process.stdin is not None
                self._process.stdin.write(b'{"command":"close"}\n')
                self._process.stdin.flush()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
        self._log.close()


@TTSRegistry.register("mark_voice")
class MarkVoiceTTSBackend(TTSBackend):
    """Mark's own cloned voice (Qwen3-TTS Base 0.6B, local, zero-shot)."""

    backend_id = "mark_voice"

    def __init__(self, *, settings: Optional[MarkVoiceSettings] = None) -> None:
        self._settings = settings or MarkVoiceSettings.from_config()
        self._worker: Optional[_Worker] = None
        self._lock = threading.Lock()

    def _ensure_worker(self) -> _Worker:
        if self._worker is None or not self._worker.alive:
            issues = self._settings.problems()
            if issues:
                raise RuntimeError("Voz de Mark no disponible: " + " ".join(issues))
            self._worker = _Worker(self._settings)
        return self._worker

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "mark",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        chunks = split_for_synthesis(text)
        if not chunks:
            raise ValueError("No hay texto para sintetizar")
        pcm = bytearray()
        sample_rate = 24000
        with self._lock:
            worker = self._ensure_worker()
            for chunk in chunks:
                audio, sample_rate = worker.synthesize(chunk)
                pcm.extend(audio)
        # Qwen3-TTS has no speed control and the worker only emits PCM, so the
        # result is always WAV regardless of the requested format.
        return TTSResult(
            audio=pcm16_to_wav(bytes(pcm), sample_rate),
            format="wav",
            duration_seconds=len(pcm) / 2 / sample_rate,
            voice_id="mark",
            sample_rate=sample_rate,
            metadata={"backend": "mark_voice", "model": "Qwen3-TTS-12Hz-0.6B-Base"},
        )

    def available_voices(self) -> List[str]:
        return ["mark"]

    def health(self) -> bool:
        issues = self._settings.problems()
        for issue in issues:
            logger.debug("mark_voice: %s", issue)
        return not issues

    def close(self) -> None:
        with self._lock:
            if self._worker is not None:
                self._worker.close()
                self._worker = None

    def __del__(self) -> None:  # pragma: no cover - best effort cleanup
        try:
            if self._worker is not None and sys is not None:
                self._worker.close()
        except Exception:
            pass


__all__ = [
    "MarkVoiceSettings",
    "MarkVoiceTTSBackend",
    "mark_voice_home",
    "pcm16_to_wav",
    "split_for_synthesis",
]
