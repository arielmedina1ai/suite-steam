"""Uma instancia do hub (nao dos apps do catalogo). Mutex nomeado no Windows."""
from __future__ import annotations

import hashlib
import sys
import threading
from collections.abc import Callable

import config

_ERROR_ALREADY_EXISTS = 183
_WAIT_OBJECT_0 = 0
_INFINITE = 0xFFFFFFFF


def _object_names() -> tuple[str, str]:
    raw = f"{config.EXE_NAME}|{config.USER_DATA_DIR}".encode("utf-8", "replace")
    digest = hashlib.sha1(raw).hexdigest()[:16]
    base = f"Local\\SuiteHub-{config.EXE_NAME}-{digest}"
    return base, f"{base}-show"


class HubInstance:
    """Primeira instancia fica com o mutex; a segunda so pede para reabrir a janela."""

    def __init__(self) -> None:
        self._mutex = None
        self._event = None
        self._owned = False
        self._watch_started = False

    def acquire(self) -> bool:
        if not sys.platform.startswith("win"):
            self._owned = True
            return True
        import ctypes
        from ctypes import wintypes

        mutex_name, event_name = _object_names()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        ctypes.set_last_error(0)
        mutex = kernel32.CreateMutexW(None, False, mutex_name)
        already = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
        event = kernel32.CreateEventW(None, True, False, event_name)
        if already or not mutex:
            if mutex:
                kernel32.CloseHandle(mutex)
            self._mutex = None
            self._event = event
            self._owned = False
            return False
        self._mutex = mutex
        self._event = event
        self._owned = True
        return True

    def notify_restore(self) -> None:
        if not sys.platform.startswith("win"):
            return
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        kernel32.SetEvent.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        if self._event:
            kernel32.SetEvent(self._event)
            kernel32.CloseHandle(self._event)
            self._event = None
            return
        _, event_name = _object_names()
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        handle = kernel32.CreateEventW(None, True, False, event_name)
        if handle:
            kernel32.SetEvent(handle)
            kernel32.CloseHandle(handle)

    def watch_restore(self, on_show: Callable[[], None]) -> None:
        if not self._owned or self._watch_started:
            return
        if not sys.platform.startswith("win") or not self._event:
            return
        self._watch_started = True
        event = self._event

        def _loop() -> None:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
            kernel32.ResetEvent.restype = wintypes.BOOL
            while True:
                rc = kernel32.WaitForSingleObject(event, _INFINITE)
                if rc != _WAIT_OBJECT_0:
                    return
                kernel32.ResetEvent(event)
                try:
                    on_show()
                except Exception:
                    pass

        threading.Thread(target=_loop, name="suite-hub-activate", daemon=True).start()

    def release(self) -> None:
        if not sys.platform.startswith("win"):
            self._owned = False
            return
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        for handle in (self._event, self._mutex):
            if handle:
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    pass
        self._event = None
        self._mutex = None
        self._owned = False
