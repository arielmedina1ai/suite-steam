"""Login do Windows para a lista publish.users (sem e-mail / grupo SharePoint)."""
from __future__ import annotations

import os
import sys


def normalize_login(raw: str) -> str:
    return (raw or "").strip().replace("/", "\\").lower()


def _username_part(login: str) -> str:
    norm = normalize_login(login)
    if "\\" in norm:
        return norm.rsplit("\\", 1)[-1]
    return norm


def login_allowed(current: str, allowed: str) -> bool:
    """Compara DOMINIO\\usuario ou so usuario, sem diferenciar maiusculas."""
    cur = normalize_login(current)
    alw = normalize_login(allowed)
    if not cur or not alw:
        return False
    if "\\" in alw:
        return cur == alw
    return _username_part(cur) == alw


def user_can_publish(current: str, users: list[str]) -> bool:
    if not users:
        return False
    return any(login_allowed(current, item) for item in users)


def current_windows_login() -> str:
    """DOMINIO\\usuario quando der; senao so o usuario. Vazio se nao houver."""
    if sys.platform.startswith("win"):
        sam = _win_sam_compatible()
        if sam:
            return sam
        domain = (os.environ.get("USERDOMAIN") or "").strip()
        user = (os.environ.get("USERNAME") or "").strip()
        if domain and user:
            return f"{domain}\\{user}"
        return user
    return (os.environ.get("USERNAME") or os.environ.get("USER") or "").strip()


def _win_sam_compatible() -> str:
    try:
        import ctypes
        from ctypes import wintypes

        NameSamCompatible = 2
        secur32 = ctypes.WinDLL("secur32", use_last_error=True)
        size = wintypes.DWORD(256)
        buf = ctypes.create_unicode_buffer(256)
        secur32.GetUserNameExW.argtypes = [
            ctypes.c_int,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        secur32.GetUserNameExW.restype = wintypes.BOOL
        if secur32.GetUserNameExW(NameSamCompatible, buf, ctypes.byref(size)):
            return (buf.value or "").strip()
    except Exception:
        return ""
    return ""
