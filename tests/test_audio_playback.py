from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import numpy as np

from jarvis_local.audio.devices import SoundDevicePlayer
from jarvis_local.audio.models import AudioDeviceInfo, SynthesizedAudio
from jarvis_local.cancellation import CancellationController


class _FakeStream:
    def __init__(self, owner, **kwargs):
        self.owner = owner
        self.kwargs = kwargs
        self.written = None

    def start(self) -> None:
        self.owner.started = True

    def write(self, output) -> None:
        self.written = output.copy()
        self.owner.written = self.written

    def stop(self) -> None:
        self.owner.stopped = True

    def abort(self) -> None:
        self.owner.aborted = True

    def close(self) -> None:
        self.owner.closed = True


class _FakeSoundDevice:
    def __init__(self):
        self.stream_kwargs = None
        self.wasapi_kwargs = None
        self.started = False
        self.stopped = False
        self.aborted = False
        self.closed = False
        self.written = None

    def WasapiSettings(self, **kwargs):
        self.wasapi_kwargs = kwargs
        return kwargs

    def OutputStream(self, **kwargs):
        self.stream_kwargs = kwargs
        return _FakeStream(self, **kwargs)


class NativeWasapiPlaybackTests(IsolatedAsyncioTestCase):
    async def test_player_keeps_tts_rate_and_asks_windows_to_convert(self) -> None:
        fake_sd = _FakeSoundDevice()
        device = AudioDeviceInfo(
            index=17,
            name="Auriculares",
            host_api="Windows WASAPI",
            max_input_channels=0,
            max_output_channels=2,
            default_sample_rate=48000,
            is_default_input=False,
            is_default_output=True,
        )
        with (
            patch(
                "jarvis_local.audio.devices.SoundDeviceCatalog.resolve",
                return_value=device,
            ),
            patch("jarvis_local.audio.devices._sounddevice", return_value=fake_sd),
        ):
            player = SoundDevicePlayer(selector="wasapi_default")
            source = np.array([10, -20, 30, -40], dtype=np.int16)
            await player.play(
                SynthesizedAudio(
                    samples=source,
                    sample_rate=24000,
                    channels=1,
                    synthesis_seconds=0.01,
                ),
                CancellationController().begin_turn(),
            )

        self.assertEqual(fake_sd.stream_kwargs["samplerate"], 24000)
        self.assertEqual(fake_sd.wasapi_kwargs, {"exclusive": False, "auto_convert": True})
        np.testing.assert_array_equal(fake_sd.written.reshape(-1), source)
        self.assertTrue(fake_sd.started)
        self.assertTrue(fake_sd.stopped)
        self.assertTrue(fake_sd.closed)
