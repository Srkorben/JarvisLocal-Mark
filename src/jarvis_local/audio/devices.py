from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import numpy as np

from ..cancellation import CancellationToken, OperationCancelled
from .base import AudioError, AudioPlayer, AudioRecorder
from .dsp import normalized_rms, resample_int16
from .models import AudioBuffer, AudioDeviceInfo, SynthesizedAudio


def _sounddevice():
    try:
        import sounddevice as sd
    except ImportError as exc:  # pragma: no cover - depende del extra opcional
        raise AudioError(
            "dependency_missing",
            "Falta sounddevice; instala JarvisLocal con el extra 'audio'.",
            component="audio_device",
        ) from exc
    return sd


class SoundDeviceCatalog:
    @staticmethod
    def list_devices() -> list[AudioDeviceInfo]:
        sd = _sounddevice()
        host_apis = list(sd.query_hostapis())
        devices = list(sd.query_devices())
        result: list[AudioDeviceInfo] = []
        for index, device in enumerate(devices):
            host_index = int(device["hostapi"])
            host = host_apis[host_index]
            result.append(
                AudioDeviceInfo(
                    index=index,
                    name=str(device["name"]),
                    host_api=str(host["name"]),
                    max_input_channels=int(device["max_input_channels"]),
                    max_output_channels=int(device["max_output_channels"]),
                    default_sample_rate=round(float(device["default_samplerate"])),
                    is_default_input=index == int(host.get("default_input_device", -1)),
                    is_default_output=index == int(host.get("default_output_device", -1)),
                )
            )
        return result

    @staticmethod
    def resolve(selector: str, *, direction: str) -> AudioDeviceInfo:
        if direction not in {"input", "output"}:
            raise ValueError("direction debe ser input u output")
        devices = SoundDeviceCatalog.list_devices()
        capacity = (
            (lambda item: item.max_input_channels > 0)
            if direction == "input"
            else (lambda item: item.max_output_channels > 0)
        )
        normalized = selector.strip().casefold()
        candidates = [item for item in devices if capacity(item)]
        if normalized == "wasapi_default":
            defaults = [
                item
                for item in candidates
                if item.host_api.casefold() == "windows wasapi"
                and (
                    item.is_default_input
                    if direction == "input"
                    else item.is_default_output
                )
            ]
            if not defaults:
                raise AudioError(
                    "device_not_found",
                    f"Windows WASAPI no informa dispositivo {direction} predeterminado.",
                    component="audio_device",
                )
            return defaults[0]
        if normalized.isdecimal():
            index = int(normalized)
            match = next((item for item in candidates if item.index == index), None)
            if match is None:
                raise AudioError(
                    "device_not_found",
                    f"El dispositivo {direction} {index} no existe o no tiene canales.",
                    component="audio_device",
                )
            return match
        matches = [item for item in candidates if normalized in item.name.casefold()]
        if not matches:
            raise AudioError(
                "device_not_found",
                f"No se encontró dispositivo {direction} que contenga: {selector}",
                component="audio_device",
            )
        wasapi_matches = [
            item for item in matches if item.host_api.casefold() == "windows wasapi"
        ]
        matches = wasapi_matches or matches
        if len(matches) > 1:
            indexes = ", ".join(str(item.index) for item in matches)
            raise AudioError(
                "ambiguous_device",
                f"Selector ambiguo ({selector}); usa uno de estos índices: {indexes}.",
                component="audio_device",
            )
        return matches[0]


