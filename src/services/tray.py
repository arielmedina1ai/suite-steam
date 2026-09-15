"""Icone na area de notificacao (bandeja). Windows; no-op em outros SOs."""
from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from pathlib import Path

import config


class TrayController:
    """Menu: Abrir janela / Sair. Nao e processo de app do catalogo."""

    def __init__(
        self,
        *,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon = None
        self._lock = threading.Lock()
        self.started = False

    def supported(self) -> bool:
        return sys.platform.startswith("win")

    def start(self) -> None:
        if not self.supported():
            return
        try:
            import pystray
            from PIL import Image
        except Exception:
            return
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
        thread = threading.Thread(target=icon.run, name="suite-tray", daemon=True)
        thread.start()

    def stop(self) -> None:
        icon = self._icon
        self._icon = None
        if icon is None:
            return
        try:
            icon.stop()
        except Exception:
            pass

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


def _load_tray_image(Image):
    candidates: list[Path] = []
    ico = config.resolve_window_icon()
    if ico is not None:
        candidates.append(ico)
    if config.BRANDING_WINDOW_ICON_PNG.exists():
        candidates.append(config.BRANDING_WINDOW_ICON_PNG)
    example = config.BRANDING_DIR / "window_icon.example.png"
    if example.exists():
        candidates.append(example)
    if config.BRANDING_LOGO.exists():
        candidates.append(config.BRANDING_LOGO)
    for path in candidates:
        try:
            img = Image.open(path)
            return img.convert("RGBA")
        except Exception:
            continue
    return Image.new("RGBA", (32, 32), (0, 133, 66, 255))
