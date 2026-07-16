"""Suite Petrobras - hub de aplicativos internos (frontend em Flet)."""
from __future__ import annotations

import flet as ft

import config
from catalog import SharePointCatalogProvider
from models import AppInfo
from services.download_manager import DownloadManager
from services.storage import Storage
from ui.app_detail_view import AppDetailView
from ui.components import build_sidebar
from ui.home_view import build_home


class SuiteApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.storage = Storage()
        self.manager = DownloadManager(self.storage)
        self.apps: list[AppInfo] = []
        self.apps_by_id: dict[str, AppInfo] = {}
        self.selected_id: str | None = None
        self.sync_message = ""

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
        self._show_sync_screen()
        self.page.run_thread(self._sync_catalog_worker)

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
        self.page.add(self.root_row)

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
                ft.ProgressRing(color=config.COLOR_ACCENT, width=48, height=48),
                ft.Text(
                    "Sincronizando catalogo...",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=config.COLOR_TEXT,
                ),
                ft.Text(
                    "Baixando catalog.json e imagens (download direto).",
                    size=13,
                    color="#8AA797",
                ),
            ],
        )
        self.page.update()

    def _sync_catalog_worker(self) -> None:
        provider = SharePointCatalogProvider()
        result = provider.sync(
            progress=lambda _p, msg: self._update_sync_status(msg)
        )
        self.apps = result.apps
        self.apps_by_id = {app.id: app for app in self.apps}
        self.sync_message = result.message
        self.selected_id = None
        self._render()

    def _update_sync_status(self, msg: str) -> None:
        # Atualiza so o texto da splash se ainda estiver nela
        try:
            content = self.content_holder.content
            if isinstance(content, ft.Column) and len(content.controls) >= 3:
                content.controls[2] = ft.Text(msg, size=13, color="#8AA797")
                self.page.update()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _go_home(self) -> None:
        self.selected_id = None
        self._render()

    def _select_app(self, app_id: str) -> None:
        self.selected_id = app_id
        self._render()

    # ------------------------------------------------------------------
    def _render(self) -> None:
        self.sidebar_holder.content = build_sidebar(
            self.apps, self.selected_id, self._go_home, self._select_app
        )

        if self.selected_id is None:
            home = build_home(self.apps, self._select_app)
            if self.sync_message:
                banner = ft.Container(
                    bgcolor=config.COLOR_SURFACE,
                    border_radius=8,
                    padding=12,
                    content=ft.Text(self.sync_message, size=12, color="#B9CEC3"),
                )
                self.content_holder.content = ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=16,
                    controls=[banner, home],
                )
            else:
                self.content_holder.content = home
        else:
            app = self.apps_by_id.get(self.selected_id)
            if app is None:
                self.content_holder.content = ft.Text(
                    "Aplicativo nao encontrado.", color=config.COLOR_TEXT
                )
            else:
                self.content_holder.content = AppDetailView(
                    self.page, app, self.storage, self.manager
                ).build()

        self.page.update()


def main(page: ft.Page) -> None:
    SuiteApp(page)


if __name__ == "__main__":
    # assets_dir inclui o cache de imagens do catalogo quando necessario
    ft.run(main, assets_dir=str(config.ASSETS_DIR))
