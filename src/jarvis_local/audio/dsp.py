from __future__ import annotations

import numpy as np


def mono_int16(samples: np.ndarray) -> np.ndarray:
    array = np.asarray(samples)
    if array.ndim == 2:
        array = array.astype(np.float32).mean(axis=1)
    if array.dtype != np.int16:
        if np.issubdtype(array.dtype, np.floating):
            array = np.clip(array, -1.0, 1.0) * 32767.0
        array = array.astype(np.int16)
    return np.ascontiguousarray(array.reshape(-1))


def resample_int16(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    mono = mono_int16(samples)
    if source_rate == target_rate or len(mono) == 0:
        return mono.copy()
    target_length = max(1, round(len(mono) * target_rate / source_rate))
    source_positions = np.linspace(0.0, 1.0, len(mono), endpoint=False)
    target_positions = np.linspace(0.0, 1.0, target_length, endpoint=False)
    values = np.interp(target_positions, source_positions, mono.astype(np.float32))
    return np.clip(values, -32768, 32767).astype(np.int16)


def normalized_rms(samples: np.ndarray) -> float:
    mono = mono_int16(samples)
    if len(mono) == 0:
        return 0.0
    values = mono.astype(np.float64) / 32768.0
    return float(np.sqrt(np.mean(values * values)))
