"""Clique de Executar e faixa de progresso na tela do aplicativo."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flet as ft

import config
from main import SuiteApp
from models import AppInfo, InstallStatus
from services.runner import RunError, RunningApp
from services.storage import Storage
from ui.app_detail_view import AppDetailView


def _walk(node):
    yield node
    for child in list(getattr(node, "controls", None) or []):
        yield from _walk(child)
    content = getattr(node, "content", None)
    if content is not None:
        yield from _walk(content)


def _scroll_columns(root) -> list:
    return [node for node in _walk(root) if getattr(node, "scroll", None) == ft.ScrollMode.AUTO]


class _Page:
    def __init__(self) -> None:
        self.threads: list = []
        self.updates = 0

    def run_thread(self, fn) -> None:
        self.threads.append(fn)

    def update(self) -> None:
        self.updates += 1


class AppDetailPresentationTests(unittest.TestCase):
    def _installed(self, root: Path, app_id: str = "app", versao: str = "1.0.0") -> Storage:
        storage = Storage(root / "apps", root / "installed.json")
        local = root / f"{app_id}.exe"
        local.write_bytes(b"MZ")
        storage.set_installed(app_id, local, versao)
        return storage

    def test_execute_click_paints_opening_on_the_button_before_run(self) -> None:
        page = _Page()
        app = AppInfo(id="app", nome="Relatorio", versao="1.0.0")
        seen: dict = {}

        def on_run(_app) -> None:
            seen["content"] = view.action_button.content
            seen["bgcolor"] = view.action_button.style.bgcolor
            seen["color"] = view.action_button.style.color
            seen["disabled"] = view.action_button.disabled
            seen["updates"] = page.updates
            seen["status"] = view.status_text.value
            seen["strip"] = view.progress_strip.visible

        with tempfile.TemporaryDirectory() as tmp:
            storage = self._installed(Path(tmp))
            view = AppDetailView(page, app, storage, object(), on_run=on_run)
            view.action_button.on_click(None)

        self.assertEqual(seen["content"], "Abrindo...")
        self.assertEqual(seen["bgcolor"], config.COLOR_ACCENT)
        self.assertEqual(seen["color"], "#142018")
        self.assertFalse(seen["disabled"])
        self.assertGreaterEqual(seen["updates"], 1)
        self.assertEqual(seen["status"], "")
        self.assertFalse(seen["strip"])
        self.assertEqual(view.action_button.content, "Abrindo...")

        view.action_button.on_click(None)
        self.assertEqual(page.updates, seen["updates"])

    def test_opening_state_keeps_the_accent_button(self) -> None:
        page = _Page()
        app = AppInfo(id="app", nome="Relatorio", tutorial_markdown_url="https://x/t.md")
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._installed(Path(tmp))
            view = AppDetailView(
                page,
                app,
                storage,
                object(),
                opening=True,
                feedback_enabled=True,
                this_app_running=True,
                work_message="erro antigo",
            )
            built = view.build()
        self.assertEqual(view.action_button.content, "Abrindo...")
        self.assertEqual(view.action_button.style.bgcolor, config.COLOR_ACCENT)
        self.assertFalse(view.action_button.disabled)
        self.assertEqual(view.update_button.content, "Atualizar versao")
        self.assertEqual(view.update_button.style.bgcolor, config.COLOR_PRIMARY)
        self.assertEqual(view.update_button.style.color, "white")
        self.assertNotEqual(view.update_button.style.bgcolor, config.COLOR_ACCENT)
        self.assertFalse(view.update_button.disabled)
        self.assertTrue(view.uninstall_button.disabled)
        self.assertTrue(view.feedback_button.disabled)
        self.assertTrue(view.tutorial_button.disabled)
        self.assertFalse(view.progress_strip.visible)
        self.assertEqual(view.status_text.value, "")
        self.assertIsNone(getattr(built, "scroll", None))
        body = _scroll_columns(built)
        self.assertEqual(body, [built.controls[0]])
        self.assertIs(view.action_dock.controls[0], view.progress_strip)
        self.assertIs(view.action_dock.controls[1], view.actions)
        self.assertNotIn(view.progress, list(_walk(body[0])))
        self.assertNotIn(view.action_button, list(_walk(body[0])))

    def test_missing_run_restores_the_button_and_the_error(self) -> None:
        page = _Page()
        app = AppInfo(id="app", nome="Relatorio")
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._installed(Path(tmp))
            view = AppDetailView(page, app, storage, object())
            view.action_button.on_click(None)
        self.assertEqual(view.action_button.content, "Executar")
        self.assertEqual(view.action_button.style.bgcolor, config.COLOR_PRIMARY)
        self.assertEqual(view.status_text.value, "Nao foi possivel iniciar o aplicativo.")
        self.assertFalse(view.opening)

    def test_download_progress_stays_in_the_fixed_strip(self) -> None:
        page = _Page()
        app = AppInfo(id="app", nome="Relatorio", descricao="Texto longo")
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "apps", Path(tmp) / "installed.json")
            view = AppDetailView(page, app, storage, object(), feedback_enabled=True)
            built = view.build()
            view.action_button.on_click(None)
        self.assertEqual(len(page.threads), 1)
        self.assertTrue(view.progress_strip.visible)
        self.assertEqual(view.progress_caption.value, "Baixando. Pode aguardar.")
        self.assertIsNone(view.progress.value)
        self.assertEqual(view.status_text.value, "")
        self.assertTrue(view.action_button.disabled)
        self.assertTrue(view.feedback_button.disabled)
        self.assertIs(view.action_dock.controls[0], view.progress_strip)
        self.assertIs(view.action_dock.controls[1], view.actions)
        body = _scroll_columns(built)
        self.assertEqual(body, [built.controls[0]])
        self.assertNotIn(view.progress, list(_walk(body[0])))
        self.assertNotIn(view.progress_caption, list(_walk(body[0])))
        self.assertNotIn(view.action_button, list(_walk(body[0])))

        view._apply_progress(0.4, "Baixando lote (3 arquivo(s)) — login unico...")
        self.assertEqual(view.progress_caption.value, "Baixando. Pode aguardar.")
        self.assertEqual(view.progress.value, 0.4)
        self.assertEqual(view.status_text.value, "")
        self.assertNotIn("login", view.progress_caption.value)

    def test_update_and_uninstall_use_the_same_fixed_strip(self) -> None:
        page = _Page()
        app = AppInfo(
            id="app",
            nome="Relatorio",
            versao="2.0.0",
            tutorial_markdown_url="https://x/t.md",
        )
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._installed(Path(tmp), versao="1.0.0")
            updating = AppDetailView(
                page,
                app,
                storage,
                object(),
                feedback_enabled=True,
                work_busy=True,
                work_progress=0.2,
                work_message="Preparando atualizacao...",
            )
            built = updating.build()
            self.assertEqual(updating.progress_caption.value, "Atualizando. Pode aguardar.")
            self.assertEqual(updating.progress.value, 0.2)
            self.assertTrue(updating.progress_strip.visible)
            self.assertTrue(updating.action_button.disabled)
            self.assertTrue(updating.update_button.disabled)
            self.assertEqual(updating.update_button.content, "Atualizar versao")
            self.assertEqual(updating.update_button.style.bgcolor, config.COLOR_PRIMARY)
            self.assertEqual(updating.update_button.style.color, "white")
            self.assertIs(updating.actions.controls[0], updating.update_button)
            self.assertIs(updating.actions.controls[1], updating.action_button)
            self.assertTrue(updating.uninstall_button.disabled)
            self.assertTrue(updating.feedback_button.disabled)
            self.assertTrue(updating.tutorial_button.disabled)
            self.assertEqual(updating.status_text.value, "")
            self.assertIs(updating.action_dock.controls[0], updating.progress_strip)
            self.assertIs(updating.action_dock.controls[1], updating.actions)
            scroll = _scroll_columns(built)[0]
            self.assertNotIn(updating.progress, list(_walk(scroll)))
            self.assertNotIn(updating.action_button, list(_walk(scroll)))

            removing = AppDetailView(
                page,
                app,
                storage,
                object(),
                work_busy=True,
                work_progress=-1.0,
                work_message="Desinstalando...",
            )
            self.assertEqual(removing.progress_caption.value, "Desinstalando. Pode aguardar.")
            self.assertIsNone(removing.progress.value)
            self.assertTrue(removing.action_button.disabled)
            self.assertTrue(removing.uninstall_button.disabled)

            seen: dict = {}

            def uninstall(_app_id: str) -> None:
                seen["caption"] = local.progress_caption.value
                seen["visible"] = local.progress_strip.visible
                seen["disabled"] = (
                    local.action_button.disabled
                    and local.uninstall_button.disabled
                    and local.update_button.disabled
                )

            storage.uninstall = uninstall
            local = AppDetailView(page, app, storage, object())
            local.uninstall_button.on_click(None)
        self.assertEqual(seen["caption"], "Desinstalando. Pode aguardar.")
        self.assertTrue(seen["visible"])
        self.assertTrue(seen["disabled"])
        self.assertFalse(local.progress_strip.visible)
        self.assertIn("Desinstal", local.status_text.value)

    def test_idle_detail_keeps_the_result_text_without_a_strip(self) -> None:
        page = _Page()
        app = AppInfo(id="app", nome="Relatorio")
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._installed(Path(tmp))
            view = AppDetailView(
                page,
                app,
                storage,
                object(),
                work_message="O arquivo baixado nao e um executavel valido. Baixe de novo.",
            )
            built = view.build()
        self.assertFalse(view.progress_strip.visible)
        self.assertEqual(view.action_button.content, "Executar")
        self.assertEqual(view.action_button.style.bgcolor, config.COLOR_PRIMARY)
        self.assertEqual(
            view.status_text.value,
            "O arquivo baixado nao e um executavel valido. Baixe de novo.",
        )
        self.assertIs(view.action_dock.controls[0], view.progress_strip)
        self.assertIs(view.action_dock.controls[1], view.actions)
        self.assertEqual(getattr(built.controls[0], "scroll", None), ft.ScrollMode.AUTO)
        self.assertNotIn(view.action_button, list(_walk(built.controls[0])))

    def test_update_button_leads_with_the_run_style_only_when_needed(self) -> None:
        page = _Page()
        current = AppInfo(
            id="app",
            nome="Relatorio",
            versao="1.0.0",
            tutorial_markdown_url="https://x/t.md",
        )
        newer = AppInfo(
            id="app",
            nome="Relatorio",
            versao="2.0.0",
            tutorial_markdown_url="https://x/t.md",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = self._installed(root, versao="1.0.0")
            same = AppDetailView(page, current, storage, object(), feedback_enabled=True)
            same.build()
            self.assertFalse(same.update_button.visible)
            self.assertEqual(
                _visible_action_labels(same),
                ["Executar", "Feedback", "Tutorial", "Desinstalar"],
            )
            self.assertIs(same.actions.controls[0], same.update_button)
            self.assertIs(same.actions.controls[1], same.action_button)

            detail = AppDetailView(page, newer, storage, object(), feedback_enabled=True)
            detail.build()
            self.assertTrue(detail.update_button.visible)
            self.assertFalse(detail.update_button.disabled)
            self.assertEqual(detail.update_button.content, "Atualizar versao")
            self.assertEqual(detail.update_button.icon, ft.Icons.SYSTEM_UPDATE)
            self.assertIsInstance(detail.update_button, ft.FilledButton)
            self.assertIs(type(detail.update_button), type(detail.action_button))
            self.assertEqual(detail.action_button.content, "Executar")
            self.assertEqual(detail.update_button.style.bgcolor, config.COLOR_PRIMARY)
            self.assertEqual(detail.update_button.style.color, "white")
            self.assertEqual(
                detail.update_button.style.bgcolor,
                detail.action_button.style.bgcolor,
            )
            self.assertEqual(detail.update_button.style.color, detail.action_button.style.color)
            self.assertEqual(
                detail.update_button.style.overlay_color,
                detail.action_button.style.overlay_color,
            )
            self.assertEqual(
                detail.update_button.style.elevation,
                detail.action_button.style.elevation,
            )
            self.assertEqual(detail.update_button.elevation, detail.action_button.elevation)
            self.assertEqual(
                _visible_action_labels(detail),
                ["Atualizar versao", "Executar", "Feedback", "Tutorial", "Desinstalar"],
            )
            self.assertIs(detail.action_dock.controls[0], detail.progress_strip)
            self.assertIs(detail.action_dock.controls[1], detail.actions)
            self.assertFalse(detail.progress_strip.visible)

            fresh = Storage(root / "other-apps", root / "other.json")
            download = AppDetailView(page, newer, fresh, object())
            download.build()
        self.assertFalse(download.update_button.visible)
        self.assertEqual(download.action_button.content, "Baixar / Instalar")
        self.assertEqual(download.update_button.style.bgcolor, config.COLOR_PRIMARY)
        self.assertEqual(download.update_button.style.color, "white")
        self.assertEqual(_visible_action_labels(download), ["Baixar / Instalar"])
        self.assertIs(download.actions.controls[0], download.update_button)
        self.assertIs(download.actions.controls[1], download.action_button)

    def test_opening_does_not_turn_the_update_button_into_abrindo(self) -> None:
        page = _Page()
        app = AppInfo(id="app", nome="Relatorio", versao="2.0.0")
        seen: dict = {}

        with tempfile.TemporaryDirectory() as tmp:
            storage = self._installed(Path(tmp), versao="1.0.0")
            view = AppDetailView(
                page,
                app,
                storage,
                object(),
                opening=True,
            )
            view.build()
            self.assertTrue(view.update_button.visible)
            self.assertEqual(view.action_button.content, "Abrindo...")
            self.assertEqual(view.action_button.style.bgcolor, config.COLOR_ACCENT)
            self.assertEqual(view.update_button.content, "Atualizar versao")
            self.assertEqual(view.update_button.style.bgcolor, config.COLOR_PRIMARY)
            self.assertEqual(view.update_button.style.color, "white")
            self.assertFalse(view.update_button.disabled)
            self.assertFalse(view.progress_strip.visible)
            self.assertIs(view.action_dock.controls[0], view.progress_strip)
            self.assertIs(view.actions.controls[0], view.update_button)

            def on_run(_app) -> None:
                seen["action"] = idle.action_button.content
                seen["action_bg"] = idle.action_button.style.bgcolor
                seen["update"] = idle.update_button.content
                seen["update_bg"] = idle.update_button.style.bgcolor
                seen["update_color"] = idle.update_button.style.color
                seen["update_disabled"] = idle.update_button.disabled

            idle = AppDetailView(page, app, storage, object(), on_run=on_run)
            idle.build()
            self.assertFalse(idle.update_button.disabled)
            self.assertEqual(idle.action_button.style.bgcolor, config.COLOR_PRIMARY)
            idle.action_button.on_click(None)

            started: list[str] = []
            view.on_update_app = lambda item: started.append(item.id)
            view.update_button.on_click(None)
            self.assertEqual(started, [app.id])

            busy = AppDetailView(
                page,
                app,
                storage,
                object(),
                on_update_app=lambda item: started.append("busy"),
                opening=True,
                work_busy=True,
                work_message="Preparando atualizacao...",
            )
            busy.update_button.on_click(None)

        self.assertEqual(seen["action"], "Abrindo...")
        self.assertEqual(seen["action_bg"], config.COLOR_ACCENT)
        self.assertEqual(seen["update"], "Atualizar versao")
        self.assertEqual(seen["update_bg"], config.COLOR_PRIMARY)
        self.assertEqual(seen["update_color"], "white")
        self.assertFalse(seen["update_disabled"])
        self.assertEqual(idle.update_button.content, "Atualizar versao")
        self.assertEqual(idle.update_button.style.bgcolor, config.COLOR_PRIMARY)
        self.assertEqual(started, [app.id])
        self.assertTrue(busy.update_button.disabled)
        self.assertEqual(busy.update_button.style.bgcolor, config.COLOR_PRIMARY)
        self.assertEqual(busy.update_button.content, "Atualizar versao")
        self.assertEqual(busy.action_button.content, "Executar")

    def test_running_lock_clears_text_and_unlocks_without_moving_update(self) -> None:
        page = _Page()
        same = AppInfo(
            id="app",
            nome="Relatorio",
            versao="1.0.0",
            tutorial_markdown_url="https://x/t.md",
        )
        newer = AppInfo(id="app", nome="Relatorio", versao="2.0.0")
        with tempfile.TemporaryDirectory() as tmp:
            storage = self._installed(Path(tmp), versao="1.0.0")
            running = AppDetailView(
                page,
                same,
                storage,
                object(),
                this_app_running=True,
                feedback_enabled=True,
            )
            running.build()
            self.assertEqual(running.action_button.content, "Executar")
            self.assertTrue(running.action_button.disabled)
            self.assertTrue(running.uninstall_button.disabled)
            self.assertEqual(running.status_text.value, "Relatorio ja esta em execucao.")
            self.assertFalse(running.progress_strip.visible)
            self.assertEqual(
                _visible_action_labels(running),
                ["Executar", "Feedback", "Tutorial", "Desinstalar"],
            )

            updating = AppDetailView(page, newer, storage, object(), this_app_running=True)
            updating.build()
            self.assertTrue(updating.action_button.disabled)
            self.assertTrue(updating.uninstall_button.disabled)
            self.assertFalse(updating.update_button.disabled)
            self.assertEqual(updating.update_button.content, "Atualizar versao")
            self.assertEqual(updating.update_button.style.bgcolor, config.COLOR_PRIMARY)
            self.assertEqual(updating.update_button.style.color, "white")
            self.assertEqual(
                updating.status_text.value,
                "Em execucao. Atualizar versao encerra o processo, instala e reabre.",
            )
            self.assertFalse(updating.progress_strip.visible)
            self.assertEqual(
                _visible_action_labels(updating),
                ["Atualizar versao", "Executar", "Desinstalar"],
            )
            self.assertIs(updating.action_dock.controls[0], updating.progress_strip)

            idle = AppDetailView(page, newer, storage, object(), this_app_running=False)
            idle.build()
        self.assertEqual(idle.action_button.content, "Executar")
        self.assertFalse(idle.action_button.disabled)
        self.assertFalse(idle.uninstall_button.disabled)
        self.assertFalse(idle.update_button.disabled)
        self.assertEqual(idle.update_button.content, "Atualizar versao")
        self.assertEqual(idle.update_button.style.bgcolor, config.COLOR_PRIMARY)
        self.assertEqual(idle.status_text.value, "")
        self.assertFalse(idle.progress_strip.visible)
        self.assertEqual(
            _visible_action_labels(idle),
            ["Atualizar versao", "Executar", "Desinstalar"],
        )
        self.assertIs(idle.actions.controls[0], idle.update_button)
        self.assertIs(idle.actions.controls[1], idle.action_button)


def _visible_action_labels(view) -> list[str]:
    labels = []
    for child in view.actions.controls:
        if getattr(child, "visible", True) is False:
            continue
        content = getattr(child, "content", None)
        if isinstance(content, str):
            labels.append(content)
    return labels


class OpenCatalogAppTests(unittest.TestCase):
    def _app(self) -> tuple[SuiteApp, _Page, list]:
        page = _Page()
        app = SuiteApp.__new__(SuiteApp)
        app.page = page
        app.opening_app_id = None
        app.run_error = "antigo"
        app.app_job_busy = False
        app.app_job_app_id = None
        app.detail_notice = "aviso"
        app.detail_notice_app_id = "a"
        log: list = []

        def _render() -> None:
            log.append(("render", app.opening_app_id, app.run_error))

        app._render = _render
        app._refresh_running = lambda force=False: None
        app._this_app_running = lambda app_id: False
        app.storage = SimpleNamespace(
            get_state=lambda app_id: SimpleNamespace(local_path="C:/app.exe")
        )
        return app, page, log

    def test_button_state_is_painted_before_launch_and_cleared_after(self) -> None:
        app, page, log = self._app()
        info = AppInfo(id="a", nome="Relatorio")

        def launch(*_args, **_kwargs):
            log.append(("launch", app.opening_app_id))
            return object()

        with patch("main.launch_file", launch):
            SuiteApp._run_catalog_app(app, info)
            self.assertEqual(log, [("render", "a", "")])
            self.assertEqual(app.detail_notice, "")
            self.assertEqual(len(page.threads), 1)
            page.threads[0]()

        self.assertEqual(
            log,
            [
                ("render", "a", ""),
                ("launch", "a"),
                ("render", None, ""),
            ],
        )
        self.assertIsNone(app.opening_app_id)
        self.assertEqual(len(page.threads), 2)

    def test_invalid_exe_error_returns_and_clears_the_button(self) -> None:
        app, page, log = self._app()
        info = AppInfo(id="a", nome="Relatorio")
        message = "O arquivo baixado nao e um executavel valido. Baixe de novo."

        def launch(*_args, **_kwargs):
            log.append("launch")
            raise RunError(message)

        with patch("main.launch_file", launch):
            SuiteApp._run_catalog_app(app, info)
            page.threads[0]()

        self.assertEqual(log[0], ("render", "a", ""))
        self.assertEqual(log[1], "launch")
        self.assertEqual(log[2], ("render", None, message))
        self.assertEqual(app.run_error, message)
        self.assertIsNone(app.opening_app_id)
        self.assertEqual(len(page.threads), 1)

    def test_second_click_does_not_launch_again(self) -> None:
        app, page, log = self._app()
        info = AppInfo(id="a", nome="Relatorio")
        with patch("main.launch_file", lambda *_a, **_k: log.append("launch")):
            SuiteApp._run_catalog_app(app, info)
            SuiteApp._run_catalog_app(app, info)
        self.assertEqual(len(page.threads), 1)
        self.assertNotIn("launch", log)

    def test_update_during_opening_cancels_the_launch(self) -> None:
        app, page, log = self._app()
        app.update_busy = False
        info = AppInfo(id="a", nome="Relatorio")

        def launch(*_args, **_kwargs):
            log.append("launch")
            return object()

        with patch("main.launch_file", launch):
            SuiteApp._run_catalog_app(app, info)
            SuiteApp._request_app_update(app, info)
            page.threads[0]()

        self.assertNotIn("launch", log)
        self.assertIsNone(app.opening_app_id)
        self.assertTrue(app.app_job_busy)
        self.assertEqual(app.app_job_app_id, "a")
        self.assertEqual(app.app_job_message, "Preparando atualizacao...")
        self.assertEqual(len(page.threads), 2)

    def test_execute_keeps_the_launched_process_handle(self) -> None:
        app, page, log = self._app()
        info = AppInfo(id="a", nome="Relatorio")
        running = RunningApp(
            app_id="a",
            app_name="Relatorio",
            popen=SimpleNamespace(wait=lambda: 0, poll=lambda: None),
        )

        with patch("main.launch_file", return_value=running):
            SuiteApp._run_catalog_app(app, info)
            page.threads[0]()

        self.assertEqual(log[-1], ("render", None, ""))
        self.assertIs(app._launched_handles["a"], running)
        self.assertEqual(len(page.threads), 3)
        self.assertEqual(app.run_error, "")

    def test_update_waits_while_another_app_is_opening(self) -> None:
        app, page, _log = self._app()
        app.update_busy = False
        app.opening_app_id = "outro"
        SuiteApp._request_app_update(app, AppInfo(id="a", nome="Relatorio"))
        self.assertEqual(app.opening_app_id, "outro")
        self.assertFalse(app.app_job_busy)
        self.assertEqual(page.threads, [])


if __name__ == "__main__":
    unittest.main()
