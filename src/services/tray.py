"""Bandeja Windows via Shell_NotifyIcon (user32/shell32).

Nao depende de pystray/Pillow no .exe onefile. pystray fica so como fallback.
"""
from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from pathlib import Path

import config

_ID_OPEN = 1001
_ID_QUIT = 1002
_WM_TRAY = 0x8000 + 21  # WM_APP + 21
_WM_COMMAND = 0x0111
_WM_DESTROY = 0x0002
_WM_LBUTTONUP = 0x0202
_WM_LBUTTONDBLCLK = 0x0203
_WM_RBUTTONUP = 0x0205
_WM_CONTEXTMENU = 0x007B
_NIM_ADD = 0
_NIM_DELETE = 2
_NIF_MESSAGE = 0x00000001
_NIF_ICON = 0x00000002
_NIF_TIP = 0x00000004
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010
_LR_DEFAULTSIZE = 0x0040
_IDI_APPLICATION = 32512
_WS_POPUP = 0x80000000
_WS_EX_TOOLWINDOW = 0x00000080
_TPM_RIGHTBUTTON = 0x0002
_TPM_BOTTOMALIGN = 0x0020
_MF_STRING = 0x00000000
_CS_HREDRAW = 0x0002
_CS_VREDRAW = 0x0001
_WM_NULL = 0x0000
_WM_QUIT = 0x0012