class SoundDeviceRecorder(AudioRecorder):
    def __init__(
        self,
        *,
        selector: str,
        target_sample_rate: int,
        max_seconds: float,
    ) -> None:
        self.device = SoundDeviceCatalog.resolve(selector, direction="input")
        self.target_sample_rate = target_sample_rate
        self.max_seconds = max_seconds
        self._stream: Any | None = None
        self._chunks: list[np.ndarray] = []
        self._captured_frames = 0
        self._lock = threading.Lock()
        self._started_at = 0.0
        self._overflowed = False
        self._status_messages: list[str] = []
        self._recent_rms = 0.0

    @property
    def elapsed_seconds(self) -> float:
        return 0.0 if not self._started_at else time.monotonic() - self._started_at

    @property
    def recent_rms(self) -> float:
        with self._lock:
            return self._recent_rms

    def retain_recent(self, seconds: float) -> None:
        keep_frames = max(0, round(self.device.default_sample_rate * seconds))
        with self._lock:
            if not self._chunks:
                return
            joined = np.concatenate(self._chunks)
            recent = joined[-keep_frames:].copy() if keep_frames else np.empty(0, dtype=np.int16)
            self._chunks = [recent] if len(recent) else []
            self._captured_frames = len(recent)

    def start(self) -> None:
        if self._stream is not None:
            raise AudioError(
                "already_recording", "El micrófono ya está grabando.", component="capture"
            )
        sd = _sounddevice()
        self._chunks = []
        self._captured_frames = 0
        self._overflowed = False
        self._status_messages = []
        self._recent_rms = 0.0
        native_rate = self.device.default_sample_rate
        max_frames = round(native_rate * self.max_seconds)

        def callback(indata, frames, _time_info, status) -> None:
            if status:
                with self._lock:
                    self._status_messages.append(str(status))
            chunk = np.asarray(indata[:, 0], dtype=np.int16).copy()
            with self._lock:
                self._recent_rms = normalized_rms(chunk)
                remaining = max_frames - self._captured_frames
                if remaining <= 0:
                    self._overflowed = True
                    return
                accepted = chunk[:remaining]
                self._chunks.append(accepted)
                self._captured_frames += len(accepted)
                if len(chunk) > remaining:
                    self._overflowed = True

        try:
            self._stream = sd.InputStream(
                device=self.device.index,
                samplerate=native_rate,
                channels=1,
                dtype="int16",
                callback=callback,
                blocksize=max(256, native_rate // 50),
                extra_settings=sd.WasapiSettings(exclusive=False),
            )
            self._stream.start()
            self._started_at = time.monotonic()
        except Exception as exc:
            self._stream = None
            raise AudioError(
                "input_unavailable",
                f"No se pudo abrir el micrófono {self.device.name}: {exc}",
                component="capture",
            ) from exc

    def stop(self) -> AudioBuffer:
        started = time.monotonic()
        stream = self._stream
        if stream is None:
            raise AudioError("not_recording", "El micrófono no está grabando.", component="capture")
        self._stream = None
        try:
            stream.stop()
            stream.close()
        except Exception as exc:
            raise AudioError(
                "input_disconnected",
                f"El micrófono dejó de estar disponible: {exc}",
                component="capture",
            ) from exc
        finally:
            self._started_at = 0.0
        with self._lock:
            chunks = list(self._chunks)
            overflowed = self._overflowed
            self._chunks.clear()
            self._captured_frames = 0
            self._recent_rms = 0.0
        native = (
            np.concatenate(chunks).astype(np.int16, copy=False)
            if chunks
            else np.empty(0, dtype=np.int16)
        )
        samples = resample_int16(
            native, self.device.default_sample_rate, self.target_sample_rate
        )
        return AudioBuffer(
            samples=samples,
            sample_rate=self.target_sample_rate,
            duration_seconds=len(samples) / self.target_sample_rate,
            rms=normalized_rms(samples),
            capture_close_seconds=time.monotonic() - started,
            overflowed=overflowed,
        )

    def abort(self) -> None:
        stream = self._stream
        self._stream = None
        self._started_at = 0.0
        with self._lock:
            self._chunks.clear()
            self._captured_frames = 0
            self._recent_rms = 0.0
        if stream is not None:
            try:
                stream.abort()
            finally:
                stream.close()


class SoundDevicePlayer(AudioPlayer):
    def __init__(self, *, selector: str) -> None:
        self.device = SoundDeviceCatalog.resolve(selector, direction="output")
        self._stream: Any | None = None
        self._lock = threading.Lock()

    async def play(
        self, audio: SynthesizedAudio, cancellation: CancellationToken
    ) -> float:
        cancellation.raise_if_cancelled()
        sd = _sounddevice()
        output = resample_int16(
            audio.samples, audio.sample_rate, self.device.default_sample_rate
        ).reshape(-1, 1)
        started = time.monotonic()
        try:
            stream = sd.OutputStream(
                device=self.device.index,
                samplerate=self.device.default_sample_rate,
                channels=1,
                dtype="int16",
                extra_settings=sd.WasapiSettings(exclusive=False),
            )
            with self._lock:
                self._stream = stream
            stream.start()
            write_task = asyncio.create_task(asyncio.to_thread(stream.write, output))
            cancel_task = asyncio.create_task(cancellation.wait())
            done, _ = await asyncio.wait(
                {write_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancel_task in done:
                self.stop()
                await asyncio.gather(write_task, return_exceptions=True)
                raise OperationCancelled(cancellation.reason or "Reproducción cancelada.")
            cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)
            await write_task
            # El aborto de PortAudio puede completar write() antes de que el
            # sondeo asíncrono despierte. El token sigue siendo la autoridad:
            # no informar reproducción exitosa si ya fue cancelada.
            cancellation.raise_if_cancelled()
            return time.monotonic() - started
        except OperationCancelled:
            raise
        except Exception as exc:
            raise AudioError(
                "output_unavailable",
                f"No se pudo reproducir por {self.device.name}: {exc}",
                component="playback",
            ) from exc
        finally:
            with self._lock:
                stream = self._stream
                self._stream = None
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    pass
                stream.close()

    def stop(self) -> None:
        with self._lock:
            stream = self._stream
        if stream is not None:
            try:
                stream.abort()
            except Exception:
                pass
