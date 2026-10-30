from __future__ import annotations

import contextlib
import ctypes
import os
from collections.abc import Iterator


ERROR_ALREADY_EXISTS = 183


@contextlib.contextmanager
def windows_singleton(name: str) -> Iterator[bool]:
    """Adquiere un mutex nominal de Windows durante toda la vida del proceso.

    Los bloqueos de archivo de ``msvcrt`` demostraron no ser suficientes para
    evitar que dos lanzadores distintos mantuvieran runtimes de Mark activos a
    la vez. Un mutex del kernel cubre procesos iniciados por Python global, el
    entorno virtual y la aplicación WPF dentro de la misma sesión de usuario.
    """

    if os.name != "nt":
        yield True
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    create_mutex.restype = ctypes.c_void_p
    release_mutex = kernel32.ReleaseMutex
    release_mutex.argtypes = (ctypes.c_void_p,)
    release_mutex.restype = ctypes.c_bool
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_bool

    ctypes.set_last_error(0)
    handle = create_mutex(None, True, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
    try:
        yield acquired
    finally:
        if acquired:
            release_mutex(handle)
        close_handle(handle)
