"""Suite Petrobras - hub de aplicativos internos (frontend em Flet)."""
from __future__ import annotations

import flet as ft

import config
from catalog import get_default_provider
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
        self.apps: list[AppInfo] = get_default_provider().load()
        self.apps_by_id = {app.id: app for app in self.apps}
        self.selected_id: str | None = None

        self.sidebar_holder = ft.Container()
        self.content_holder = ft.Container(expand=True, padding=28)

        self._setup_page()
        self._render()

    # ------------------------------------------------------------------
    def _setup_page(self) -> None:
        self.page.title = config.APP_NAME
        self.page.window_width = 1180
        self.page.window_height = 760
        self.page.window_min_width = 900
        self.page.window_min_height = 600
        self.page.bgcolor = config.COLOR_BG
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.theme = ft.Theme(color_scheme_seed=config.COLOR_PRIMARY)
        self.page.padding = 0

        self.page.add(
            ft.Row(
                expand=True,
                spacing=0,
                controls=[
                    self.sidebar_holder,
                    ft.Container(width=1, bgcolor="#22332B"),
                    self.content_holder,
                ],
            )
        )

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
            self.content_holder.content = build_home(self.apps, self._select_app)
        else:
            app = self.apps_by_id.get(self.selected_id)
            if app is None:
                self.content_holder.content = ft.Text("Aplicativo nao encontrado.", color=config.COLOR_TEXT)
            else:
                self.content_holder.content = AppDetailView(
                    self.page, app, self.storage, self.manager
                ).build()

        self.page.update()


def main(page: ft.Page) -> None:
    SuiteApp(page)


if __name__ == "__main__":
    ft.app(target=main, assets_dir=str(config.ASSETS_DIR))
