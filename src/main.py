"""SuiteApps - hub de aplicativos internos (frontend em Flet)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import config
from services.single_instance import HubInstance

_hub_instance: HubInstance | None = None
if __name__ == "__main__":
    _hub_instance = HubInstance()
    if not _hub_instance.acquire():
        _hub_instance.notify_restore()
        raise SystemExit(0)

import flet as ft
from catalog import SharePointCatalogProvider
from models import AppInfo, CatalogData, apps_do_setor, setores_visiveis
from services.catalog_publish import (
    DraftGerencia,
    DraftSetor,
    DraftSubSetor,
    KEEP_FOLDER,
    NEW_FOLDER,
    PublishFormState,
    ROOT_FOLDER,
    StructureFormState,
    catalog_json_media_urls,
    catalog_http_url,
    delete_catalog_app,
    fingerprint_cache_file,
    folder_choice_destination,
    infer_pasta_destino,
    publish_app,
    save_catalog_structure,
    structure_from_catalog,
)
from services.download_manager import DownloadManager, DownloadOutcome
from services.favorites import FavoritesStore
from services.preferences import PreferencesStore
from services.process_guard import running_catalog_map, snapshot_processes, terminate_pids
from services.runner import RunError, launch_file
from services.self_update import (
    can_replace_running,
    catalog_remote_filename,
    cleanup_update_artifacts,
    saved_exe_filename,
    spawn_replace_and_relaunch,
    updates_dir,
)
from services.sharepoint_manager import baixar_do_sharepoint
from services.storage import Storage
from services.tray import TrayController
from services.windows_identity import current_windows_login, user_can_publish
from services.windows_startup import set_start_with_windows, supported as startup_supported
from ui.app_detail_view import AppDetailView
from ui.components import build_sidebar
from ui.catalog_view import bind_catalog_view, session_holder
from ui.home_view import build_favoritos_view, build_home, build_setor_view
from ui.progress_util import bar_value, label as progress_label
from ui.publish_view import GERAL_KEY, NEW_APP_KEY


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
        self.show_publish = False
        self.catalog_tab = "publish"
        self.can_publish = user_can_publish(current_windows_login(), config.PUBLISH_USERS)
        self.publish_form = PublishFormState()
        self.structure = StructureFormState()
        self._publish_pick_kind = ""
        self._file_picker = None
        self._catalog_shell: ft.Column | None = None
        self._catalog_tabs = ft.Row(spacing=8)
        self._session_host = ft.Container(expand=True)
        self._catalog_session_box = ft.Container(
            expand=True,
            bgcolor=config.COLOR_SURFACE,
            border_radius=10,
            padding=12,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=self._session_host,
        )
        self._publish_layout = ft.Column(expand=True, spacing=12)
        self._estrutura_layout = ft.Row(
            expand=True,
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self._sess_pub_sel = session_holder()
        self._sess_pub_edit = session_holder()
        self._sess_str_sel = session_holder()
        self._sess_str_edit = session_holder()
        self._confirm_open = False
        self.sync_message = ""
        self.sync_notice = ""
        self._sync_notice_gen = 0
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
        self.content_holder = ft.Container(
            expand=True,
            padding=28,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
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
            # Nunca desligar prevent_close se a bandeja falhar: X nao pode destruir.
            self.page.window.prevent_close = True
            self.page.window.on_event = self._on_window_event
            self._tray = TrayController(on_show=self._show_from_tray, on_quit=self._quit_app)
            self._tray.start()
        self.page.add(self.root_row)
        if self.can_publish and hasattr(ft, "FilePicker"):
            picker = ft.FilePicker()
            self._file_picker = picker
            services = getattr(self.page, "services", None)
            if services is not None:
                try:
                    services.append(picker)
                except Exception:
                    pass
            else:
                overlay = getattr(self.page, "overlay", None)
                if overlay is not None:
                    overlay.append(picker)
        if sys.platform.startswith("win"):
            try:
                self.page.update()
            except Exception:
                pass
            try:
                self.page.run_task(self._reapply_prevent_close)
            except Exception:
                pass

    async def _reapply_prevent_close(self) -> None:
        try:
            await self.page.window.wait_until_ready_to_show()
        except Exception:
            pass
        self.page.window.prevent_close = True
        self.page.window.on_event = self._on_window_event
        try:
            self.page.update()
        except Exception:
            pass

    def _on_window_event(self, e) -> None:
        if self._exiting:
            return
        kind = _window_event_name(e)
        if kind in {"CLOSE", "MINIMIZE"}:
            self._hide_to_tray()

    def _hide_to_tray(self) -> None:
        try:
            self.page.window.prevent_close = True
            self.page.window.visible = False
            self.page.window.skip_task_bar = True
            self.page.window.minimized = True
            self.page.update()
        except Exception:
            pass

    def _show_from_tray(self) -> None:
        try:
            self.page.run_task(self._show_from_tray_async)
        except Exception:
            try:
                self.page.window.visible = True
                self.page.window.skip_task_bar = False
                self.page.window.minimized = False
                self.page.window.prevent_close = True
                self.page.update()
            except Exception:
                pass

    async def _show_from_tray_async(self) -> None:
        try:
            self.page.window.visible = True
            self.page.window.skip_task_bar = False
            self.page.window.minimized = False
            self.page.window.prevent_close = True
            self.page.update()
            await self.page.window.to_front()
        except Exception:
            pass

    def _quit_app(self) -> None:
        self._exiting = True
        if self._tray is not None:
            self._tray.stop()
        try:
            self.page.run_task(self._destroy_window)
        except Exception:
            os._exit(0)

    async def _destroy_window(self) -> None:
        try:
            self.page.window.prevent_close = False
            self.page.update()
            await self.page.window.destroy()
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
        self.sync_progress = None
        self.sync_status = ""
        if not initial and result.ok:
            self._sync_notice_gen += 1
            token = self._sync_notice_gen
            self.sync_notice = progress_label(1.0, "Catalogo sincronizado.")
            self._render()
            self.page.run_thread(lambda: self._clear_sync_notice(token))
            return
        self.sync_notice = ""
        self._render()

    def _on_sync_progress(self, pct: float, msg: str) -> None:
        self.sync_progress = pct
        self.sync_status = msg
        try:
            content = self.content_holder.content
            if content is self._catalog_shell:
                return
            if not isinstance(content, ft.Column) or len(content.controls) < 3:
                return
            bar = content.controls[0]
            if not isinstance(bar, ft.ProgressBar):
                return
            bar.value = bar_value(pct)
            content.controls[2] = ft.Text(
                progress_label(pct, msg),
                size=13,
                color="#8AA797",
            )
            self.page.update()
        except Exception:
            pass

    def _clear_sync_notice(self, token: int) -> None:
        time.sleep(2.5)
        if token != self._sync_notice_gen or self.sync_busy or self._exiting:
            return
        self.sync_notice = ""
        try:
            self._render()
        except Exception:
            pass

    def _check_updates(self) -> None:
        if self.sync_busy:
            return
        self.sync_busy = True
        self.sync_message = ""
        self.sync_notice = ""
        self._sync_notice_gen += 1
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

    def _running_app_names(self) -> str:
        self._refresh_running()
        names: list[str] = []
        for app_id, pids in self._running_pids.items():
            if not pids:
                continue
            app = self.apps_by_id.get(app_id)
            names.append(app.nome if app is not None else app_id)
        return ", ".join(names)

    # ------------------------------------------------------------------
    def _go_home(self) -> None:
        self.selected_id = None
        self.selected_setor = None
        self.show_favorites = False
        self.show_publish = False
        self._render()

    def _go_favorites(self) -> None:
        self.selected_id = None
        self.selected_setor = None
        self.show_favorites = True
        self.show_publish = False
        self._render()

    def _go_publish(self) -> None:
        if not self.can_publish:
            return
        self.selected_id = None
        self.selected_setor = None
        self.show_favorites = False
        self.show_publish = True
        fp = fingerprint_cache_file()
        if not self.publish_form.fingerprint:
            self.publish_form.fingerprint = fp
        if not self.structure.fingerprint or not self.structure.dirty:
            self.structure = structure_from_catalog(self.catalog, fp or self.publish_form.fingerprint)
        self._refresh_publish_folders()
        self._render()

    def _catalog_tab(self, tab: str) -> None:
        if not self.can_publish:
            return
        self.catalog_tab = "estrutura" if tab == "estrutura" else "publish"
        self._render()

    def _select_setor(self, setor_id: str) -> None:
        self.selected_setor = setor_id
        self.selected_id = None
        self.show_favorites = False
        self.show_publish = False
        self._render()

    def _select_app(self, app_id: str) -> None:
        self.selected_id = app_id
        app = self.apps_by_id.get(app_id)
        if app is not None and app.setor:
            self.selected_setor = app.setor
        self.show_favorites = False
        self.show_publish = False
        self._render()

    def _select_gerencia(self, gerencia_id: str) -> None:
        gid = (gerencia_id or "").strip()
        self.selected_gerencia_id = gid
        self.preferences.set_gerencia_id(gid)
        self._apply_gerencia_filter()
        self.selected_id = None
        self.selected_setor = None
        self.show_favorites = False
        self.show_publish = False
        self._render()

    def _toggle_favorite(self, app_id: str) -> None:
        self.favorites.toggle(app_id)
        if self.show_favorites and not self._has_visible_favorites():
            self.show_favorites = False
        self._render()

    def _publish_select(self, app_id: str) -> None:
        if not self.can_publish:
            return
        if not app_id or app_id == NEW_APP_KEY:
            self._publish_new()
            return
        self._publish_edit(app_id)

    def _fresh_publish_form(self, **kwargs) -> PublishFormState:
        folders = list(self.publish_form.folders)
        ferr = self.publish_form.folders_error
        fp = kwargs.pop("fingerprint", None) or self.publish_form.fingerprint or fingerprint_cache_file()
        form = PublishFormState(
            fingerprint=fp,
            folders=folders,
            folders_error=ferr,
            **kwargs,
        )
        if form.editing_id and form.current_download:
            form.folder_choice = KEEP_FOLDER
            form.move_files = False
        else:
            form.folder_choice = ROOT_FOLDER
        if not form.editing_id and not (form.upload_url or "").strip():
            form.upload_url = infer_pasta_destino()
        form.capture_baseline()
        return form

    def _refresh_publish_folders(self, force: bool = False) -> None:
        if not self.can_publish:
            return
        if self.publish_form.folders_busy:
            return
        if self.publish_form.folders and not force:
            return
        self.publish_form.folders_busy = True
        self.publish_form.folders_error = ""
        self._render()
        self.page.run_thread(self._list_folders_worker)

    def _list_folders_worker(self) -> None:
        from services.sharepoint_manager import listar_pastas_sharepoint

        names, err = listar_pastas_sharepoint(config.PUBLISH_FOLDER_URL)
        self.publish_form.folders_busy = False
        if err:
            self.publish_form.folders_error = err
        else:
            self.publish_form.folders = names
            self.publish_form.folders_error = ""
        try:
            self._render()
        except Exception:
            pass

    def _publish_new(self) -> None:
        if not self.can_publish:
            return
        self.publish_form = self._fresh_publish_form(show_form=True)
        self._refresh_publish_folders()
        self._render()

    def _publish_edit(self, app_id: str) -> None:
        if not self.can_publish:
            return
        app = next((a for a in self.catalog.apps if a.id == app_id), None)
        if app is None:
            return
        gid = ""
        for g in self.catalog.gerencias:
            if app.id in g.apps:
                gid = g.id
                break
        file_capa, file_icone = catalog_json_media_urls(app.id)
        self.publish_form = self._fresh_publish_form(
            editing_id=app.id,
            nome=app.nome,
            descricao=app.descricao,
            versao=app.versao,
            tipo=app.tipo.value,
            gerencia_id=gid,
            setor_id=app.setor,
            sub_setor_id=app.sub_setor,
            upload_url=app.upload_url,
            current_download=app.download_url,
            current_capa=file_capa or catalog_http_url(app.catalog_imagem),
            current_icone=file_icone or catalog_http_url(app.catalog_icone),
            preview_capa=str(app.imagem or "") if app.imagem and not str(app.imagem).lower().startswith(("http://", "https://")) else "",
            preview_icone=str(app.icone or "") if app.icone and not str(app.icone).lower().startswith(("http://", "https://")) else "",
            original_gerencia_id=gid,
            show_form=True,
        )
        self._refresh_publish_folders()
        self._render()

    def _publish_field(self, key: str, value: str) -> None:
        if key == "setor_id":
            self.publish_form.setor_id = "" if value in {"", GERAL_KEY} else value
            setor = self.catalog.setor_by_id(value)
            known = {s.id for s in setor.sub_setores} if setor is not None else set()
            if self.publish_form.sub_setor_id not in known:
                self.publish_form.sub_setor_id = ""
            self._render()
            return
        if key == "folder_choice":
            self.publish_form.folder_choice = value or ROOT_FOLDER
            self.publish_form.move_files = self.publish_form.folder_choice != KEEP_FOLDER
            dest, _err = folder_choice_destination(
                self.publish_form, self.publish_form.current_download
            )
            if dest:
                self.publish_form.upload_url = dest
            self._render()
            return
        if key == "new_folder_name":
            self.publish_form.new_folder_name = value
            if self.publish_form.folder_choice == NEW_FOLDER:
                dest, _err = folder_choice_destination(
                    self.publish_form, self.publish_form.current_download
                )
                if dest:
                    self.publish_form.upload_url = dest
            return
        if key == "move_files":
            self.publish_form.move_files = (value or "").strip().lower() in {
                "1",
                "true",
                "on",
                "yes",
            }
            return
        if hasattr(self.publish_form, key):
            setattr(self.publish_form, key, "" if value in {"", GERAL_KEY} else value)
            if key in {
                "nome",
                "descricao",
                "versao",
                "upload_url",
                "current_download",
                "current_capa",
                "current_icone",
            }:
                return
            self._render()

    def _publish_cancel(self) -> None:
        self.publish_form = self._fresh_publish_form()
        self._render()

    def _publish_reopen(self) -> None:
        if self.publish_form.busy or self.structure.busy:
            return
        self.publish_form.busy = True
        self.structure.busy = True
        self.publish_form.message = "Relendo catalogo remoto..."
        self.structure.message = "Relendo catalogo remoto..."
        self._render()
        self.page.run_thread(self._publish_reopen_worker)

    def _publish_reopen_worker(self) -> None:
        provider = SharePointCatalogProvider()
        result = provider.sync(progress=self._on_publish_progress)
        self.publish_form.busy = False
        if result.ok:
            self.catalog = result.catalog
            self._apply_gerencia_filter()
            self.publish_form = self._fresh_publish_form(
                message="Catalogo recarregado. Escolha o aplicativo no menu acima para editar.",
            )
            self.structure = structure_from_catalog(self.catalog, self.publish_form.fingerprint)
            self.structure.message = "Catalogo recarregado."
        else:
            self.publish_form.conflict = True
            self.publish_form.message = result.message or "Falha ao reler o catalogo."
            self.structure.busy = False
            self.structure.conflict = True
            self.structure.message = result.message or "Falha ao reler o catalogo."
        self._render()

    def _on_publish_progress(self, pct: float, msg: str) -> None:
        if self.structure.busy:
            self.structure.hold_scroll = True
            self.structure.progress = pct
            self.structure.message = msg
        else:
            self.publish_form.hold_scroll = True
            self.publish_form.progress = pct
            self.publish_form.message = msg
        try:
            self._render()
        except Exception:
            pass

    def _publish_pick(self, kind: str) -> None:
        self._publish_pick_kind = kind
        if not hasattr(ft, "FilePicker"):
            self.publish_form.message = "Seletor de arquivo indisponivel neste ambiente."
            self._render()
            return
        try:
            self.page.run_task(self._publish_pick_async)
        except Exception as exc:
            self.publish_form.message = f"Nao foi possivel abrir o seletor: {exc}"
            self._render()

    async def _publish_pick_async(self) -> None:
        kind = self._publish_pick_kind
        allowed = {
            "app": ["exe", "xlsx", "xlsm"],
            "capa": ["png", "jpg", "jpeg", "webp"],
            "icone": ["png", "jpg", "jpeg", "webp", "ico"],
        }.get(kind)
        picker = self._file_picker
        if picker is None:
            picker = ft.FilePicker()
            self._file_picker = picker
            services = getattr(self.page, "services", None)
            if services is not None:
                try:
                    services.append(picker)
                    self.page.update()
                except Exception:
                    pass
        kwargs: dict = {"allow_multiple": False}
        file_type = getattr(ft, "FilePickerFileType", None)
        if allowed and file_type is not None:
            kwargs["file_type"] = file_type.CUSTOM
            kwargs["allowed_extensions"] = allowed
        elif allowed:
            kwargs["allowed_extensions"] = allowed
        try:
            files = await picker.pick_files(**kwargs)
        except TypeError:
            files = await picker.pick_files(allow_multiple=False)
        if not files:
            return
        selected = files[0]
        path = getattr(selected, "path", None) or ""
        if not path:
            self.publish_form.message = (
                "O seletor nao devolveu o caminho do arquivo. Tente de novo."
            )
            self._render()
            return
        if kind == "app":
            self.publish_form.app_path = path
        elif kind == "capa":
            self.publish_form.capa_path = path
        elif kind == "icone":
            self.publish_form.icone_path = path
        self._render()

    def _publish_save(self) -> None:
        if not self.can_publish or self.publish_form.busy or self.structure.busy:
            return
        self.publish_form.busy = True
        self.publish_form.conflict = False
        self.publish_form.hold_scroll = True
        self.publish_form.notice = ""
        self.publish_form.notice_ok = False
        self.publish_form.message = "Publicando..."
        self.publish_form.progress = -1.0
        self._render()
        form = self.publish_form
        self.page.run_thread(lambda: self._publish_save_worker(form))

    def _gerencia_id_for_app(self, app_id: str) -> str:
        for g in self.catalog.gerencias:
            if app_id in g.apps:
                return g.id
        return ""

    def _apply_saved_app_to_form(self, app: AppInfo, *, notice: str) -> None:
        gid = self._gerencia_id_for_app(app.id)
        file_capa, file_icone = catalog_json_media_urls(app.id)
        form = self.publish_form
        form.editing_id = app.id
        form.nome = app.nome
        form.descricao = app.descricao
        form.versao = app.versao
        form.tipo = app.tipo.value
        form.gerencia_id = gid
        form.setor_id = app.setor
        form.sub_setor_id = app.sub_setor
        form.upload_url = app.upload_url
        form.current_download = app.download_url
        form.current_capa = file_capa or catalog_http_url(app.catalog_imagem)
        form.current_icone = file_icone or catalog_http_url(app.catalog_icone)
        form.preview_capa = (
            str(app.imagem or "")
            if app.imagem and not str(app.imagem).lower().startswith(("http://", "https://"))
            else ""
        )
        form.preview_icone = (
            str(app.icone or "")
            if app.icone and not str(app.icone).lower().startswith(("http://", "https://"))
            else ""
        )
        form.original_gerencia_id = gid
        form.app_path = ""
        form.capa_path = ""
        form.icone_path = ""
        form.folder_choice = KEEP_FOLDER
        form.new_folder_name = ""
        form.move_files = False
        form.busy = False
        form.conflict = False
        form.message = ""
        form.progress = None
        form.notice = notice
        form.notice_ok = True
        form.show_form = True
        form.capture_baseline()

    def _publish_save_worker(self, form: PublishFormState) -> None:
        result = publish_app(
            form,
            expected_fingerprint=form.fingerprint,
            progress=self._on_publish_progress,
        )
        if result.conflict:
            self.publish_form.busy = False
            self.publish_form.conflict = True
            self.publish_form.hold_scroll = True
            self.publish_form.message = result.message
            self._render()
            self.publish_form.hold_scroll = False
            return
        if not result.ok:
            self.publish_form.busy = False
            self.publish_form.hold_scroll = True
            self.publish_form.message = result.message
            self._render()
            self.publish_form.hold_scroll = False
            return
        if result.catalog is not None:
            self.catalog = result.catalog
        else:
            provider = SharePointCatalogProvider()
            synced = provider.sync(progress=self._on_publish_progress)
            if synced.ok:
                self.catalog = synced.catalog
        self._apply_gerencia_filter()
        fp = result.fingerprint or fingerprint_cache_file()
        was_edit = bool(form.editing_id)
        app_id = (result.app_id or form.editing_id or "").strip()
        notice = "Item atualizado." if was_edit else "Catalogo salvo."
        self.publish_form.fingerprint = fp
        app = next((a for a in self.catalog.apps if a.id == app_id), None)
        if app is not None:
            self._apply_saved_app_to_form(app, notice=notice)
        else:
            self.publish_form.busy = False
            self.publish_form.app_path = ""
            self.publish_form.capa_path = ""
            self.publish_form.icone_path = ""
            self.publish_form.notice = notice
            self.publish_form.notice_ok = True
            self.publish_form.message = ""
            self.publish_form.progress = None
            self.publish_form.capture_baseline()
        self.structure = structure_from_catalog(self.catalog, fp)
        self.publish_form.hold_scroll = False
        self._render()

    def _publish_delete(self) -> None:
        if not self.can_publish or self.publish_form.busy or self.structure.busy or self._confirm_open:
            return
        app_id = (self.publish_form.editing_id or "").strip()
        if not app_id:
            return
        nome = self.publish_form.nome or app_id
        self._confirm_open = True
        dlg_holder: dict = {"done": False}

        def _close(_e=None) -> None:
            self._confirm_open = False
            dlg = dlg_holder.get("dlg")
            pop = getattr(self.page, "pop_dialog", None)
            if callable(pop):
                try:
                    pop()
                    return
                except Exception:
                    pass
            if dlg is not None:
                try:
                    dlg.open = False
                    self.page.update()
                except Exception:
                    pass

        def _pick(delete_files: bool):
            def _run(_e=None, files=delete_files) -> None:
                if dlg_holder["done"]:
                    return
                dlg_holder["done"] = True
                _close()
                self._publish_delete_confirmed(app_id, files)

            return _run

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Excluir?"),
            content=ft.Text(
                f'Excluir "{nome}"? '
                "So do catalogo remove o app do catalog.json. "
                "Tambem os arquivos apaga o aplicativo, a capa e o icone no SharePoint."
            ),
            actions=[
                ft.TextButton(content="Cancelar", on_click=_close),
                ft.OutlinedButton(content="Excluir so do catalogo", on_click=_pick(False)),
                ft.FilledButton(
                    content="Excluir tambem os arquivos no SharePoint",
                    on_click=_pick(True),
                ),
            ],
        )
        dlg_holder["dlg"] = dlg
        show = getattr(self.page, "show_dialog", None)
        if callable(show):
            show(dlg)
            return
        open_fn = getattr(self.page, "open", None)
        if callable(open_fn):
            open_fn(dlg)
            return
        try:
            self.page.overlay.append(dlg)
            dlg.open = True
            self.page.update()
        except Exception:
            self._confirm_open = False

    def _publish_delete_confirmed(self, app_id: str, delete_files: bool) -> None:
        if not self.can_publish or self.publish_form.busy or self.structure.busy:
            return
        self.publish_form.busy = True
        self.publish_form.conflict = False
        self.publish_form.hold_scroll = True
        self.publish_form.notice = ""
        self.publish_form.notice_ok = False
        self.publish_form.message = "Excluindo..."
        self.publish_form.progress = -1.0
        self._render()
        self.page.run_thread(lambda: self._publish_delete_worker(app_id, delete_files))

    def _publish_delete_worker(self, app_id: str, delete_files: bool) -> None:
        result = delete_catalog_app(
            app_id,
            expected_fingerprint=self.publish_form.fingerprint,
            delete_sharepoint_files=delete_files,
            progress=self._on_publish_progress,
        )
        if result.conflict:
            self.publish_form.busy = False
            self.publish_form.conflict = True
            self.publish_form.hold_scroll = True
            self.publish_form.message = result.message
            self._render()
            self.publish_form.hold_scroll = False
            return
        if not result.ok:
            self.publish_form.busy = False
            self.publish_form.hold_scroll = True
            self.publish_form.message = result.message
            self._render()
            self.publish_form.hold_scroll = False
            return
        if result.catalog is not None:
            self.catalog = result.catalog
        self._apply_gerencia_filter()
        fp = result.fingerprint or fingerprint_cache_file()
        self.publish_form = self._fresh_publish_form(
            fingerprint=fp,
            notice="Item excluido.",
            notice_ok=True,
        )
        self.structure = structure_from_catalog(self.catalog, fp)
        self.publish_form.hold_scroll = False
        self._render()

    def _structure_select(self, sel: str) -> None:
        if not self.can_publish:
            return
        self.structure.sel = sel
        self.structure.notice = ""
        self.structure.notice_ok = False
        self._render()

    def _structure_target(self):
        sel = self.structure.sel or ""
        try:
            if sel.startswith("g:"):
                return self.structure.gerencias[int(sel.split(":")[1])]
            if sel.startswith("s:"):
                return self.structure.setores[int(sel.split(":")[1])]
            if sel.startswith("sub:"):
                _, si, subi = sel.split(":")
                return self.structure.setores[int(si)].sub_setores[int(subi)]
        except (IndexError, ValueError):
            return None
        return None

    def _structure_field(self, key: str, value: str) -> None:
        if not self.can_publish:
            return
        self.structure.dirty = True
        if self.structure.sel == "geral" or key == "gerencia_geral":
            if key == "gerencia_geral":
                self.structure.gerencia_geral = value
            return
        target = self._structure_target()
        if target is not None and hasattr(target, key):
            setattr(target, key, value)

    def _structure_toggle_app(self, app_id: str, checked: bool) -> None:
        if not self.can_publish:
            return
        sel = self.structure.sel or ""
        if not sel.startswith("g:"):
            return
        g = self.structure.gerencias[int(sel.split(":")[1])]
        self.structure.dirty = True
        if checked and app_id not in g.apps:
            g.apps.append(app_id)
        elif not checked:
            g.apps = [x for x in g.apps if x != app_id]
        self._render()

    def _structure_new(self, kind: str) -> None:
        self._structure_new_at(kind, None)

    def _structure_new_subsetor(self, setor_index: int) -> None:
        self._structure_new_at("subsetor", setor_index)

    def _structure_new_at(self, kind: str, setor_index: int | None) -> None:
        if not self.can_publish:
            return
        self.structure.dirty = True
        if kind == "gerencia":
            self.structure.gerencias.append(DraftGerencia(nome="Nova gerencia"))
            self.structure.sel = f"g:{len(self.structure.gerencias) - 1}"
        elif kind == "setor":
            self.structure.setores.append(DraftSetor(nome="Novo setor"))
            self.structure.sel = f"s:{len(self.structure.setores) - 1}"
        elif kind == "subsetor":
            si = setor_index
            sel = self.structure.sel or ""
            if si is None:
                if sel.startswith("s:"):
                    si = int(sel.split(":")[1])
                elif sel.startswith("sub:"):
                    si = int(sel.split(":")[1])
                elif self.structure.setores:
                    si = len(self.structure.setores) - 1
            if si is None:
                self.structure.message = "Crie um setor antes do sub-setor."
                self._render()
                return
            if si < 0 or si >= len(self.structure.setores):
                return
            setor = self.structure.setores[si]
            setor.sub_setores.append(DraftSubSetor(nome="Novo sub-setor"))
            self.structure.sel = f"sub:{si}:{len(setor.sub_setores) - 1}"
        self._render()

    def _structure_delete(self, sel: str) -> None:
        if not self.can_publish or self.structure.busy or self.publish_form.busy or self._confirm_open:
            return
        label = "este item"
        if sel.startswith("g:"):
            try:
                g = self.structure.gerencias[int(sel.split(":")[1])]
                label = f"a gerencia \"{g.nome or g.id or 'Gerencia'}\""
            except (IndexError, ValueError):
                return
        elif sel.startswith("s:"):
            try:
                s = self.structure.setores[int(sel.split(":")[1])]
                label = f"o setor \"{s.nome or s.id or 'Setor'}\""
            except (IndexError, ValueError):
                return
        elif sel.startswith("sub:"):
            try:
                _, si, subi = sel.split(":")
                sub = self.structure.setores[int(si)].sub_setores[int(subi)]
                label = f"o sub-setor \"{sub.nome or sub.id or 'Sub-setor'}\""
            except (IndexError, ValueError):
                return
        else:
            return
        self._confirm_dialog(
            "Excluir?",
            f"Excluir {label}? Sim atualiza o catalog.json agora. Nao cancela.",
            lambda: self._structure_delete_confirmed(sel),
        )

    def _structure_delete_confirmed(self, sel: str) -> None:
        if not self.can_publish or self.structure.busy or self.publish_form.busy:
            return
        remote = False
        try:
            if sel.startswith("g:"):
                i = int(sel.split(":")[1])
                g = self.structure.gerencias[i]
                remote = bool(g.orig_id)
                del self.structure.gerencias[i]
                self.structure.sel = ""
            elif sel.startswith("s:"):
                i = int(sel.split(":")[1])
                setor = self.structure.setores[i]
                remote = bool(setor.orig_id)
                del self.structure.setores[i]
                self.structure.sel = ""
            elif sel.startswith("sub:"):
                _, si, subi = sel.split(":")
                si_i, sub_i = int(si), int(subi)
                sub = self.structure.setores[si_i].sub_setores[sub_i]
                remote = bool(sub.orig_id)
                del self.structure.setores[si_i].sub_setores[sub_i]
                self.structure.sel = f"s:{si_i}"
            else:
                return
        except (IndexError, ValueError):
            return
        self.structure.dirty = True
        if remote:
            self._structure_save()
        else:
            self._render()

    def _confirm_dialog(self, title: str, body: str, on_yes) -> None:
        if self._confirm_open or self.structure.busy or self.publish_form.busy:
            return
        self._confirm_open = True
        dlg_holder: dict = {"done": False}

        def _close(_e=None) -> None:
            self._confirm_open = False
            dlg = dlg_holder.get("dlg")
            pop = getattr(self.page, "pop_dialog", None)
            if callable(pop):
                try:
                    pop()
                    return
                except Exception:
                    pass
            if dlg is not None:
                try:
                    dlg.open = False
                    self.page.update()
                except Exception:
                    pass

        def _yes(e) -> None:
            if dlg_holder["done"]:
                return
            dlg_holder["done"] = True
            _close()
            on_yes()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(body),
            actions=[
                ft.TextButton(content="Nao", on_click=_close),
                ft.FilledButton(content="Sim", on_click=_yes),
            ],
        )
        dlg_holder["dlg"] = dlg
        show = getattr(self.page, "show_dialog", None)
        if callable(show):
            show(dlg)
            return
        open_fn = getattr(self.page, "open", None)
        if callable(open_fn):
            open_fn(dlg)
            return
        try:
            self.page.overlay.append(dlg)
            dlg.open = True
            self.page.update()
        except Exception:
            self._confirm_open = False

    def _structure_save(self) -> None:
        if not self.can_publish or self.structure.busy:
            return
        self.structure.busy = True
        self.structure.conflict = False
        self.structure.hold_scroll = True
        self.structure.notice = ""
        self.structure.notice_ok = False
        self.structure.message = "Publicando estrutura..."
        self.structure.progress = -1.0
        self._render()
        form = self.structure
        self.page.run_thread(lambda: self._structure_save_worker(form))

    def _structure_save_worker(self, form: StructureFormState) -> None:
        result = save_catalog_structure(
            form,
            expected_fingerprint=form.fingerprint,
            progress=self._on_publish_progress,
        )
        if result.conflict:
            self.structure.busy = False
            self.structure.conflict = True
            self.structure.hold_scroll = True
            self.structure.message = result.message
            self._render()
            self.structure.hold_scroll = False
            return
        if not result.ok:
            self.structure.busy = False
            self.structure.hold_scroll = True
            self.structure.message = result.message
            self._render()
            self.structure.hold_scroll = False
            return
        if result.catalog is not None:
            self.catalog = result.catalog
        else:
            provider = SharePointCatalogProvider()
            synced = provider.sync(progress=self._on_publish_progress)
            if synced.ok:
                self.catalog = synced.catalog
        self._apply_gerencia_filter()
        fp = result.fingerprint or fingerprint_cache_file()
        self.publish_form.fingerprint = fp
        sel = form.sel
        self.structure = structure_from_catalog(self.catalog, fp)
        self.structure.sel = sel
        self.structure.notice = "Catalogo salvo."
        self.structure.notice_ok = True
        self.structure.hold_scroll = False
        self.catalog_tab = "estrutura"
        self._render()

    def _run_catalog_app(self, app: AppInfo) -> None:
        self._refresh_running(force=True)
        if self._this_app_running(app.id):
            self.run_error = "Este aplicativo ja esta em execucao."
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
        cleanup_update_artifacts()
        dest_dir = updates_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Nome remoto = URL/catalogo. Nao copia *.new.exe ao lado do hub.
        nome_remoto = catalog_remote_filename(suite.download_url)

        def on_progress(pct: float, msg: str) -> None:
            self.update_progress = pct
            self.update_message = msg
            try:
                self._render()
            except Exception:
                pass

        result = baixar_do_sharepoint(
            link=suite.download_url,
            pasta_destino=dest_dir,
            nome_arquivo=nome_remoto,
            progress=on_progress,
        )
        if not (result.ok and result.path and result.path.exists()):
            cleanup_update_artifacts()
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
                cleanup_update_artifacts()
                self.update_busy = False
                self.update_failed = True
                self.update_message = err
                self.update_path = None
                self._render()
                return
            self.update_done = True
            self.update_busy = False
            self._exiting = True
            if self._tray is not None:
                self._tray.stop()
            # Saida normal: o bootloader pode limpar o _MEI. O .cmd so inicia
            # o exe novo depois que este PID acabar, e apaga updates/ e extras.
            try:
                self.page.window.prevent_close = False
                self.page.update()
                self.page.run_task(self.page.window.destroy)
            except Exception:
                os._exit(0)
            return

        # Sem troca in-place (dev / nao Windows): fallback no Downloads + Explorer
        downloads = config.user_downloads_dir()
        downloads.mkdir(parents=True, exist_ok=True)
        fallback = downloads / saved_exe_filename()
        try:
            if new_exe.resolve() != fallback.resolve():
                if fallback.exists():
                    fallback.unlink()
                fallback.write_bytes(new_exe.read_bytes())
            path_show = fallback if fallback.exists() else new_exe
        except OSError:
            path_show = new_exe
        cleanup_update_artifacts()
        if not Path(path_show).exists() and fallback.exists():
            path_show = fallback
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
    def _ensure_catalog_shell(self) -> ft.Column:
        self._publish_layout.controls = [self._sess_pub_sel, self._sess_pub_edit]
        self._estrutura_layout.controls = [self._sess_str_sel, self._sess_str_edit]
        self._catalog_session_box.content = self._session_host
        if self._catalog_shell is None:
            self._session_host.content = self._publish_layout
            self._catalog_shell = ft.Column(
                expand=True,
                spacing=12,
                controls=[
                    ft.Text("Catalogo", size=22, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                    self._catalog_tabs,
                    self._catalog_session_box,
                ],
            )
        else:
            title = self._catalog_shell.controls[0] if self._catalog_shell.controls else None
            if not isinstance(title, ft.Text):
                title = ft.Text("Catalogo", size=22, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT)
            self._catalog_shell.controls = [title, self._catalog_tabs, self._catalog_session_box]
        return self._catalog_shell

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
            and not self.show_publish
        )
        favorites_selected = self.show_favorites and self.selected_id is None
        running_name = self._running_app_names()

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
            check_updates_notice=self.sync_notice,
            start_with_windows=self.preferences.get_start_with_windows(),
            on_toggle_startup=self._toggle_startup,
            show_startup_toggle=sys.platform.startswith("win"),
            running_app_name=running_name,
            show_publish=self.can_publish,
            publish_selected=self.show_publish,
            on_publish=self._go_publish if self.can_publish else None,
        )

        if self.show_publish and self.can_publish:
            shell = self._ensure_catalog_shell()
            bind_catalog_view(
                self.catalog,
                self.publish_form,
                self.structure,
                self.catalog_tab,
                on_tab=self._catalog_tab,
                on_select_app=self._publish_select,
                on_save=self._publish_save,
                on_cancel=self._publish_cancel,
                on_pick=self._publish_pick,
                on_field=self._publish_field,
                on_reopen=self._publish_reopen,
                on_refresh_folders=lambda: self._refresh_publish_folders(True),
                on_delete_app=self._publish_delete,
                on_structure_select=self._structure_select,
                on_structure_field=self._structure_field,
                on_structure_toggle_app=self._structure_toggle_app,
                on_structure_new=self._structure_new,
                on_structure_new_subsetor=self._structure_new_subsetor,
                on_structure_delete=self._structure_delete,
                on_structure_save=self._structure_save,
                on_structure_reopen=self._publish_reopen,
                tab_row=self._catalog_tabs,
                session_host=self._session_host,
                publish_layout=self._publish_layout,
                estrutura_layout=self._estrutura_layout,
                publish_select=self._sess_pub_sel,
                publish_edit=self._sess_pub_edit,
                structure_select=self._sess_str_sel,
                structure_edit=self._sess_str_edit,
            )
            self.content_holder.content = shell
        elif self.selected_id is not None:
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
                    on_run=self._run_catalog_app,
                    on_update_app=self._request_app_update,
                    this_app_running=self._this_app_running(app.id),
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
    app = SuiteApp(page)
    if _hub_instance is not None:
        _hub_instance.watch_restore(app._show_from_tray)


if __name__ == "__main__":
    try:
        ft.run(main, assets_dir=str(config.ASSETS_DIR))
    finally:
        if _hub_instance is not None:
            _hub_instance.release()
