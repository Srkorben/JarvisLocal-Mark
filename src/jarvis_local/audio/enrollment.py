from __future__ import annotations

import hashlib
import json
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .base import AudioError
from .models import AudioBuffer


CONSENT_VERSION = 1
AUTHORIZED_UPLOAD_CONSENT_VERSION = 2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_reference_wav(path: Path, audio: AudioBuffer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.asarray(audio.samples, dtype=np.int16)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(audio.sample_rate)
        output.writeframes(samples.astype("<i2", copy=False).tobytes())


def create_own_voice_consent(
    *, reference_path: Path, consent_path: Path, duration_seconds: float
) -> dict:
    if not reference_path.is_file():
        raise AudioError(
            "reference_missing",
            f"No existe la muestra de voz: {reference_path}",
            component="voice_clone",
        )
    record = {
        "version": CONSENT_VERSION,
        "confirmed_owner": True,
        "scope": "JarvisLocal local TTS only",
        "source": "trusted_local_cli",
        "reference_sha256": sha256_file(reference_path),
        "reference_filename": reference_path.name,
        "duration_seconds": round(duration_seconds, 3),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notice": (
            "El usuario confirmó que esta es su propia voz. La muestra no puede "
            "utilizarse para suplantar a terceros ni como confirmación de seguridad."
        ),
    }
    consent_path.parent.mkdir(parents=True, exist_ok=True)
    consent_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


def create_authorized_voice_consent(
    *,
    reference_path: Path,
    consent_path: Path,
    duration_seconds: float,
    source_extension: str,
) -> dict:
    """Liga una referencia importada a una autorización dada en la UI local.

    La confirmación afirma propiedad *o* permiso suficiente del titular. No se
    infiere identidad a partir del audio ni se conserva el nombre del archivo.
    """

    if not reference_path.is_file():
        raise AudioError(
            "reference_missing",
            f"No existe la muestra de voz: {reference_path}",
            component="voice_clone",
        )
    record = {
        "version": AUTHORIZED_UPLOAD_CONSENT_VERSION,
        "authorization_confirmed": True,
        "authorization_basis": "owner_or_permission_from_voice_owner",
        "scope": "JarvisLocal local TTS only",
        "source": "trusted_local_ui_upload",
        "source_extension": source_extension.casefold(),
        "reference_sha256": sha256_file(reference_path),
        "reference_filename": reference_path.name,
        "duration_seconds": round(duration_seconds, 3),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notice": (
            "El usuario confirmó en la interfaz local que es titular de la voz o "
            "que cuenta con autorización para usarla. La muestra no puede utilizarse "
            "como confirmación de seguridad ni acredita identidad."
        ),
    }
    consent_path.parent.mkdir(parents=True, exist_ok=True)
    consent_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


def validate_own_voice_consent(reference_path: Path, consent_path: Path) -> dict:
    if not reference_path.is_file():
        raise AudioError(
            "reference_missing",
            f"No existe la muestra de voz local: {reference_path}",
            component="voice_clone",
        )
    if not consent_path.is_file():
        raise AudioError(
            "consent_missing",
            "Falta el manifiesto local de consentimiento para clonación de voz.",
            component="voice_clone",
        )
    try:
        record = json.loads(consent_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AudioError(
            "consent_invalid",
            f"El manifiesto de voz no es válido: {exc}",
            component="voice_clone",
        ) from exc
    own_voice_consent = (
        isinstance(record, dict)
        and record.get("version") == CONSENT_VERSION
        and record.get("confirmed_owner") is True
        and record.get("source") == "trusted_local_cli"
    )
    authorized_upload_consent = (
        isinstance(record, dict)
        and record.get("version") == AUTHORIZED_UPLOAD_CONSENT_VERSION
        and record.get("authorization_confirmed") is True
        and record.get("authorization_basis") == "owner_or_permission_from_voice_owner"
        and record.get("source") == "trusted_local_ui_upload"
    )
    if not (own_voice_consent or authorized_upload_consent):
        raise AudioError(
            "consent_invalid",
            "El manifiesto no contiene una autorización válida desde una interfaz local confiable.",
            component="voice_clone",
        )
    actual_hash = sha256_file(reference_path)
    if record.get("reference_sha256") != actual_hash:
        raise AudioError(
            "reference_changed",
            "La muestra de voz cambió después del consentimiento; vuelve a enrolarla.",
            component="voice_clone",
        )
    return record
