from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass

from .base import AudioError


_NAMED_KEYS = {
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "shift": 0x10,
    "win": 0x5B,
    "space": 0x20,
    "pause": 0x13,
    "enter": 0x0D,
    "tab": 0x09,
}


@dataclass(frozen=True)
class WindowsKeyChord:
    expression: str
    virtual_keys: tuple[int, ...]

    @classmethod
    def parse(cls, expression: str) -> "WindowsKeyChord":
        parts = [item.strip().casefold() for item in expression.split("+") if item.strip()]
        if not parts:
            raise ValueError("La combinación de teclas no puede estar vacía.")
        keys: list[int] = []
        for part in parts:
            if part in _NAMED_KEYS:
                key = _NAMED_KEYS[part]
            elif len(part) == 1 and part.isalnum():
                key = ord(part.upper())
            elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
                key = 0x6F + int(part[1:])
            else:
                raise ValueError(f"Tecla global no soportada: {part}")
            if key not in keys:
                keys.append(key)
        return cls(expression=expression, virtual_keys=tuple(keys))

    def is_pressed(self) -> bool:
        if os.name != "nt":
            raise AudioError(
                "unsupported_platform",
                "La hotkey global de Fase 2 sólo está implementada para Windows.",
                component="hotkey",
            )
        user32 = ctypes.windll.user32
        return all(user32.GetAsyncKeyState(key) & 0x8000 for key in self.virtual_keys)
