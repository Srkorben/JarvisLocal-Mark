"""Consent manifest that binds Mark's voice reference to its owner.

Carried over from the original Mark (JarvisLocal) voice pipeline. The cloned
voice is only usable when a local manifest confirms that the reference sample
is the user's own voice (or used with the owner's permission) *and* the
manifest's SHA-256 still matches the sample on disk.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

CONSENT_VERSION = 1
AUTHORIZED_UPLOAD_CONSENT_VERSION = 2


class VoiceConsentError(RuntimeError):
    """The voice reference is missing, changed or not authorized."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_own_voice_consent(*, reference_path: Path, consent_path: Path) -> dict:
    """Write a manifest confirming *reference_path* is the user's own voice."""
    if not reference_path.is_file():
        raise VoiceConsentError(
            "reference_missing", f"No existe la muestra de voz: {reference_path}"
        )
    record = {
        "version": CONSENT_VERSION,
        "confirmed_owner": True,
        "scope": "Mark local TTS only",
        "source": "trusted_local_cli",
        "reference_sha256": sha256_file(reference_path),
        "reference_filename": reference_path.name,
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


def validate_own_voice_consent(reference_path: Path, consent_path: Path) -> dict:
    """Return the manifest, or raise :class:`VoiceConsentError`."""
    if not reference_path.is_file():
        raise VoiceConsentError(
            "reference_missing", f"No existe la muestra de voz local: {reference_path}"
        )
    if not consent_path.is_file():
        raise VoiceConsentError(
            "consent_missing",
            "Falta el manifiesto local de consentimiento para clonación de voz.",
        )
    try:
        record = json.loads(consent_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VoiceConsentError(
            "consent_invalid", f"El manifiesto de voz no es válido: {exc}"
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
        raise VoiceConsentError(
            "consent_invalid",
            "El manifiesto no contiene una autorización válida desde una "
            "interfaz local confiable.",
        )
    if record.get("reference_sha256") != sha256_file(reference_path):
        raise VoiceConsentError(
            "reference_changed",
            "La muestra de voz cambió después del consentimiento; vuelve a enrolarla.",
        )
    return record


__all__ = [
    "AUTHORIZED_UPLOAD_CONSENT_VERSION",
    "CONSENT_VERSION",
    "VoiceConsentError",
    "create_own_voice_consent",
    "sha256_file",
    "validate_own_voice_consent",
]
