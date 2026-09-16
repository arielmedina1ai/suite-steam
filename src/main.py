"""SuiteApps - hub de aplicativos internos (frontend em Flet)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import flet as ft

import config
from catalog import SharePointCatalogProvider
from models import AppInfo, CatalogData, apps_do_setor, setores_visiveis
from services.download_manager import DownloadManager, DownloadOutcome
from services.favorites import FavoritesStore
from services.preferences import PreferencesStore
from services.process_guard import running_catalog_map, snapshot_processes, terminate_pids
from services.runner import RunError, launch_file
from services.self_update import (
    can_replace_running,
    saved_exe_filename,
    spawn_replace_and_relaunch,
    updates_dir,
)
from services.sharepoint_manager import baixar_do_sharepoint
from services.storage import Storage
from services.tray import TrayController
from services.windows_startup import set_start_with_windows, supported as startup_supported
from ui.app_detail_view import AppDetailView
from ui.components import build_sidebar
from ui.home_view import build_favoritos_view, build_home, build_setor_view
from ui.progress_util import bar_value, label as progress_label


class SuiteApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.storage = Storage()
        self.favorites = FavoritesStore()
        self.preferences = PreferencesStore()
        self.manager = DownloadManager(self.storage)
        self.catalog = CatalogData()
        self.view_catalog = CatalogData()
        self.apps: list[AppInfo] = []
        self.apps_by_id: dict[str, AppInfo] = {}
        self.selected_gerencia_id = self.preferences.get_gerencia_id()
        self.selected_id: str | None = None
        self.selected_setor: str | None = None
        self.show_favorites = False
        self.sync_message = ""
        self.sync_busy = True
        self.sync_progress: float | None = -1.0
        self.sync_status = "Sincronizando catalogo com SharePoint..."
        self.update_busy = False
        self.update_message = ""
        self.update_progress: float | None = None
        self.update_path: str | None = None
        self.update_failed = False
        self.update_done = False
        self._running_pids: dict[str, list[int]] = {}
        self._running_cache_at = 0.0
        self.app_job_busy = False
        self.app_job_app_id: str | None = None
        self.app_job_progress: float | None = None
        self.app_job_message = ""
        self._exiting = False
        self._tray: TrayController | None = None
        self.run_error = ""

        self.sidebar_holder = ft.Container()
        self.content_holder = ft.Container(expand=True, padding=28)
        self.root_row = ft.Row(
            expand=True,
            spacing=0,
            controls=[
                self.sidebar_holder,
                ft.Container(width=1, bgcolor="#22332B"),
                self.content_holder,
            ],
        )

        self._setup_page()
        self._apply_startup_preference()
        self._show_sync_screen()
        self.page.run_thread(lambda: self._sync_catalog_worker(True))

    # ------------------------------------------------------------------
    def _setup_page(self) -> None:
        self.page.title = config.APP_NAME
        self.page.window.width = 1180
        self.page.window.height = 760
        self.page.window.min_width = 900
        self.page.window.min_height = 600
        self.page.bgcolor = config.COLOR_BG
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.theme = ft.Theme(color_scheme_seed=config.COLOR_PRIMARY)
        self.page.padding = 0
        icon_path = config.resolve_window_icon()
        if icon_path is not None:
            self.page.window.icon = str(icon_path)
        if sys.platform.startswith("win"):
            self.page.window.prevent_close = True
            self.page.window.on_event = self._on_window_event
            self._tray = TrayController(on_show=self._show_from_tray, on_quit=self._quit_app)
            self._tray.start()
            if not self._tray.started:
                self.page.window.prevent_close = False
                self.page.window.on_event = None
        self.page.add(self.root_row)

    def _on_window_event(self, e) -> None:
        if self._exiting:
            return
        kind = _window_event_name(e)
        if kind in {"CLOSE", "MINIMIZE"}:
            self._hide_to_tray()

    def _hide_to_tray(self) -> None:
        try:
            self.page.window.minimized = True
            self.page.window.skip_task_bar = True
            self.page.window.visible = False
            self.page.update()
        except Exception:
            pass

    def _show_from_tray(self) -> None:
        def _apply() -> None:
            try:
                self.page.window.visible = True
                self.page.window.skip_task_bar = False
                self.page.window.minimized = False
                self.page.update()
                self.page.run_task(self.page.window.to_front)
            except Exception:
                pass

        try:
            self.page.run_thread(_apply)
        except Exception:
            _apply()

    def _quit_app(self) -> None:
        self._exiting = True
        if self._tray is not None:
            self._tray.stop()

        def _do() -> None:
            try:
                self.page.window.prevent_close = False
                self.page.update()
                self.page.run_task(self.page.window.destroy)
            except Exception:
                os._exit(0)

        try:
            self.page.run_thread(_do)
        except Exception:
            os._exit(0)

    def _apply_startup_preference(self) -> None:
        if startup_supported():
            set_start_with_windows(self.preferences.get_start_with_windows())

    def _toggle_startup(self, enabled: bool) -> None:
        self.preferences.set_start_with_windows(enabled)
        err = set_start_with_windows(enabled) if startup_supported() else ""
        if err:
            self.sync_message = err
        self._render()

    def _show_sync_screen(self) -> None:
        self.sidebar_holder.content = ft.Container(
            width=260,
            bgcolor=config.COLOR_SURFACE,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Text(config.APP_NAME, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                    ft.Text("Sincronizando...", size=12, color="#8AA797"),
                ]
            ),
        )
        self.content_holder.content = ft.Column(
            expand=True,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=16,
            controls=[
                ft.ProgressBar(
                    value=bar_value(self.sync_progress),
                    width=320,
                    color=config.COLOR_ACCENT,
                    bgcolor="#0A0F0C",
                ),
                ft.Text(
                    "Sincronizando catalogo com SharePoint...",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=config.COLOR_TEXT,
                ),
                ft.Text(
                    progress_label(self.sync_progress, self.sync_status)
                    or "Pode abrir uma janela de login (WebLogin).",
                    size=13,
                    color="#8AA797",
                ),
            ],
        )
        self.page.update()

    def _sync_catalog_worker(self, initial: bool = False) -> None:
        self.sync_busy = True
        provider = SharePointCatalogProvider()
        result = provider.sync(progress=self._on_sync_progress)
        if result.ok or initial or not self.catalog.apps:
            self.catalog = result.catalog
            self._apply_gerencia_filter()
        if result.ok:
            self.sync_message = ""
        else:
            self.sync_message = result.message or "Falha ao buscar atualizacoes."
        if initial:
            self.selected_id = None
            self.selected_setor = None
            self.show_favorites = False
        self.sync_busy = False
        self.sync_progress = 1.0 if result.ok else -1.0
        self._render()

    def _on_sync_progress(self, pct: float, msg: str) -> None:
        self.sync_progress = pct
        self.sync_status = msg
        try:
            content = self.content_holder.content
            if isinstance(content, ft.Column) and len(content.controls) >= 3:
                bar = content.controls[0]
                if isinstance(bar, ft.ProgressBar):
                    bar.value = bar_value(pct)
                content.controls[2] = ft.Text(
                    progress_label(pct, msg),
                    size=13,
                    color="#8AA797",
                )
                self.page.update()
        except Exception:
            pass

    def _check_updates(self) -> None:
        if self.sync_busy:
            return
        self.sync_busy = True
        self.sync_message = ""
        self._render()
        self.page.run_thread(lambda: self._sync_catalog_worker(False))

    # ------------------------------------------------------------------
    def _apply_gerencia_filter(self) -> None:
        gid = self.selected_gerencia_id
        if gid and self.catalog.gerencia_by_id(gid) is None:
            gid = ""
            self.selected_gerencia_id = ""
            self.preferences.set_gerencia_id("")
        self.view_catalog = self.catalog.filter_for_gerencia(gid)
        self.apps = self.view_catalog.apps
        self.apps_by_id = {app.id: app for app in self.apps}

    def _favorite_ids(self) -> set[str]:
        return set(self.favorites.list_ids())

    def _visible_favorite_apps(self) -> list[AppInfo]:
        favs = self._favorite_ids()
        return [a for a in self.apps if a.id in favs]

    def _has_visible_favorites(self) -> bool:
        return bool(self._visible_favorite_apps())

    def _gerencia_atual(self):
        if not self.selected_gerencia_id:
            return None
        return self.catalog.gerencia_by_id(self.selected_gerencia_id)

    def _update_available(self) -> bool:
        suite = self.catalog.suite
        if not suite.available:
            return False
        return suite.versao != config.APP_VERSION

    def _installed_paths(self) -> dict[str, str]:
        paths: dict[str, str] = {}
        for app in self.apps:
            state = self.storage.get_state(app.id)
            if state.local_path:
                paths[app.id] = state.local_path
        return paths

    def _refresh_running(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._running_cache_at) < 2.5:
            return
        paths = self._installed_paths()
        if not paths:
            self._running_pids = {}
            self._running_cache_at = now
            return
        snapshot = snapshot_processes()
        self._running_pids = running_catalog_map(paths, snapshot)
        self._running_cache_at = now

    def _this_app_running(self, app_id: str) -> bool:
        self._refresh_running()
        return bool(self._running_pids.get(app_id))

    def _other_app_running(self, app_id: str) -> bool:
        self._refresh_running()
        return any(aid != app_id and pids for aid, pids in self._running_pids.items())

    def _running_app_name(self) -> str:
        self._refresh_running()
        for app_id, pids in self._running_pids.items():
            if not pids:
                continue
            app = self.apps_by_id.get(app_id)
            return app.nome if app is not None else app_id
        return ""

    def _catalog_locked(self) -> bool:
        self._refresh_running()
        return any(bool(pids) for pids in self._running_pids.values())

    # ------------------------------------------------------------------
    def _go_home(self) -> None:
        self.selected_id = None
        self.selected_setor = None
        self.show_favorites = False
        self._render()

    def _go_favorites(self) -> None:
        self.selected_id = None
        self.selected_setor = None
        self.show_favorites = True
        self._render()

    def _select_setor(self, setor_id: str) -> None:
        self.selected_setor = setor_id
        self.selected_id = None
        self.show_favorites = False
        self._render()

    def _select_app(self, app_id: str) -> None:
        self.selected_id = app_id
        app = self.apps_by_id.get(app_id)
        if app is not None and app.setor:
            self.selected_setor = app.setor
        self.show_favorites = False
        self._render()

    def _select_gerencia(self, gerencia_id: str) -> None:
        gid = (gerencia_id or "").strip()
        self.selected_gerencia_id = gid
        self.preferences.set_gerencia_id(gid)
        self._apply_gerencia_filter()
        self.selected_id = None
        self.selected_setor = None
        self.show_favorites = False
        self._render()

    def _toggle_favorite(self, app_id: str) -> None:
        self.favorites.toggle(app_id)
        if self.show_favorites and not self._has_visible_favorites():
            self.show_favorites = False
        self._render()

    def _run_catalog_app(self, app: AppInfo) -> None:
        self._refresh_running(force=True)
        if self._this_app_running(app.id):
            self.run_error = "Este aplicativo ja esta em execucao."
            self._render()
            return
        if self._other_app_running(app.id):
            who = self._running_app_name() or "outro aplicativo"
            self.run_error = f"Aguarde: {who} em execucao. So um app por vez."
            self._render()
            return
        state = self.storage.get_state(app.id)
        if not state.local_path:
            self.run_error = "Arquivo nao encontrado. Use Baixar / Instalar."
            self._render()
            return
        try:
            launch_file(state.local_path, app_id=app.id, app_name=app.nome)
        except RunError as exc:
            self.run_error = str(exc)
            self._render()
            return
        self.run_error = ""
        self._refresh_running(force=True)
        self._render()

        def _nudge() -> None:
            time.sleep(0.5)
            self._refresh_running(force=True)
            self._render()

        self.page.run_thread(_nudge)

    def _request_app_update(self, app: AppInfo) -> None:
        if self.app_job_busy or self.update_busy:
            return
        self._refresh_running(force=True)
        if self._other_app_running(app.id):
            who = self._running_app_name() or "outro aplicativo"
            self.run_error = f"Aguarde: {who} em execucao. So um app por vez."
            self._render()
            return
        self.app_job_busy = True
        self.app_job_app_id = app.id
        self.app_job_progress = -1.0
        self.app_job_message = "Preparando atualizacao..."
        self.run_error = ""
        self._render()
        self.page.run_thread(lambda: self._update_catalog_app_worker(app))

    def _update_catalog_app_worker(self, app: AppInfo) -> None:
        reopen = False
        state = self.storage.get_state(app.id)
        pids = list(self._running_pids.get(app.id) or [])
        if not pids and state.local_path:
            pids = running_catalog_map({app.id: state.local_path}).get(app.id, [])
        if pids:
            self.app_job_message = "Encerrando o aplicativo em execucao..."
            self.app_job_progress = -1.0
            self._render()
            err = terminate_pids(pids)
            if err:
                self.app_job_busy = False
                self.app_job_app_id = None
                self.run_error = err
                self._refresh_running(force=True)
                self._render()
                return
            reopen = True
            self._refresh_running(force=True)

        def on_progress(pct: float, msg: str) -> None:
            self.app_job_progress = pct
            self.app_job_message = msg
            try:
                self._render()
            except Exception:
                pass

        result = self.manager.download(app, progress=on_progress)
        if result.outcome != DownloadOutcome.SUCCESS:
            self.app_job_busy = False
            self.app_job_app_id = None
            self.app_job_progress = None
            self.run_error = result.message or "Falha ao atualizar o aplicativo."
            self._render()
            return

        self.app_job_progress = 1.0
        self.app_job_message = result.message or "Atualizacao concluida."
        if reopen:
            new_state = self.storage.get_state(app.id)
            if new_state.local_path:
                self.app_job_message = "Reabrindo o aplicativo..."
                self._render()
                try:
                    launch_file(new_state.local_path, app_id=app.id, app_name=app.nome)
                    time.sleep(0.4)
                except RunError as exc:
                    self.run_error = str(exc)
        self.app_job_busy = False
        self.app_job_app_id = None
        self._refresh_running(force=True)
        self._render()

    def _download_suite_update(self) -> None:
        if self.update_busy:
            return
        suite = self.catalog.suite
        if not suite.available:
            return
        self.update_busy = True
        self.update_failed = False
        self.update_done = False
        self.update_path = None
        self.update_progress = -1.0
        self.update_message = "Baixando atualizacao..."
        self._render()
        self.page.run_thread(self._download_suite_worker)

    def _download_suite_worker(self) -> None:
        suite = self.catalog.suite
        dest = updates_dir()
        nome_final = saved_exe_filename()

        def on_progress(pct: float, msg: str) -> None:
            self.update_progress = pct
            self.update_message = msg
            try:
                self._render()
            except Exception:
                pass

        result = baixar_do_sharepoint(
            link=suite.download_url,
            pasta_destino=dest,
            nome_arquivo=nome_final,
            progress=on_progress,
        )
        if not (result.ok and result.path and result.path.exists()):
            self.update_busy = False
            self.update_failed = True
            self.update_progress = None
            self.update_message = result.message or "Falha no download da atualizacao."
            self._render()
            return

        new_exe = result.path
        if can_replace_running():
            self.update_message = "Substituindo o executavel e reiniciando..."
            self.update_progress = 0.95
            self._render()
            err = spawn_replace_and_relaunch(new_exe)
            if err:
                self.update_busy = False
                self.update_failed = True
                self.update_message = err
                self.update_path = str(new_exe)
                self._render()
                return
            self.update_done = True
            self.update_busy = False
            self._exiting = True
            if self._tray is not None:
                self._tray.stop()
            os._exit(0)

        # Sem troca in-place (dev / nao Windows): fallback no Downloads + Explorer
        downloads = config.user_downloads_dir()
        downloads.mkdir(parents=True, exist_ok=True)
        fallback = downloads / nome_final
        try:
            if new_exe.resolve() != fallback.resolve():
                if fallback.exists():
                    fallback.unlink()
                fallback.write_bytes(new_exe.read_bytes())
            path_show = fallback if fallback.exists() else new_exe
        except OSError:
            path_show = new_exe
        self.update_path = str(path_show)
        self.update_done = False
        self.update_busy = False
        self.update_failed = True
        self.update_progress = 1.0
        self.update_message = (
            f'Download ok, mas a troca automatica so roda no .exe Windows. '
            f'Arquivo: "{path_show.name}".'
        )
        self._reveal_in_explorer(path_show)
        self._render()

    def _reveal_in_explorer(self, path: Path) -> None:
        try:
            if not path.exists():
                return
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", str(path.resolve())])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _render(self) -> None:
        fav_ids = self._favorite_ids()
        has_favs = self._has_visible_favorites()
        if self.show_favorites and not has_favs:
            self.show_favorites = False

        if self.selected_setor is not None:
            visible_ids = {s.id for s in setores_visiveis(self.view_catalog)}
            if self.selected_setor not in visible_ids:
                self.selected_setor = None

        if self.selected_id is not None and self.selected_id not in self.apps_by_id:
            self.selected_id = None

        home_selected = (
            self.selected_id is None
            and self.selected_setor is None
            and not self.show_favorites
        )
        favorites_selected = self.show_favorites and self.selected_id is None
        running_name = self._running_app_name()

        self.sidebar_holder.content = build_sidebar(
            self.view_catalog,
            gerencias=self.catalog.gerencias,
            home_selected=home_selected,
            favorites_selected=favorites_selected,
            selected_setor_id=self.selected_setor,
            selected_gerencia_id=self.selected_gerencia_id,
            show_favorites=has_favs,
            suite_update=self.catalog.suite,
            update_available=self._update_available() or self.update_busy or self.update_failed,
            update_busy=self.update_busy,
            update_message=self.update_message,
            update_progress=self.update_progress,
            update_done=self.update_done,
            update_failed=self.update_failed,
            on_home=self._go_home,
            on_favorites=self._go_favorites,
            on_select_setor=self._select_setor,
            on_select_gerencia=self._select_gerencia,
            on_download_update=self._download_suite_update,
            on_check_updates=self._check_updates,
            check_updates_busy=self.sync_busy,
            start_with_windows=self.preferences.get_start_with_windows(),
            on_toggle_startup=self._toggle_startup,
            show_startup_toggle=sys.platform.startswith("win"),
            running_app_name=running_name,
        )

        if self.selected_id is not None:
            app = self.apps_by_id.get(self.selected_id)
            if app is None:
                self.content_holder.content = ft.Text(
                    "Aplicativo nao encontrado.", color=config.COLOR_TEXT
                )
            else:
                self.content_holder.content = AppDetailView(
                    self.page,
                    app,
                    self.storage,
                    self.manager,
                    is_favorite=app.id in fav_ids,
                    on_toggle_favorite=self._toggle_favorite,
                    catalog_locked=self._other_app_running(app.id),
                    running_app_name=running_name,
                    on_run=self._run_catalog_app,
                    on_update_app=self._request_app_update,
                    this_app_running=self._this_app_running(app.id),
                    other_app_running=self._other_app_running(app.id),
                    work_busy=self.app_job_busy and self.app_job_app_id == app.id,
                    work_progress=self.app_job_progress,
                    work_message=self.app_job_message or self.run_error,
                ).build()
        elif self.show_favorites:
            self.content_holder.content = build_favoritos_view(
                self._visible_favorite_apps(),
                self._select_app,
                favorite_ids=fav_ids,
                on_toggle_favorite=self._toggle_favorite,
            )
        elif self.selected_setor is not None:
            filtrados = apps_do_setor(self.apps, self.selected_setor)
            setor_info = self.catalog.setor_by_id(self.selected_setor)
            if setor_info is None:
                from models import SetorInfo

                setor_info = SetorInfo(
                    id=self.selected_setor,
                    nome=self.selected_setor,
                    descricao="",
                )
            self.content_holder.content = build_setor_view(
                setor_info,
                filtrados,
                self._select_app,
                favorite_ids=fav_ids,
                on_toggle_favorite=self._toggle_favorite,
            )
        else:
            home = build_home(
                self.apps,
                self._select_app,
                gerencia=self._gerencia_atual(),
                favorite_ids=fav_ids,
                on_toggle_favorite=self._toggle_favorite,
            )
            extras: list[ft.Control] = []
            if self.sync_message:
                extras.append(
                    ft.Container(
                        bgcolor=config.COLOR_SURFACE,
                        border_radius=8,
                        padding=12,
                        content=ft.Text(self.sync_message, size=12, color="#B9CEC3"),
                    )
                )
            if self.update_busy:
                extras.append(
                    ft.Container(
                        bgcolor=config.COLOR_SURFACE,
                        border_radius=8,
                        padding=12,
                        content=ft.Column(
                            spacing=8,
                            tight=True,
                            controls=[
                                ft.Text(
                                    progress_label(self.update_progress, self.update_message)
                                    or "Atualizando...",
                                    size=12,
                                    color="#B9CEC3",
                                ),
                                ft.ProgressBar(
                                    value=bar_value(self.update_progress),
                                    color=config.COLOR_ACCENT,
                                    bgcolor="#0A0F0C",
                                ),
                            ],
                        ),
                    )
                )
            if extras:
                self.content_holder.content = ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=16,
                    controls=[*extras, home],
                )
            else:
                self.content_holder.content = home

        try:
            self.page.update()
        except Exception:
            pass


def _window_event_name(e) -> str:
    t = getattr(e, "type", None)
    if t is None:
        return ""
    name = getattr(t, "name", None)
    if isinstance(name, str):
        return name.upper()
    text = str(t)
    if "." in text:
        text = text.split(".")[-1]
    return text.upper()


def main(page: ft.Page) -> None:
    SuiteApp(page)


if __name__ == "__main__":
    ft.run(main, assets_dir=str(config.ASSETS_DIR))
