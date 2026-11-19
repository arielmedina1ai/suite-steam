"""Minimizar fica na barra de tarefas. Fechar ainda vai para a bandeja.

Foco da janela e a saida do processo que o Executar abriu reconferem
o cadeado de "em execucao" sem varredura periodica.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flet as ft

from main import SuiteApp, _ALREADY_RUNNING_ERROR
from services.runner import RunningApp


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
        self.threads: list = []

    def update(self) -> None:
        self.updates += 1

    def run_thread(self, fn) -> None:
        self.threads.append(fn)


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


def _proc() -> SimpleNamespace:
    return SimpleNamespace(wait=lambda: 0, poll=lambda: None)


class RunningRefreshTests(unittest.TestCase):
    def _app(self) -> tuple[SuiteApp, _Page]:
        page = _Page()
        app = SuiteApp.__new__(SuiteApp)
        app.page = page
        app._exiting = False
        app._running_pids = {}
        app._running_cache_at = time.monotonic()
        app.selected_id = "a"
        app.run_error = ""
        app._launched_handles = {}
        app._launched_lock = threading.Lock()
        app._renders: list[set[str]] = []
        app._render = lambda: app._renders.append(set(app._running_app_ids()))
        app._installed_paths = lambda: {"a": r"C:\Apps\a.exe"}
        return app, page

    def _focus(self, app: SuiteApp, found: dict[str, list[int]]) -> None:
        with (
            patch("main.snapshot_processes", return_value=[]) as snap,
            patch("main.running_catalog_map", return_value=found) as mapped,
        ):
            SuiteApp._on_window_event(app, SimpleNamespace(type=ft.WindowEventType.FOCUS))
        self.snap = snap
        self.mapped = mapped

    def test_focus_clears_a_running_lock_the_screen_still_shows(self) -> None:
        app, page = self._app()
        app._running_pids = {"a": [4], "b": [9]}
        app.run_error = _ALREADY_RUNNING_ERROR
        self._focus(app, {})
        self.snap.assert_called_once()
        self.mapped.assert_called_once()
        self.assertEqual(app._running_pids, {})
        self.assertEqual(app.run_error, "")
        self.assertEqual(app._renders, [set()])
        self.assertTrue(page.window.visible)
        self.assertFalse(page.window.minimized)

    def test_focus_keeps_the_lock_when_the_process_is_still_there(self) -> None:
        app, _page = self._app()
        app._running_pids = {"a": [4]}
        app.run_error = _ALREADY_RUNNING_ERROR
        self._focus(app, {"a": [8]})
        self.assertEqual(app._running_pids, {"a": [8]})
        self.assertEqual(app.run_error, _ALREADY_RUNNING_ERROR)
        self.assertEqual(app._renders, [])

    def test_focus_does_not_scan_when_nothing_is_shown_as_running(self) -> None:
        app, _page = self._app()
        app.run_error = "Arquivo nao encontrado. Use Baixar / Instalar."
        with patch("main.snapshot_processes") as snap:
            SuiteApp._on_window_event(app, _Event("FOCUS"))
        snap.assert_not_called()
        self.assertEqual(app.run_error, "Arquivo nao encontrado. Use Baixar / Instalar.")
        self.assertEqual(app._renders, [])

    def test_focus_clears_a_stale_running_message_without_a_cached_pid(self) -> None:
        app, _page = self._app()
        app.run_error = _ALREADY_RUNNING_ERROR
        self._focus(app, {})
        self.assertEqual(app.run_error, "")
        self.assertEqual(app._renders, [set()])

    def test_minimize_does_not_rescan_running_apps(self) -> None:
        app, page = self._app()
        app._running_pids = {"a": [4]}
        with patch("main.snapshot_processes") as snap:
            SuiteApp._on_window_event(app, _Event("MINIMIZE"))
        snap.assert_not_called()
        self.assertEqual(app._running_pids, {"a": [4]})
        self.assertTrue(page.window.minimized)
        self.assertTrue(page.window.visible)

    def test_cache_does_not_skip_the_focus_recheck(self) -> None:
        app, _page = self._app()
        app._running_pids = {"a": [4]}
        app._running_cache_at = time.monotonic()
        SuiteApp._refresh_running(app)
        self.assertEqual(app._running_pids, {"a": [4]})
        self._focus(app, {})
        self.assertEqual(app._running_pids, {})
        self.assertEqual(app._renders, [set()])

    def test_launched_exit_unlocks_when_the_scan_no_longer_sees_the_app(self) -> None:
        app, page = self._app()
        app._running_pids = {"a": [4]}
        app.run_error = _ALREADY_RUNNING_ERROR
        running = RunningApp(app_id="a", app_name="Relatorio", popen=_proc())
        SuiteApp._remember_launched(app, running)
        self.assertIs(app._launched_handles["a"], running)
        with (
            patch("main.snapshot_processes", return_value=[]),
            patch("main.running_catalog_map", return_value={}),
        ):
            page.threads[-1]()
        self.assertNotIn("a", app._launched_handles)
        self.assertEqual(app._running_pids, {})
        self.assertEqual(app.run_error, "")
        self.assertEqual(app._renders, [set()])

    def test_short_launcher_exit_keeps_the_lock_if_the_app_is_still_running(self) -> None:
        app, page = self._app()
        app._running_pids = {"a": [4]}
        app.run_error = _ALREADY_RUNNING_ERROR
        running = RunningApp(app_id="a", app_name="Relatorio", popen=_proc())
        SuiteApp._remember_launched(app, running)
        with (
            patch("main.snapshot_processes", return_value=[]),
            patch("main.running_catalog_map", return_value={"a": [8]}),
        ):
            page.threads[-1]()
        self.assertEqual(app._running_pids, {"a": [8]})
        self.assertEqual(app.run_error, _ALREADY_RUNNING_ERROR)
        self.assertEqual(app._renders, [])
        self.assertNotIn("a", app._launched_handles)

    def test_old_launcher_exit_does_not_drop_a_newer_handle(self) -> None:
        app, page = self._app()
        app._running_pids = {"a": [4]}
        first = RunningApp(app_id="a", app_name="Relatorio", popen=_proc())
        second = RunningApp(app_id="a", app_name="Relatorio", popen=_proc())
        SuiteApp._remember_launched(app, first)
        first_wait = page.threads[-1]
        SuiteApp._remember_launched(app, second)
        with patch("main.snapshot_processes") as snap:
            first_wait()
        snap.assert_not_called()
        self.assertIs(app._launched_handles["a"], second)
        self.assertEqual(app._running_pids, {"a": [4]})
        self.assertEqual(app._renders, [])

    def test_show_from_tray_rechecks_the_same_running_lock(self) -> None:
        app, page = self._app()
        seen: list[str] = []
        app._recheck_running_on_focus = lambda: seen.append("focus")

        async def _to_front() -> None:
            return None

        page.window.to_front = _to_front
        asyncio.run(SuiteApp._show_from_tray_async(app))
        self.assertEqual(seen, ["focus"])
        self.assertTrue(page.window.visible)

        seen.clear()

        def _no_task(_fn) -> None:
            raise RuntimeError("sem loop")

        page.run_task = _no_task
        SuiteApp._show_from_tray(app)
        self.assertEqual(seen, ["focus"])


if __name__ == "__main__":
    unittest.main()
