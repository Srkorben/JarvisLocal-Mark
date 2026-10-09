from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import subprocess
import threading
import uuid
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from ..audio.enrollment import (
    create_authorized_voice_consent,
    sha256_file,
    write_reference_wav,
)
from ..audio.models import AudioBuffer
from ..database import Database


MAX_SOURCE_BYTES = 24 * 1024 * 1024
MIN_DURATION_SECONDS = 15.0
MAX_DURATION_SECONDS = 30.0
TARGET_SAMPLE_RATE = 24_000
MIN_RMS = 120.0
ALLOWED_EXTENSIONS = frozenset(
    {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wma"}
)


class VoiceImportError(RuntimeError):
    def __init__(self, code: str, message: str, *, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class VoiceImportResult:
    duration_seconds: float
    reference_sha256: str
    source_extension: str
    replaced_existing: bool
    backup_created: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "outcome": "imported",
            "duration_seconds": round(self.duration_seconds, 3),
            "reference_sha256": self.reference_sha256,
            "source_extension": self.source_extension,
            "replaced_existing": self.replaced_existing,
            "backup_created": self.backup_created,
        }


class VoiceReferenceImporter:
    """Importa una única referencia activa sin aceptar rutas ni comandos del navegador."""

    def __init__(
        self,
        *,
        data_dir: Path,
        reference_path: Path,
        consent_path: Path,
        database: Database,
        project_id: str,
        ffmpeg_executable: Path | None = None,
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.reference_path = reference_path.resolve()
        self.consent_path = consent_path.resolve()
        self.database = database
        self.project_id = project_id
        discovered = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
        self.ffmpeg_executable = (
            ffmpeg_executable.resolve()
            if ffmpeg_executable
            else Path(discovered).resolve()
            if discovered
            else None
        )
        self._lock = threading.Lock()
        self._validate_destinations()

    def import_base64(
        self,
        *,
        filename: str,
        audio_base64: str,
        authorization_confirmed: bool,
        replace_existing: bool,
    ) -> dict[str, object]:
        if authorization_confirmed is not True:
            raise VoiceImportError(
                "authorization_required",
                "Confirma que eres titular de la voz o que tienes permiso del titular.",
                http_status=409,
            )
        extension = self._validate_filename(filename)
        try:
            raw = base64.b64decode(audio_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise VoiceImportError("audio_invalid", "El audio no contiene Base64 válido.") from exc
        if not raw:
            raise VoiceImportError("audio_empty", "El archivo de audio está vacío.")
        if len(raw) > MAX_SOURCE_BYTES:
            raise VoiceImportError(
                "audio_too_large",
                f"El audio supera el máximo local de {MAX_SOURCE_BYTES // (1024 * 1024)} MiB.",
                http_status=413,
            )

        if not self._lock.acquire(blocking=False):
            raise VoiceImportError(
                "import_in_progress",
                "Ya hay una importación de voz en curso.",
                http_status=409,
            )
        try:
            return self._import_bytes(
                raw=raw,
                extension=extension,
                replace_existing=replace_existing,
            ).as_dict()
        finally:
            self._lock.release()

    def _import_bytes(
        self, *, raw: bytes, extension: str, replace_existing: bool
    ) -> VoiceImportResult:
        had_reference = self.reference_path.exists()
        had_consent = self.consent_path.exists()
        if (had_reference or had_consent) and not replace_existing:
            raise VoiceImportError(
                "reference_exists",
                "Ya existe una referencia. Confirma explícitamente su reemplazo recuperable.",
                http_status=409,
            )

        voice_dir = self.reference_path.parent
        voice_dir.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".voice-import-", dir=voice_dir) as directory:
            temporary = Path(directory)
            source = temporary / f"source{extension}"
            normalized = temporary / "reference.wav"
            staged_consent = temporary / "consent.json"
            source.write_bytes(raw)
            audio = self._decode_and_normalize(source, extension)
            self._validate_audio(audio)
            write_reference_wav(normalized, audio)
            record = create_authorized_voice_consent(
                reference_path=normalized,
                consent_path=staged_consent,
                duration_seconds=audio.duration_seconds,
                source_extension=extension,
            )

            backup_dir = self._backup_existing() if had_reference or had_consent else None
            try:
                os.replace(normalized, self.reference_path)
                os.replace(staged_consent, self.consent_path)
                self.database.record_audit(
                    session_id=None,
                    project_id=self.project_id,
                    event_type="voice_reference_import",
                    outcome="success",
                    confirmation={
                        "source": "trusted_local_ui",
                        "authorization_confirmed": True,
                        "scope": "local_tts_reference_only",
                    },
                    detail={
                        "reference_sha256": record["reference_sha256"],
                        "duration_seconds": record["duration_seconds"],
                        "source_extension": extension,
                        "replaced_existing": had_reference or had_consent,
                        "backup_created": backup_dir is not None,
                        "audio_content_stored_in_audit": False,
                        "original_filename_stored_in_audit": False,
                    },
                )
            except Exception as exc:
                self._restore_backup(backup_dir, had_reference, had_consent)
                raise VoiceImportError(
                    "import_failed",
                    "No se pudo activar la muestra; se restauró el estado anterior.",
                    http_status=500,
                ) from exc

        return VoiceImportResult(
            duration_seconds=audio.duration_seconds,
            reference_sha256=sha256_file(self.reference_path),
            source_extension=extension,
            replaced_existing=had_reference or had_consent,
            backup_created=backup_dir is not None,
        )

    def _decode_and_normalize(self, source: Path, extension: str) -> AudioBuffer:
        if extension == ".wav":
            return self._read_wave(source)
        if self.ffmpeg_executable is None or not self.ffmpeg_executable.is_file():
            raise VoiceImportError(
                "ffmpeg_unavailable",
                "Este formato requiere FFmpeg local. Usa WAV o instala FFmpeg.",
                http_status=503,
            )
        converted = source.with_name("decoded.wav")
        try:
            completed = subprocess.run(
                [
                    str(self.ffmpeg_executable),
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(source),
                    "-t",
                    str(MAX_DURATION_SECONDS + 1),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    str(TARGET_SAMPLE_RATE),
                    "-c:a",
                    "pcm_s16le",
                    "-y",
                    str(converted),
                ],
                capture_output=True,
                check=False,
                timeout=45,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise VoiceImportError("audio_decode_failed", "FFmpeg no pudo procesar el audio.") from exc
        if completed.returncode != 0 or not converted.is_file():
            raise VoiceImportError("audio_decode_failed", "El formato o contenido del audio no es válido.")
        return self._read_wave(converted)

    def _read_wave(self, path: Path) -> AudioBuffer:
        try:
            with wave.open(str(path), "rb") as source:
                channels = source.getnchannels()
                sample_width = source.getsampwidth()
                sample_rate = source.getframerate()
                frame_count = source.getnframes()
                compression = source.getcomptype()
                frames = source.readframes(frame_count)
        except (OSError, EOFError, wave.Error) as exc:
            raise VoiceImportError("audio_decode_failed", "El archivo WAV no es PCM válido.") from exc
        if compression != "NONE" or channels not in {1, 2} or sample_width not in {1, 2, 3, 4}:
            raise VoiceImportError("audio_unsupported", "El WAV debe ser PCM mono o estéreo.")
        if sample_rate < 8_000 or sample_rate > 192_000 or frame_count <= 0:
            raise VoiceImportError("audio_unsupported", "La frecuencia o duración del WAV no es válida.")
        samples = self._pcm_to_float(frames, sample_width)
        try:
            samples = samples.reshape(-1, channels).mean(axis=1)
        except ValueError as exc:
            raise VoiceImportError("audio_decode_failed", "Los cuadros PCM están incompletos.") from exc
        if sample_rate != TARGET_SAMPLE_RATE:
            target_count = max(1, round(samples.size * TARGET_SAMPLE_RATE / sample_rate))
            old_positions = np.linspace(0.0, 1.0, samples.size, endpoint=False)
            new_positions = np.linspace(0.0, 1.0, target_count, endpoint=False)
            samples = np.interp(new_positions, old_positions, samples)
        pcm = np.clip(np.rint(samples), -32768, 32767).astype(np.int16)
        rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2))) if pcm.size else 0.0
        return AudioBuffer(
            samples=pcm,
            sample_rate=TARGET_SAMPLE_RATE,
            duration_seconds=pcm.size / TARGET_SAMPLE_RATE,
            rms=rms,
        )

    @staticmethod
    def _pcm_to_float(frames: bytes, sample_width: int) -> np.ndarray:
        if sample_width == 1:
            return (np.frombuffer(frames, dtype=np.uint8).astype(np.float64) - 128.0) * 256.0
        if sample_width == 2:
            return np.frombuffer(frames, dtype="<i2").astype(np.float64)
        if sample_width == 4:
            return (np.frombuffer(frames, dtype="<i4").astype(np.float64) / 65536.0)
        raw = np.frombuffer(frames, dtype=np.uint8)
        if raw.size % 3:
            raise VoiceImportError("audio_decode_failed", "Las muestras PCM24 están incompletas.")
        triples = raw.reshape(-1, 3).astype(np.int32)
        values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
        values = np.where(values & 0x800000, values - 0x1000000, values)
        return values.astype(np.float64) / 256.0

    @staticmethod
    def _validate_audio(audio: AudioBuffer) -> None:
        if not MIN_DURATION_SECONDS <= audio.duration_seconds <= MAX_DURATION_SECONDS:
            raise VoiceImportError(
                "duration_invalid",
                f"La muestra debe durar entre {MIN_DURATION_SECONDS:.0f} y {MAX_DURATION_SECONDS:.0f} segundos; dura {audio.duration_seconds:.2f}.",
            )
        if audio.rms < MIN_RMS:
            raise VoiceImportError("audio_too_quiet", "La muestra está vacía o tiene un volumen demasiado bajo.")

    @staticmethod
    def _validate_filename(filename: str) -> str:
        if not isinstance(filename, str) or not filename or len(filename) > 180:
            raise VoiceImportError("filename_invalid", "El nombre del archivo no es válido.")
        if (
            "/" in filename
            or "\\" in filename
            or Path(filename).name != filename
            or any(ord(char) < 32 for char in filename)
        ):
            raise VoiceImportError("filename_invalid", "Solo se admite el nombre local del archivo, sin rutas.")
        extension = Path(filename).suffix.casefold()
        if extension not in ALLOWED_EXTENSIONS:
            raise VoiceImportError(
                "format_unsupported",
                "Formato no admitido. Usa WAV, MP3, M4A, FLAC, OGG, OPUS, AAC o WMA.",
            )
        return extension

    def _validate_destinations(self) -> None:
        for path in (self.reference_path, self.consent_path):
            try:
                path.relative_to(self.data_dir)
            except ValueError as exc:
                raise ValueError("La referencia y el consentimiento deben permanecer dentro de data_dir.") from exc

    def _backup_existing(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = self.reference_path.parent / "history" / stamp
        backup.mkdir(parents=True, exist_ok=False)
        if self.reference_path.is_file():
            shutil.copy2(self.reference_path, backup / "reference.wav")
        if self.consent_path.is_file():
            shutil.copy2(self.consent_path, backup / "consent.json")
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reason": "voice_reference_replaced_from_trusted_local_ui",
        }
        (backup / "backup.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return backup

    def _restore_backup(self, backup: Path | None, had_reference: bool, had_consent: bool) -> None:
        if had_reference and backup and (backup / "reference.wav").is_file():
            shutil.copy2(backup / "reference.wav", self.reference_path)
        elif not had_reference:
            self.reference_path.unlink(missing_ok=True)
        if had_consent and backup and (backup / "consent.json").is_file():
            shutil.copy2(backup / "consent.json", self.consent_path)
        elif not had_consent:
            self.consent_path.unlink(missing_ok=True)
