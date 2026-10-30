from types import SimpleNamespace
from unittest import TestCase

import numpy as np

from jarvis_local.xtts_worker import _coqui_pcm16, _official_inference_settings


class XTTSWorkerTests(TestCase):
    def test_pcm_conversion_matches_coqui_peak_normalization(self) -> None:
        converted = _coqui_pcm16(np.array([-0.25, 0.0, 0.5], dtype=np.float32))

        self.assertEqual(converted.dtype, np.dtype("<i2"))
        np.testing.assert_array_equal(converted, [-16383, 0, 32767])

    def test_empty_waveform_is_valid_pcm(self) -> None:
        converted = _coqui_pcm16(np.array([], dtype=np.float32))

        self.assertEqual(converted.dtype, np.dtype("<i2"))
        self.assertEqual(converted.size, 0)

    def test_inference_settings_follow_model_configuration(self) -> None:
        model = SimpleNamespace(
            config=SimpleNamespace(
                length_penalty=1.0,
                repetition_penalty=5.0,
                top_k=50,
                top_p=0.85,
            )
        )

        settings = _official_inference_settings(
            model, temperature=0.75, speed=1.0
        )

        self.assertEqual(settings["temperature"], 0.75)
        self.assertEqual(settings["repetition_penalty"], 5.0)
        self.assertEqual(settings["top_k"], 50)
        self.assertEqual(settings["top_p"], 0.85)
        self.assertTrue(settings["enable_text_splitting"])

