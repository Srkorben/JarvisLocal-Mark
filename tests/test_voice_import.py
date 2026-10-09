from __future__ import annotations

import base64
import json
import shutil
import subprocess
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import numpy as np

from jarvis_local.audio.enrollment import validate_own_voice_consent
from jarvis_local.control_center.voice_import import VoiceImportError, VoiceReferenceImporter
from jarvis_local.database import Database


def pcm_wave_bytes(path: Path, *, seconds: float, frequency: float = 220.0) -> bytes:
    sample_rate = 16_000
    timeline = np.arange(round(sample_rate * seconds), dtype=np.float64) / sample_rate
    samples = (np.sin(2 * np.pi * frequency * timeline) * 8_000).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())
    return path.read_bytes()


class VoiceReferenceImporterTests(TestCase):
    def make_importer(self, root: Path) -> tuple[VoiceReferenceImporter, Database]:
        data = root / "data"
        database = Database(data / "test.db")
        project = database.create_project("Mark", root, make_active=True)
        importer = VoiceReferenceImporter(
            data_dir=data,
            reference_path=data / "voices" / "user" / "reference.wav",
            consent_path=data / "voices" / "user" / "consent.json",
            database=database,
            project_id=project.id,
        )
        return importer, database

    def test_imports_normalizes_audits_and_binds_authorized_reference(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            importer, database = self.make_importer(root)
            raw = pcm_wave_bytes(root / "source.wav", seconds=20.0)
            result = importer.import_base64(
                filename="voz autorizada.wav",
                audio_base64=base64.b64encode(raw).decode("ascii"),
                authorization_confirmed=True,
                replace_existing=False,
            )
            self.assertEqual(result["outcome"], "imported")
            self.assertAlmostEqual(result["duration_seconds"], 20.0, places=2)
            reference = root / "data" / "voices" / "user" / "reference.wav"
            consent = root / "data" / "voices" / "user" / "consent.json"
            with wave.open(str(reference), "rb") as normalized:
                self.assertEqual(normalized.getnchannels(), 1)
                self.assertEqual(normalized.getsampwidth(), 2)
                self.assertEqual(normalized.getframerate(), 24_000)
            record = validate_own_voice_consent(reference, consent)
            self.assertEqual(record["source"], "trusted_local_ui_upload")
            self.assertTrue(database.verify_audit_chain()[0])
            with database.connection() as connection:
                detail = json.loads(
                    connection.execute(
                        "SELECT detail_json FROM audit_events ORDER BY id DESC LIMIT 1"
                    ).fetchone()[0]
                )
            self.assertFalse(detail["audio_content_stored_in_audit"])
            self.assertFalse(detail["original_filename_stored_in_audit"])

    def test_replacement_keeps_recoverable_backup(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            importer, _ = self.make_importer(root)
            first = pcm_wave_bytes(root / "first.wav", seconds=20.0, frequency=220.0)
            second = pcm_wave_bytes(root / "second.wav", seconds=20.0, frequency=330.0)
            importer.import_base64(
                filename="first.wav",
                audio_base64=base64.b64encode(first).decode("ascii"),
                authorization_confirmed=True,
                replace_existing=False,
            )
            result = importer.import_base64(
                filename="second.wav",
                audio_base64=base64.b64encode(second).decode("ascii"),
                authorization_confirmed=True,
                replace_existing=True,
            )
            self.assertTrue(result["replaced_existing"])
            self.assertTrue(result["backup_created"])
            backups = list((root / "data" / "voices" / "user" / "history").iterdir())
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / "reference.wav").is_file())
            self.assertTrue((backups[0] / "consent.json").is_file())

    def test_real_ffmpeg_mp3_path_when_available(self) -> None:
        ffmpeg = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
        if not ffmpeg:
            self.skipTest("FFmpeg no está instalado en esta máquina de pruebas.")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            importer, _ = self.make_importer(root)
            wav_path = root / "source.wav"
            pcm_wave_bytes(wav_path, seconds=20.0)
            mp3_path = root / "source.mp3"
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(wav_path),
                    "-y",
                    str(mp3_path),
                ],
                capture_output=True,
                check=False,
                timeout=30,
                shell=False,
            )
            self.assertEqual(completed.returncode, 0)
            result = importer.import_base64(
                filename="source.mp3",
                audio_base64=base64.b64encode(mp3_path.read_bytes()).decode("ascii"),
                authorization_confirmed=True,
                replace_existing=False,
            )
            self.assertEqual(result["source_extension"], ".mp3")
            self.assertAlmostEqual(result["duration_seconds"], 20.0, delta=0.1)

    def test_rejects_missing_authorization_short_audio_and_paths(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            importer, _ = self.make_importer(root)
            raw = pcm_wave_bytes(root / "short.wav", seconds=2.0)
            encoded = base64.b64encode(raw).decode("ascii")
            with self.assertRaises(VoiceImportError) as caught:
                importer.import_base64(
                    filename="short.wav",
                    audio_base64=encoded,
                    authorization_confirmed=False,
                    replace_existing=False,
                )
            self.assertEqual(caught.exception.code, "authorization_required")
            with self.assertRaises(VoiceImportError) as caught:
                importer.import_base64(
                    filename="short.wav",
                    audio_base64=encoded,
                    authorization_confirmed=True,
                    replace_existing=False,
                )
            self.assertEqual(caught.exception.code, "duration_invalid")
            with self.assertRaises(VoiceImportError) as caught:
                importer.import_base64(
                    filename="..\\short.wav",
                    audio_base64=encoded,
                    authorization_confirmed=True,
                    replace_existing=False,
                )
            self.assertEqual(caught.exception.code, "filename_invalid")
