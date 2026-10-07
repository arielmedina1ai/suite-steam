"""Minimizar fica na barra de tarefas. Fechar ainda vai para a bandeja."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from main import SuiteApp


class _Type:
    def __init__(self, name: str) -> None:
        self.name = name


class _Event:
    def __init__(self, name: str) -> None:
        self.type = _Type(name)


class _Window:
    def __init__(self) -> None:
        self.visible = True
        self.skip_task_bar = False
        self.minimized = False
        self.prevent_close = True


class _Page:
    def __init__(self) -> None:
        self.window = _Window()
        self.updates = 0

    def update(self) -> None:
        self.updates += 1


class WindowEventTests(unittest.TestCase):
    def _app(self) -> tuple[object, _Page]:
        page = _Page()
        app = SuiteApp.__new__(SuiteApp)
        app.page = page
        app._exiting = False
        return app, page

    def test_minimize_stays_visible_on_the_taskbar(self) -> None:
        app, page = self._app()
        SuiteApp._on_window_event(app, _Event("MINIMIZE"))
        self.assertTrue(page.window.minimized)
        self.assertTrue(page.window.visible)
        self.assertFalse(page.window.skip_task_bar)
        self.assertEqual(page.updates, 1)

    def test_close_still_hides_to_the_tray(self) -> None:
        app, page = self._app()
        SuiteApp._on_window_event(app, _Event("CLOSE"))
        self.assertFalse(page.window.visible)
        self.assertTrue(page.window.skip_task_bar)
        self.assertTrue(page.window.minimized)
        self.assertTrue(page.window.prevent_close)


if __name__ == "__main__":
    unittest.main()
