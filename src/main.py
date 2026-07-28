"""Suite Petrobras - hub de aplicativos internos (frontend em Flet)."""
from __future__ import annotations

import flet as ft

import config
from catalog import SharePointCatalogProvider
from models import AppInfo, CatalogData, apps_do_setor
from services.download_manager import DownloadManager
from services.favorites import FavoritesStore
from services.sharepoint_manager import baixar_do_sharepoint
from services.storage import Storage
from ui.app_detail_view import AppDetailView
from ui.components import build_sidebar
from ui.home_view import build_favoritos_view, build_home, build_setor_view


class SuiteApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.storage = Storage()
        self.favorites = FavoritesStore()
        self.manager = DownloadManager(self.storage)
        self.catalog = CatalogData()
        self.apps: list[AppInfo] = []
        self.apps_by_id: dict[str, AppInfo] = {}
        self.selected_id: str | None = None
        self.selected_setor: str | None = None
        self.show_favorites = False
        self.sync_message = ""
        self.update_busy = False
        self.update_message = ""

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
        icon_path = config.resolve_window_icon()
        if icon_path is not None:
            # Windows/Flet: precisa de .ico com caminho absoluto
            self.page.window.icon = str(icon_path)
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
                    "Sincronizando catalogo com SharePoint...",
                    size=18,
                    weight=ft.FontWeight.BOLD,
                    color=config.COLOR_TEXT,
                ),
                ft.Text(
                    "Pode abrir uma janela de login (WebLogin).",
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
        self.catalog = result.catalog
        self.apps = result.catalog.apps
        self.apps_by_id = {app.id: app for app in self.apps}
        # Banner so em falha/aviso — sucesso limpo nao polui a home
        self.sync_message = result.message if not result.ok else ""
        self.selected_id = None
        self.selected_setor = None
        self.show_favorites = False
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
    def _favorite_ids(self) -> set[str]:
        return set(self.favorites.list_ids())

    def _visible_favorite_apps(self) -> list[AppInfo]:
        favs = self._favorite_ids()
        return [a for a in self.apps if a.id in favs]

    def _has_visible_favorites(self) -> bool:
        return bool(self._visible_favorite_apps())

    def _gerencia_atual(self):
        return self.catalog.gerencia_by_id(config.GERENCIA_ID)

    def _update_available(self) -> bool:
        suite = self.catalog.suite
        if not suite.available:
            return False
        return suite.versao != config.APP_VERSION

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

    def _toggle_favorite(self, app_id: str) -> None:
        self.favorites.toggle(app_id)
        # Se removeu o ultimo favorito enquanto na view Favoritos, volta ao Inicio
        if self.show_favorites and not self._has_visible_favorites():
            self.show_favorites = False
        self._render()

    def _download_suite_update(self) -> None:
        if self.update_busy:
            return
        suite = self.catalog.suite
        if not suite.available:
            return
        self.update_busy = True
        self.update_message = "Iniciando download..."
        self._render()
        self.page.run_thread(self._download_suite_worker)

    def _download_suite_worker(self) -> None:
        suite = self.catalog.suite
        dest = config.user_downloads_dir()
        dest.mkdir(parents=True, exist_ok=True)
        nome = f"SuiteAPPs_{suite.versao}.exe"
        self.update_message = f"Baixando {nome}..."
        try:
            self.page.update()
        except Exception:
            pass

        result = baixar_do_sharepoint(
            link=suite.download_url,
            pasta_destino=dest,
            nome_arquivo=nome,
        )
        if result.ok and result.path and result.path.exists():
            # Garante o nome final pedido
            final = dest / nome
            if result.path.resolve() != final.resolve():
                try:
                    if final.exists():
                        final.unlink()
                    result.path.replace(final)
                    path_show = final
                except OSError:
                    path_show = result.path
            else:
                path_show = result.path
            self.update_message = f"Salvo em: {path_show}"
        else:
            self.update_message = result.message or "Falha no download da atualizacao."
        self.update_busy = False
        self._render()

    # ------------------------------------------------------------------
    def _render(self) -> None:
        fav_ids = self._favorite_ids()
        has_favs = self._has_visible_favorites()
        if self.show_favorites and not has_favs:
            self.show_favorites = False

        home_selected = (
            self.selected_id is None
            and self.selected_setor is None
            and not self.show_favorites
        )
        favorites_selected = self.show_favorites and self.selected_id is None

        self.sidebar_holder.content = build_sidebar(
            self.catalog,
            home_selected=home_selected,
            favorites_selected=favorites_selected,
            selected_setor_id=self.selected_setor,
            show_favorites=has_favs,
            suite_update=self.catalog.suite,
            update_available=self._update_available(),
            update_busy=self.update_busy,
            update_message=self.update_message,
            on_home=self._go_home,
            on_favorites=self._go_favorites,
            on_select_setor=self._select_setor,
            on_download_update=self._download_suite_update,
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

        self.page.update()


def main(page: ft.Page) -> None:
    SuiteApp(page)


if __name__ == "__main__":
    ft.run(main, assets_dir=str(config.ASSETS_DIR))