class TrayController:
    """Menu: Abrir / Sair. Nao e processo de app do catalogo."""

    def __init__(
        self,
        *,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon = None
        self.started = False
        self._hwnd = None
        self._hicon = None
        self._nid = None
        self._wndproc = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def supported(self) -> bool:
        return sys.platform.startswith("win")

    def start(self) -> None:
        if not self.supported() or self.started:
            return
        if self._start_win32():
            return
        self._start_pystray()

    def stop(self) -> None:
        hwnd = self._hwnd
        if hwnd:
            try:
                import ctypes
                from ctypes import wintypes

                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostMessageW.argtypes = [
                    wintypes.HWND,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM,
                ]
                user32.PostMessageW.restype = wintypes.BOOL
                user32.PostMessageW(hwnd, _WM_QUIT, 0, 0)
            except Exception:
                pass
        icon = self._icon
        self._icon = None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        self.started = False

    def _start_win32(self) -> bool:
        self._ready.clear()
        try:
            thread = threading.Thread(
                target=self._win32_message_loop,
                name="suite-tray",
                daemon=True,
            )
            thread.start()
            self._thread = thread
        except Exception:
            return False
        self._ready.wait(3.0)
        return bool(self.started and self._hwnd)

    def _win32_message_loop(self) -> None:
        try:
            self._win32_message_loop_inner()
        except Exception:
            self.started = False
            self._hwnd = None
            self._ready.set()

    def _win32_message_loop_inner(self) -> None:
        import ctypes
        from ctypes import wintypes

        LRESULT = ctypes.c_ssize_t
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)

        user32.DefWindowProcW.restype = LRESULT
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.GetMessageW.restype = ctypes.c_int
        user32.DispatchMessageW.restype = LRESULT
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadIconW.restype = wintypes.HICON
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.PostMessageW.restype = wintypes.BOOL
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_ubyte * 16),
                ("hBalloonIcon", wintypes.HICON),
            ]

        shell32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(NOTIFYICONDATAW),
        ]

        def _loword(value: int) -> int:
            return int(value) & 0xFFFF

        controller = self

        def _wndproc(hwnd, msg, wparam, lparam):
            if msg == _WM_TRAY:
                kind = int(lparam) & 0xFFFF
                if kind in (_WM_LBUTTONUP, _WM_LBUTTONDBLCLK):
                    controller._handle_show()
                    return 0
                if kind in (_WM_RBUTTONUP, _WM_CONTEXTMENU):
                    _popup_menu(hwnd)
                    return 0
            if msg == _WM_COMMAND:
                cmd = _loword(wparam)
                if cmd == _ID_OPEN:
                    controller._handle_show()
                    return 0
                if cmd == _ID_QUIT:
                    controller._handle_quit()
                    return 0
            if msg == _WM_DESTROY:
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        def _popup_menu(hwnd) -> None:
            menu = user32.CreatePopupMenu()
            if not menu:
                return
            user32.AppendMenuW(menu, _MF_STRING, _ID_OPEN, "Abrir")
            user32.AppendMenuW(menu, _MF_STRING, _ID_QUIT, "Sair")
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.SetForegroundWindow(hwnd)
            user32.TrackPopupMenu(
                menu,
                _TPM_RIGHTBUTTON | _TPM_BOTTOMALIGN,
                pt.x,
                pt.y,
                0,
                hwnd,
                None,
            )
            user32.PostMessageW(hwnd, _WM_NULL, 0, 0)
            user32.DestroyMenu(menu)

        self._wndproc = WNDPROC(_wndproc)
        class_name = f"SuiteAppsTray_{id(self)}"
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.style = _CS_HREDRAW | _CS_VREDRAW
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            err = ctypes.get_last_error()
            # 1410 = ERROR_CLASS_ALREADY_EXISTS
            if err != 1410:
                raise OSError(f"RegisterClassW falhou ({err})")

        hwnd = user32.CreateWindowExW(
            _WS_EX_TOOLWINDOW,
            class_name,
            "SuiteAppsTray",
            _WS_POPUP,
            0,
            0,
            0,
            0,
            None,
            None,
            hinst,
            None,
        )
        if not hwnd:
            raise OSError(f"CreateWindowExW falhou ({ctypes.get_last_error()})")
        self._hwnd = hwnd

        hicon = _load_win_icon(user32, shell32, hinst)
        self._hicon = hicon
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP
        nid.uCallbackMessage = _WM_TRAY
        nid.hIcon = hicon
        nid.szTip = (config.APP_NAME or "SuiteApps")[:127]
        if not shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid)):
            raise OSError(f"Shell_NotifyIcon ADD falhou ({ctypes.get_last_error()})")
        self._nid = nid
        self.started = True
        self._ready.set()

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", POINT),
            ]

        user32.GetMessageW.argtypes = [
            ctypes.POINTER(MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self._nid is not None:
            try:
                shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(self._nid))
            except Exception:
                pass
            self._nid = None
        if hwnd:
            user32.DestroyWindow(hwnd)
        self._hwnd = None

    def _start_pystray(self) -> None:
        try:
            import pystray
            from PIL import Image
        except Exception:
            return
        try:
            image = _load_tray_image(Image)
            menu = pystray.Menu(
                pystray.MenuItem("Abrir", self._handle_show, default=True),
                pystray.MenuItem("Sair", self._handle_quit),
            )
            icon = pystray.Icon(
                config.EXE_NAME or "SuiteApps",
                image,
                config.APP_NAME or "SuiteApps",
                menu,
            )
            self._icon = icon
            self.started = True
            threading.Thread(target=icon.run, name="suite-tray-pystray", daemon=True).start()
        except Exception:
            self.started = False

    def _handle_show(self, *_args) -> None:
        try:
            self._on_show()
        except Exception:
            pass

    def _handle_quit(self, *_args) -> None:
        try:
            self._on_quit()
        except Exception:
            pass


def _icon_candidates() -> list[Path]:
    paths: list[Path] = []
    ico = config.resolve_window_icon()
    if ico is not None:
        paths.append(ico)
    if config.BRANDING_WINDOW_ICON_ICO.exists():
        paths.append(config.BRANDING_WINDOW_ICON_ICO)
    if config.BRANDING_WINDOW_ICON_PNG.exists():
        paths.append(config.BRANDING_WINDOW_ICON_PNG)
    example = config.BRANDING_DIR / "window_icon.example.png"
    if example.exists():
        paths.append(example)
    if config.BRANDING_LOGO.exists():
        paths.append(config.BRANDING_LOGO)
    return paths


def _makeintresource(value: int):
    import ctypes

    return ctypes.cast(value, ctypes.c_wchar_p)


def _load_win_icon(user32, shell32, hinst):
    import ctypes
    from ctypes import wintypes

    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    for path in _icon_candidates():
        if path.suffix.lower() != ".ico":
            continue
        handle = user32.LoadImageW(
            None,
            str(path),
            _IMAGE_ICON,
            0,
            0,
            _LR_LOADFROMFILE | _LR_DEFAULTSIZE,
        )
        if handle:
            return handle

    exe = sys.executable if getattr(sys, "frozen", False) else None
    if exe:
        try:
            shell32.ExtractIconExW.restype = wintypes.UINT
            shell32.ExtractIconExW.argtypes = [
                wintypes.LPCWSTR,
                ctypes.c_int,
                ctypes.POINTER(wintypes.HICON),
                ctypes.POINTER(wintypes.HICON),
                wintypes.UINT,
            ]
            large = wintypes.HICON()
            small = wintypes.HICON()
            n = shell32.ExtractIconExW(exe, 0, ctypes.byref(large), ctypes.byref(small), 1)
            if n and small:
                return small
            if n and large:
                return large
        except Exception:
            pass
        handle = user32.LoadIconW(hinst, _makeintresource(1))
        if handle:
            return handle
    return user32.LoadIconW(None, _makeintresource(_IDI_APPLICATION))


def _load_tray_image(Image):
    for path in _icon_candidates():
        try:
            img = Image.open(path)
            return img.convert("RGBA")
        except Exception:
            continue
    return Image.new("RGBA", (32, 32), (0, 133, 66, 255))
