"""Ponteiro de links, download silencioso e a pagina do menu."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flet as ft

import config
from catalog.provider import SharePointCatalogProvider
from main import SuiteApp
from models import (
    AppInfo,
    CatalogData,
    LinksInfo,
    parse_catalog_dict,
    parse_links_payload,
)
from services.favorites import FavoritesStore, move_before
from services.link_favorites import LinkFavoritesStore, visible_favorite_links
from ui.home_view import build_favoritos_view
from services.links import (
    links_menu_visible,
    load_local_links,
    should_download_links,
    sync_links,
)
from services.sharepoint_manager import SharePointResult
from ui.components import build_sidebar
from ui.links_view import build_links_view


def _walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None and not isinstance(content, str):
        yield from _walk(content)
    controls = getattr(control, "controls", None)
    if isinstance(controls, (list, tuple)):
        for child in controls:
            yield from _walk(child)


def _texts(control) -> list[str]:
    found = []
    for node in _walk(control):
        value = getattr(node, "value", None)
        if isinstance(value, str) and value:
            found.append(value)
    return found


def _buttons(control) -> list[ft.Button]:
    return [node for node in _walk(control) if isinstance(node, ft.Button)]


class _Result:
    def __init__(self, ok: bool, path: Path | None = None) -> None:
        self.ok = ok
        self.path = path
        self.message = "" if ok else "falhou"


class _Page:
    def __init__(self) -> None:
        self.ran: list[tuple] = []
        self.updates = 0

    def run_task(self, handler, *args, **kwargs):
        self.ran.append(args)

    def update(self) -> None:
        self.updates += 1


class _Holder:
    def __init__(self) -> None:
        self.content = None


class _Favorites:
    def list_ids(self) -> list[str]:
        return []


class _InstallState:
    status = "ausente"
    local_path = ""


class _Storage:
    def get_state(self, _app_id: str) -> _InstallState:
        return _InstallState()


class _Prefs:
    def get_start_with_windows(self) -> bool:
        return False

    def get_gerencia_id(self) -> str:
        return ""


def _valid_body() -> str:
    return json.dumps(
        {
            "grupos": [
                {
                    "titulo": "Portais",
                    "links": [
                        {
                            "titulo": "Ponto",
                            "descricao": "Registro de ponto",
                            "url": "https://exemplo.com/ponto",
                        }
                    ],
                }
            ]
        }
    )


class CatalogPointerTests(unittest.TestCase):
    def test_old_catalog_without_links_still_parses(self) -> None:
        catalog = parse_catalog_dict({"apps": [{"id": "a", "nome": "A"}]})
        self.assertEqual(catalog.apps[0].id, "a")
        self.assertEqual(catalog.links, LinksInfo())
        self.assertFalse(catalog.links.configured)
        self.assertFalse(catalog.dicas.configured)

    def test_links_block_needs_url_and_version(self) -> None:
        only_url = parse_catalog_dict({"links": {"url": "https://sp/links.json"}})
        only_version = parse_catalog_dict({"links": {"versao": "1"}})
        broken = parse_catalog_dict({"links": "nao-e-objeto"})
        ready = parse_catalog_dict(
            {
                "links": {
                    "url": "https://empresa.sharepoint.com/teams/seu-time/_layouts/15/download.aspx?UniqueId=abc",
                    "versao": "1",
                }
            }
        )
        self.assertFalse(only_url.links.configured)
        self.assertFalse(only_version.links.configured)
        self.assertFalse(broken.links.configured)
        self.assertTrue(ready.links.configured)
        self.assertIn("download.aspx?UniqueId=", ready.links.url)

    def test_example_files_have_pointer_and_two_groups(self) -> None:
        catalog = json.loads((ROOT / "catalog.example.json").read_text(encoding="utf-8"))
        pointer = catalog["links"]
        self.assertIn("download.aspx?UniqueId=", pointer["url"])
        self.assertTrue(str(pointer["versao"]).strip())
        dicas = catalog["dicas"]
        self.assertEqual(set(pointer), set(dicas))
        body = json.loads((ROOT / "links.example.json").read_text(encoding="utf-8"))
        groups = parse_links_payload(body)
        self.assertEqual(len(groups), 2)
        for group in groups:
            self.assertTrue(group.titulo)
            self.assertTrue(group.links)
            for item in group.links:
                self.assertTrue(item.titulo)
                self.assertTrue(item.descricao)
                self.assertTrue(item.url.startswith("https://"))

    def test_filter_keeps_the_links_pointer(self) -> None:
        info = LinksInfo(url="https://sp/links.json", versao="4")
        catalog = parse_catalog_dict(
            {
                "links": {"url": info.url, "versao": info.versao},
                "gerencias": [{"id": "g", "nome": "G", "apps": ["a"]}],
                "apps": [{"id": "a", "nome": "A"}, {"id": "b", "nome": "B"}],
            }
        )
        filtered = catalog.filter_for_gerencia("g")
        self.assertEqual([app.id for app in filtered.apps], ["a"])
        self.assertEqual(filtered.links, info)


class DownloadTests(unittest.TestCase):
    def test_missing_url_or_version_does_not_download(self) -> None:
        self.assertFalse(
            should_download_links(url="", versao="1", saved_versao="", local_exists=False)
        )
        self.assertFalse(
            should_download_links(
                url="https://empresa.sharepoint.com/links.json",
                versao="",
                saved_versao="",
                local_exists=False,
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            links = root / "links.json"
            version = root / "links.versao"
            calls: list[str] = []

            def download(url: str, dest: Path) -> _Result:
                calls.append(url)
                return _Result(False)

            for info in (
                LinksInfo(url="", versao="1"),
                LinksInfo(url="https://sp/links.json", versao=""),
            ):
                catalog = CatalogData(links=info)
                self.assertEqual(
                    sync_links(
                        catalog,
                        download=download,
                        links_path=links,
                        version_path=version,
                    ),
                    "skipped",
                )
                self.assertFalse(
                    links_menu_visible(catalog, links_path=links, version_path=version)
                )
            self.assertEqual(calls, [])

    def test_same_version_with_local_file_skips(self) -> None:
        self.assertFalse(
            should_download_links(
                url="https://empresa.sharepoint.com/links.json",
                versao="2",
                saved_versao="2",
                local_exists=True,
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            links = root / "links.json"
            version = root / "links.versao"
            links.write_text(_valid_body(), encoding="utf-8")
            version.write_text("2", encoding="utf-8")
            calls: list[str] = []

            def download(url: str, dest: Path) -> _Result:
                calls.append(url)
                return _Result(False)

            catalog = CatalogData(links=LinksInfo(url="https://sp/links.json", versao="2"))
            self.assertEqual(
                sync_links(
                    catalog,
                    download=download,
                    links_path=links,
                    version_path=version,
                ),
                "skipped",
            )
            self.assertEqual(calls, [])
            self.assertTrue(links_menu_visible(catalog, links_path=links, version_path=version))
            self.assertEqual(load_local_links(links)[0].links[0].titulo, "Ponto")

    def test_valid_download_writes_file_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            links = root / "links.json"
            version = root / "links.versao"
            calls: list[str] = []

            def download(url: str, dest: Path) -> _Result:
                calls.append(url)
                dest.write_text(_valid_body(), encoding="utf-8")
                return _Result(True, dest)

            catalog = CatalogData(links=LinksInfo(url="https://sp/links.json", versao="3"))
            self.assertEqual(
                sync_links(
                    catalog,
                    download=download,
                    links_path=links,
                    version_path=version,
                ),
                "downloaded",
            )
            self.assertEqual(calls, ["https://sp/links.json"])
            self.assertIn("Ponto", links.read_text(encoding="utf-8"))
            self.assertEqual(version.read_text(encoding="utf-8"), "3")
            self.assertFalse((root / "links.json.partial").exists())
            self.assertTrue(links_menu_visible(catalog, links_path=links, version_path=version))

    def test_failure_or_invalid_json_does_not_show_the_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            links = root / "links.json"
            version = root / "links.versao"
            original = _valid_body()
            links.write_text(original, encoding="utf-8")
            version.write_text("1", encoding="utf-8")

            def boom(url: str, dest: Path) -> _Result:
                dest.write_text("lixo", encoding="utf-8")
                raise RuntimeError("rede caiu")

            catalog = CatalogData(links=LinksInfo(url="https://sp/links.json", versao="4"))
            self.assertEqual(
                sync_links(catalog, download=boom, links_path=links, version_path=version),
                "failed",
            )
            self.assertEqual(links.read_text(encoding="utf-8"), original)
            self.assertEqual(version.read_text(encoding="utf-8"), "1")
            self.assertFalse((root / "links.json.partial").exists())
            self.assertFalse(links_menu_visible(catalog, links_path=links, version_path=version))

            def html(url: str, dest: Path) -> _Result:
                dest.write_text("<html>nao</html>", encoding="utf-8")
                return _Result(True, dest)

            self.assertEqual(
                sync_links(catalog, download=html, links_path=links, version_path=version),
                "failed",
            )
            self.assertEqual(links.read_text(encoding="utf-8"), original)
            self.assertEqual(version.read_text(encoding="utf-8"), "1")
            self.assertFalse(links_menu_visible(catalog, links_path=links, version_path=version))

            links.write_text("{nao e json", encoding="utf-8")
            version.write_text("4", encoding="utf-8")
            self.assertEqual(
                sync_links(
                    catalog,
                    download=boom,
                    links_path=links,
                    version_path=version,
                ),
                "skipped",
            )
            self.assertFalse(links_menu_visible(catalog, links_path=links, version_path=version))

    def test_provider_keeps_catalog_quiet_when_links_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "catalog"
            cache.mkdir()
            (cache / "images").mkdir()
            links = cache / "links.json"
            version = cache / "links.versao"
            original = _valid_body()
            links.write_text(original, encoding="utf-8")
            version.write_text("1", encoding="utf-8")
            body = json.dumps(
                {
                    "apps": [],
                    "links": {
                        "url": "https://empresa.sharepoint.com/sites/s/_layouts/15/download.aspx?UniqueId=abc",
                        "versao": "2",
                    },
                }
            )

            def fake(link, pasta_destino=None, nome_arquivo=None, progress=None, session=None):
                if nome_arquivo == "catalog.json":
                    path = Path(pasta_destino) / "catalog.json"
                    path.write_text(body, encoding="utf-8")
                    return SharePointResult(ok=True, path=path, message="")
                return SharePointResult(ok=False, message="links explodiu no powershell")

            with (
                patch.object(config, "CATALOG_CACHE_DIR", cache),
                patch.object(config, "CATALOG_CACHE_FILE", cache / "catalog.json"),
                patch.object(config, "CATALOG_IMAGES_DIR", cache / "images"),
                patch.object(config, "CATALOG_IMAGES_MANIFEST", cache / "images_manifest.json"),
                patch.object(config, "LINKS_FILE", links),
                patch.object(config, "LINKS_VERSION_FILE", version),
                patch("catalog.provider.baixar_do_sharepoint", side_effect=fake),
                patch("services.links.baixar_do_sharepoint", side_effect=fake),
            ):
                result = SharePointCatalogProvider(
                    "https://empresa.sharepoint.com/sites/s/catalog.json"
                ).sync()
            self.assertTrue(result.ok)
            self.assertEqual(result.message, "")
            self.assertNotIn("links", result.message.lower())
            self.assertEqual(links.read_text(encoding="utf-8"), original)
            self.assertEqual(version.read_text(encoding="utf-8"), "1")
            self.assertFalse(
                links_menu_visible(result.catalog, links_path=links, version_path=version)
            )


class PayloadTests(unittest.TestCase):
    def test_incomplete_groups_and_items_drop_out(self) -> None:
        groups = parse_links_payload(
            {
                "grupos": [
                    {
                        "titulo": "",
                        "links": [
                            {
                                "titulo": "Some",
                                "descricao": "fora",
                                "url": "https://exemplo.com/some",
                            }
                        ],
                    },
                    {"links": [{"titulo": "Sem grupo", "url": "https://exemplo.com/x"}]},
                    {"titulo": "Vazio", "links": []},
                    {
                        "titulo": "Ruim",
                        "links": [
                            {"titulo": "", "descricao": "sem titulo", "url": "https://exemplo.com/a"},
                            {"titulo": "sem url", "descricao": "falta"},
                            "texto",
                        ],
                    },
                    {
                        "titulo": "Portais",
                        "links": [
                            {
                                "titulo": "Ponto",
                                "descricao": "",
                                "url": "https://exemplo.com/ponto",
                            },
                            {
                                "titulo": "  ",
                                "descricao": "branco",
                                "url": "https://exemplo.com/branco",
                            },
                            {
                                "titulo": "Guia",
                                "descricao": "Passo a passo",
                                "url": "https://exemplo.com/guia",
                            },
                        ],
                    },
                    {
                        "titulo": "Manuais",
                        "links": [
                            {
                                "titulo": "Norma",
                                "descricao": "Texto da norma",
                                "url": "https://exemplo.com/norma",
                            }
                        ],
                    },
                ]
            }
        )
        self.assertEqual([group.titulo for group in groups], ["Portais", "Manuais"])
        self.assertEqual(
            [(item.titulo, item.descricao, item.url) for item in groups[0].links],
            [
                ("Ponto", "", "https://exemplo.com/ponto"),
                ("Guia", "Passo a passo", "https://exemplo.com/guia"),
            ],
        )
        self.assertEqual(groups[1].links[0].titulo, "Norma")

    def test_broken_document_is_invalid(self) -> None:
        with self.assertRaises(ValueError):
            parse_links_payload(["nao", "e", "objeto"])
        with self.assertRaises(ValueError):
            parse_links_payload({"links": []})
        self.assertEqual(parse_links_payload({"grupos": []}), [])

    def test_valid_file_with_zero_links_still_shows_the_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            links = root / "links.json"
            version = root / "links.versao"
            links.write_text('{"grupos": []}\n', encoding="utf-8")
            version.write_text("1", encoding="utf-8")
            catalog = CatalogData(links=LinksInfo(url="https://sp/links.json", versao="1"))
            self.assertEqual(load_local_links(links), [])
            self.assertTrue(links_menu_visible(catalog, links_path=links, version_path=version))


class PageTests(unittest.TestCase):
    def test_button_keeps_the_item_url(self) -> None:
        groups = parse_links_payload(
            {
                "grupos": [
                    {
                        "titulo": "Portais",
                        "links": [
                            {
                                "titulo": "Ponto",
                                "descricao": "Registro de ponto",
                                "url": "https://exemplo.com/ponto",
                            },
                            {
                                "titulo": "Interno",
                                "descricao": "",
                                "url": "http://exemplo.com/interno",
                            },
                        ],
                    },
                    {
                        "titulo": "Manuais",
                        "links": [
                            {
                                "titulo": "Guia",
                                "descricao": "Passo a passo",
                                "url": "https://exemplo.com/guia",
                            }
                        ],
                    },
                ]
            }
        )
        page = _Page()
        view = build_links_view(groups, page)
        buttons = _buttons(view)
        self.assertEqual(
            [button.data for button in buttons],
            [
                "https://exemplo.com/ponto",
                "http://exemplo.com/interno",
                "https://exemplo.com/guia",
            ],
        )
        self.assertEqual([group.titulo for group in groups], ["Portais", "Manuais"])
        self.assertEqual(_texts(view)[:3], ["Links", "Portais", "Ponto"])
        ponto = buttons[0]
        self.assertEqual(ponto.bgcolor, config.COLOR_SURFACE)
        title = next(node for node in _walk(ponto) if getattr(node, "value", None) == "Ponto")
        desc = next(
            node for node in _walk(ponto) if getattr(node, "value", None) == "Registro de ponto"
        )
        self.assertEqual(title.weight, ft.FontWeight.BOLD)
        self.assertEqual(desc.color, "#B9CEC3")
        ponto.on_click(None)
        self.assertEqual(page.ran, [(page, "https://exemplo.com/ponto")])
        buttons[1].on_click(None)
        self.assertEqual(len(page.ran), 1)

    def test_empty_valid_file_shows_a_short_line(self) -> None:
        view = build_links_view([], _Page())
        self.assertEqual(_texts(view), ["Links", "Nenhum link."])
        self.assertEqual(_buttons(view), [])

    def test_menu_sits_between_favorites_and_catalog(self) -> None:
        opened: list[str] = []

        def sidebar(*, show_links: bool) -> ft.Control:
            return build_sidebar(
                CatalogData(),
                home_selected=False,
                favorites_selected=False,
                selected_setor_id=None,
                selected_gerencia_id="",
                show_favorites=True,
                show_links=show_links,
                links_selected=show_links,
                on_links=lambda: opened.append("links"),
                suite_update=None,
                update_available=False,
                update_busy=False,
                update_message="",
                update_progress=None,
                update_done=False,
                update_failed=False,
                on_home=lambda: None,
                on_favorites=lambda: None,
                on_select_setor=lambda _setor: None,
                on_select_gerencia=lambda _gerencia: None,
                on_download_update=lambda: None,
                on_check_updates=lambda: None,
                check_updates_busy=False,
                start_with_windows=False,
                on_toggle_startup=lambda _value: None,
                show_startup_toggle=False,
                show_publish=True,
                on_publish=lambda: None,
            )

        hidden = sidebar(show_links=False)
        labels = [text for text in _texts(hidden) if text in {"Inicio", "Favoritos", "Links", "Catalogo"}]
        self.assertEqual(labels, ["Inicio", "Favoritos", "Catalogo"])
        self.assertFalse(any(getattr(node, "icon", None) == ft.Icons.LINK for node in _walk(hidden)))

        visible = sidebar(show_links=True)
        labels = [text for text in _texts(visible) if text in {"Inicio", "Favoritos", "Links", "Catalogo"}]
        self.assertEqual(labels, ["Inicio", "Favoritos", "Links", "Catalogo"])
        link_icons = [node for node in _walk(visible) if getattr(node, "icon", None) == ft.Icons.LINK]
        self.assertEqual(len(link_icons), 1)
        item = next(
            node
            for node in _walk(visible)
            if any(getattr(child, "value", None) == "Links" for child in _walk(node))
            and getattr(node, "on_click", None) is not None
            and getattr(node, "bgcolor", None) == config.COLOR_PRIMARY
        )
        item.on_click(None)
        self.assertEqual(opened, ["links"])


class ScreenTests(unittest.TestCase):
    def _app(self, catalog: CatalogData) -> SuiteApp:
        app = SuiteApp.__new__(SuiteApp)
        app.page = _Page()
        app.catalog = catalog
        app.view_catalog = catalog
        app.apps = list(catalog.apps)
        app.apps_by_id = {item.id: item for item in app.apps}
        app.selected_gerencia_id = ""
        app.selected_id = None
        app.selected_setor = None
        app.show_favorites = False
        app.show_links = False
        app.show_publish = False
        app.can_publish = False
        app.favorites = _Favorites()
        app.storage = _Storage()
        app.preferences = _Prefs()
        app.sidebar_holder = _Holder()
        app.content_holder = _Holder()
        app.sync_message = ""
        app.sync_notice = ""
        app.check_updates_busy = False
        app.update_busy = False
        app.update_message = ""
        app.update_progress = None
        app.update_failed = False
        app.update_done = False
        app._running_pids = {}
        app._running_cache_at = 0.0
        app._current_tip = None
        app._home_tip_balloon = None
        return app

    def test_failed_follow_up_hides_the_item_and_returns_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            links = root / "links.json"
            version = root / "links.versao"
            links.write_text(_valid_body(), encoding="utf-8")
            version.write_text("1", encoding="utf-8")
            catalog = CatalogData(links=LinksInfo(url="https://sp/links.json", versao="9"))
            app = self._app(catalog)
            app.show_links = True
            with (
                patch.object(config, "LINKS_FILE", links),
                patch.object(config, "LINKS_VERSION_FILE", version),
            ):
                SuiteApp._render(app)
            self.assertFalse(app.show_links)
            self.assertNotIn("Ponto", _texts(app.content_holder.content))
            sidebar = [
                text
                for text in _texts(app.sidebar_holder.content)
                if text in {"Inicio", "Favoritos", "Links", "Catalogo"}
            ]
            self.assertEqual(sidebar, ["Inicio"])

            version.write_text("9", encoding="utf-8")
            app.show_links = True
            with (
                patch.object(config, "LINKS_FILE", links),
                patch.object(config, "LINKS_VERSION_FILE", version),
            ):
                SuiteApp._render(app)
            self.assertTrue(app.show_links)
            self.assertIn("Ponto", _texts(app.content_holder.content))
            self.assertIn("Registro de ponto", _texts(app.content_holder.content))
            buttons = _buttons(app.content_holder.content)
            self.assertEqual(buttons[0].data, "https://exemplo.com/ponto")
            sidebar = [
                text
                for text in _texts(app.sidebar_holder.content)
                if text in {"Inicio", "Favoritos", "Links", "Catalogo"}
            ]
            self.assertEqual(sidebar, ["Inicio", "Links"])


def _rows_with_url(control, url: str) -> list:
    found = []
    for node in _walk(control):
        controls = getattr(node, "controls", None)
        if not isinstance(controls, list):
            continue
        if any(getattr(child, "data", None) == url for child in controls):
            found.append(node)
    return found


def _star_in(row) -> ft.Control:
    for child in row.controls:
        icon = getattr(child, "icon", None)
        if icon in (ft.Icons.STAR, ft.Icons.STAR_BORDER):
            return child
    raise AssertionError("estrela ausente")


class LinkFavoriteTests(unittest.TestCase):
    def test_file_sits_beside_app_favorites_and_keeps_favorite_order(self) -> None:
        self.assertEqual(config.LINK_FAVORITES_FILE.parent, config.USER_DATA_DIR)
        self.assertEqual(config.LINK_FAVORITES_FILE.parent, config.FAVORITES_FILE.parent)
        self.assertNotEqual(config.LINK_FAVORITES_FILE.name, config.FAVORITES_FILE.name)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = LinkFavoritesStore(root / "link_favorites.json")
            links = root / "links.json"
            links.write_text(_valid_body(), encoding="utf-8")
            original = links.read_text(encoding="utf-8")
            self.assertFalse(store.toggle("  "))
            self.assertTrue(store.toggle(" https://exemplo.com/guia "))
            self.assertTrue(store.toggle("https://exemplo.com/ponto"))
            self.assertEqual(
                store.list_urls(),
                ["https://exemplo.com/guia", "https://exemplo.com/ponto"],
            )
            self.assertFalse(store.toggle("https://exemplo.com/guia"))
            self.assertTrue(store.toggle("https://exemplo.com/guia"))
            self.assertEqual(
                store.list_urls(),
                ["https://exemplo.com/ponto", "https://exemplo.com/guia"],
            )
            self.assertEqual(links.read_text(encoding="utf-8"), original)
            self.assertFalse((root / "favorites.json").exists())
            again = LinkFavoritesStore(store.path)
            self.assertEqual(again.list_urls(), store.list_urls())
            store.path.write_text("{nao e json", encoding="utf-8")
            self.assertEqual(LinkFavoritesStore(store.path).list_urls(), [])

    def test_visible_favorites_follow_mark_order_and_skip_missing(self) -> None:
        groups = parse_links_payload(
            {
                "grupos": [
                    {
                        "titulo": "Portais",
                        "links": [
                            {
                                "titulo": "Ponto",
                                "descricao": "Registro de ponto",
                                "url": "https://exemplo.com/ponto",
                            }
                        ],
                    },
                    {
                        "titulo": "Manuais",
                        "links": [
                            {
                                "titulo": "Ponto de novo",
                                "descricao": "Outra ficha",
                                "url": "https://exemplo.com/ponto",
                            },
                            {
                                "titulo": "Guia",
                                "descricao": "Passo a passo",
                                "url": "https://exemplo.com/guia",
                            },
                        ],
                    },
                ]
            }
        )
        self.assertEqual(visible_favorite_links(groups, []), [])
        self.assertEqual(
            visible_favorite_links(groups, ["https://exemplo.com/sumiu", "  "]),
            [],
        )
        favorite = visible_favorite_links(
            groups,
            [
                "https://exemplo.com/sumiu",
                "https://exemplo.com/guia",
                "https://exemplo.com/ponto",
                "https://exemplo.com/guia",
            ],
        )
        self.assertEqual(
            [(item.titulo, item.url) for item in favorite],
            [
                ("Guia", "https://exemplo.com/guia"),
                ("Ponto", "https://exemplo.com/ponto"),
            ],
        )
        self.assertEqual([group.titulo for group in groups], ["Portais", "Manuais"])
        self.assertEqual(groups[1].links[0].titulo, "Ponto de novo")

    def test_star_toggles_without_opening_and_page_keeps_json_groups(self) -> None:
        groups = parse_links_payload(
            {
                "grupos": [
                    {
                        "titulo": "Portais",
                        "links": [
                            {
                                "titulo": "Ponto",
                                "descricao": "Registro de ponto",
                                "url": "https://exemplo.com/ponto",
                            }
                        ],
                    },
                    {
                        "titulo": "Manuais",
                        "links": [
                            {
                                "titulo": "Guia",
                                "descricao": "Passo a passo",
                                "url": "https://exemplo.com/guia",
                            }
                        ],
                    },
                ]
            }
        )
        page = _Page()
        toggled: list[str] = []
        view = build_links_view(
            groups,
            page,
            favorite_urls=["https://exemplo.com/guia", "https://exemplo.com/ponto"],
            on_toggle_favorite=toggled.append,
        )
        texts = _texts(view)
        self.assertEqual(texts[:3], ["Links", "Portais", "Ponto"])
        self.assertNotIn("Favoritos", texts)
        self.assertLess(texts.index("Portais"), texts.index("Manuais"))
        self.assertEqual(texts.count("Ponto"), 1)
        self.assertEqual(texts.count("Guia"), 1)
        self.assertEqual(
            [button.data for button in _buttons(view)],
            [
                "https://exemplo.com/ponto",
                "https://exemplo.com/guia",
            ],
        )
        ponto_rows = _rows_with_url(view, "https://exemplo.com/ponto")
        self.assertEqual(len(ponto_rows), 1)
        for row in ponto_rows:
            self.assertEqual(_star_in(row).icon, ft.Icons.STAR)
            self.assertEqual(_star_in(row).tooltip, "Remover dos favoritos")
        guia = _rows_with_url(view, "https://exemplo.com/guia")[0]
        _star_in(guia).on_click(None)
        self.assertEqual(toggled, ["https://exemplo.com/guia"])
        self.assertEqual(page.ran, [])
        opener = next(child for child in guia.controls if getattr(child, "data", None))
        opener.on_click(None)
        self.assertEqual(page.ran, [(page, "https://exemplo.com/guia")])
        self.assertEqual(toggled, ["https://exemplo.com/guia"])

        plain = build_links_view(groups, page, favorite_urls=["https://exemplo.com/sumiu"])
        self.assertEqual([text for text in _texts(plain) if text in {"Portais", "Manuais", "Favoritos"}], ["Portais", "Manuais"])
        self.assertEqual(_star_in(_rows_with_url(plain, "https://exemplo.com/ponto")[0]).icon, ft.Icons.STAR_BORDER)

    def test_favorites_screen_lists_links_under_apps(self) -> None:
        groups = parse_links_payload(
            {
                "grupos": [
                    {
                        "titulo": "Portais",
                        "links": [
                            {
                                "titulo": "Ponto",
                                "descricao": "Registro de ponto",
                                "url": "https://exemplo.com/ponto",
                            }
                        ],
                    },
                    {
                        "titulo": "Manuais",
                        "links": [
                            {
                                "titulo": "Guia",
                                "descricao": "Passo a passo",
                                "url": "https://exemplo.com/guia",
                            }
                        ],
                    },
                ]
            }
        )
        page = _Page()
        toggled: list[str] = []
        links = visible_favorite_links(
            groups,
            ["https://exemplo.com/sumiu", "https://exemplo.com/guia", "https://exemplo.com/ponto"],
        )
        apps = [AppInfo(id="relatorio", nome="Relatorio")]
        both = build_favoritos_view(
            apps,
            lambda _app_id: None,
            favorite_ids={"relatorio"},
            on_toggle_favorite=lambda _app_id: None,
            link_items=links,
            page=page,
            on_toggle_link=toggled.append,
        )
        texts = _texts(both)
        self.assertLess(texts.index("Aplicativos"), texts.index("Links"))
        self.assertLess(texts.index("Relatorio"), texts.index("Guia"))
        self.assertLess(texts.index("Guia"), texts.index("Ponto"))
        self.assertNotIn("sumiu", "".join(texts))
        self.assertEqual(
            [button.data for button in _buttons(both)],
            ["https://exemplo.com/guia", "https://exemplo.com/ponto"],
        )
        guia = _rows_with_url(both, "https://exemplo.com/guia")[0]
        self.assertEqual(_star_in(guia).icon, ft.Icons.STAR)
        _star_in(guia).on_click(None)
        self.assertEqual(toggled, ["https://exemplo.com/guia"])
        self.assertEqual(page.ran, [])
        opener = next(child for child in guia.controls if getattr(child, "data", None))
        opener.on_click(None)
        self.assertEqual(page.ran, [(page, "https://exemplo.com/guia")])

        only_links = build_favoritos_view(
            [],
            lambda _app_id: None,
            favorite_ids=set(),
            on_toggle_favorite=lambda _app_id: None,
            link_items=links,
            page=page,
            on_toggle_link=toggled.append,
        )
        only_texts = _texts(only_links)
        self.assertIn("Favoritos", only_texts)
        self.assertIn("Links", only_texts)
        self.assertNotIn("Aplicativos", only_texts)
        self.assertIn("Guia", only_texts)

        only_apps = build_favoritos_view(
            apps,
            lambda _app_id: None,
            favorite_ids={"relatorio"},
            on_toggle_favorite=lambda _app_id: None,
        )
        self.assertIn("Aplicativos", _texts(only_apps))
        self.assertNotIn("Links", _texts(only_apps))
        self.assertNotIn("Guia", _texts(only_apps))

    def test_render_keeps_links_json_and_returns_home_without_favorites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            links = root / "links.json"
            version = root / "links.versao"
            body = json.dumps(
                {
                    "grupos": [
                        {
                            "titulo": "Portais",
                            "links": [
                                {
                                    "titulo": "Ponto",
                                    "descricao": "Registro de ponto",
                                    "url": "https://exemplo.com/ponto",
                                }
                            ],
                        },
                        {
                            "titulo": "Manuais",
                            "links": [
                                {
                                    "titulo": "Guia",
                                    "descricao": "Passo a passo",
                                    "url": "https://exemplo.com/guia",
                                }
                            ],
                        },
                    ]
                }
            )
            links.write_text(body, encoding="utf-8")
            version.write_text("1", encoding="utf-8")
            catalog = CatalogData(links=LinksInfo(url="https://sp/links.json", versao="1"))
            app = ScreenTests()._app(catalog)
            app.show_links = True
            app.link_favorites = LinkFavoritesStore(root / "link_favorites.json")
            app.link_favorites.toggle("https://exemplo.com/guia")
            app.link_favorites.toggle("https://exemplo.com/sumiu")
            app.link_favorites.toggle("https://exemplo.com/ponto")
            def sidebar_labels() -> list[str]:
                return [
                    text
                    for text in _texts(app.sidebar_holder.content)
                    if text in {"Inicio", "Favoritos", "Links", "Catalogo"}
                ]

            with (
                patch.object(config, "LINKS_FILE", links),
                patch.object(config, "LINKS_VERSION_FILE", version),
            ):
                SuiteApp._render(app)
                shown = _texts(app.content_holder.content)
                self.assertEqual(shown[:3], ["Links", "Portais", "Ponto"])
                self.assertNotIn("Favoritos", shown)
                self.assertEqual(shown.count("Ponto"), 1)
                self.assertEqual(shown.count("Guia"), 1)
                self.assertEqual(_star_in(_rows_with_url(app.content_holder.content, "https://exemplo.com/ponto")[0]).icon, ft.Icons.STAR)
                self.assertEqual(links.read_text(encoding="utf-8"), body)

                app.show_links = False
                app.show_favorites = True
                SuiteApp._render(app)
                fav = _texts(app.content_holder.content)
                self.assertIn("Favoritos", fav)
                self.assertNotIn("Aplicativos", fav)
                self.assertLess(fav.index("Links"), fav.index("Guia"))
                self.assertLess(fav.index("Guia"), fav.index("Ponto"))
                self.assertNotIn("sumiu", "".join(fav))
                self.assertIn("Favoritos", sidebar_labels())
                self.assertTrue(app.show_favorites)

                SuiteApp._toggle_link_favorite(app, "https://exemplo.com/guia")
                self.assertTrue(app.show_favorites)
                mid = _texts(app.content_holder.content)
                self.assertIn("Ponto", mid)
                self.assertNotIn("Guia", mid)

                SuiteApp._toggle_link_favorite(app, "https://exemplo.com/ponto")
                self.assertFalse(app.show_favorites)
                home = _texts(app.content_holder.content)
                self.assertNotIn("Registro de ponto", home)
                self.assertNotIn("Favoritos", sidebar_labels())
            self.assertEqual(links.read_text(encoding="utf-8"), body)
            saved = json.loads((root / "link_favorites.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["urls"], ["https://exemplo.com/sumiu"])
            self.assertNotIn("apps", saved)

    def test_favorites_stay_while_either_apps_or_links_remain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            links = root / "links.json"
            version = root / "links.versao"
            links.write_text(_valid_body(), encoding="utf-8")
            version.write_text("1", encoding="utf-8")
            app_info = AppInfo(id="relatorio", nome="Relatorio")
            catalog = CatalogData(
                apps=[app_info],
                links=LinksInfo(url="https://sp/links.json", versao="1"),
            )
            app = ScreenTests()._app(catalog)
            app.apps = [app_info]
            app.apps_by_id = {app_info.id: app_info}
            app.view_catalog = catalog
            app.favorites = _AppFavorites(["relatorio"])
            app.link_favorites = LinkFavoritesStore(root / "link_favorites.json")
            app.link_favorites.toggle("https://exemplo.com/ponto")
            app.show_favorites = True
            with (
                patch.object(config, "LINKS_FILE", links),
                patch.object(config, "LINKS_VERSION_FILE", version),
            ):
                SuiteApp._render(app)
                texts = _texts(app.content_holder.content)
                self.assertLess(texts.index("Aplicativos"), texts.index("Links"))
                self.assertLess(texts.index("Relatorio"), texts.index("Ponto"))
                SuiteApp._toggle_link_favorite(app, "https://exemplo.com/ponto")
                self.assertTrue(app.show_favorites)
                after_link = _texts(app.content_holder.content)
                self.assertIn("Aplicativos", after_link)
                self.assertIn("Relatorio", after_link)
                self.assertNotIn("Links", after_link)
                self.assertNotIn("Ponto", after_link)
                SuiteApp._toggle_favorite(app, "relatorio")
                self.assertFalse(app.show_favorites)
                self.assertNotIn(
                    "Favoritos",
                    [
                        text
                        for text in _texts(app.sidebar_holder.content)
                        if text in {"Inicio", "Favoritos", "Links", "Catalogo"}
                    ],
                )


def _order_button(control):
    for node in _walk(control):
        if getattr(node, "content", None) == "Ordenar favoritos":
            return node
    raise AssertionError("botao Ordenar favoritos ausente")


def _drag_targets(control, group: str | None = None) -> list:
    found = []
    for node in _walk(control):
        if not isinstance(node, ft.DragTarget):
            continue
        if group is not None and node.group != group:
            continue
        found.append(node)
    return found


def _drop_on(control, group: str, src: str, dst: str) -> None:
    for target in _drag_targets(control, group):
        if getattr(getattr(target, "content", None), "data", None) != dst:
            continue
        source = type("Src", (), {"data": src})()
        target.on_accept(type("Event", (), {"src": source})())
        return
    raise AssertionError(f"alvo {dst} ausente em {group}")


class FavoriteOrderTests(unittest.TestCase):
    def test_move_keeps_each_list_and_ignores_a_short_section(self) -> None:
        self.assertIsNone(move_before(["so"], "so", "so"))
        self.assertIsNone(move_before(["a", "b"], "a", "a"))
        self.assertIsNone(move_before(["a", "b"], "link", "a"))
        self.assertEqual(move_before(["a", "b", "c"], "c", "a"), ["c", "a", "b"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apps = FavoritesStore(root / "favorites.json")
            links = LinkFavoritesStore(root / "link_favorites.json")
            apps.toggle("oculto")
            apps.toggle("beta")
            apps.toggle("alfa")
            before = apps.path.read_text(encoding="utf-8")
            self.assertFalse(apps.move_visible("beta", "alfa", ["beta"]))
            self.assertEqual(apps.path.read_text(encoding="utf-8"), before)
            self.assertFalse(apps.move_visible("https://exemplo.com/guia", "beta", ["oculto", "beta", "alfa"]))
            self.assertTrue(apps.move_visible("alfa", "beta", ["beta", "alfa"]))
            self.assertEqual(apps.list_ids(), ["oculto", "alfa", "beta"])
            apps.toggle("gama")
            self.assertEqual(apps.list_ids(), ["oculto", "alfa", "beta", "gama"])
            apps.toggle("beta")
            self.assertEqual(apps.list_ids(), ["oculto", "alfa", "gama"])

            links.toggle("https://exemplo.com/sumiu")
            links.toggle("https://exemplo.com/guia")
            links.toggle("https://exemplo.com/ponto")
            self.assertTrue(
                links.move_visible(
                    "https://exemplo.com/ponto",
                    "https://exemplo.com/guia",
                    ["https://exemplo.com/guia", "https://exemplo.com/ponto"],
                )
            )
            self.assertEqual(
                links.list_urls(),
                [
                    "https://exemplo.com/sumiu",
                    "https://exemplo.com/ponto",
                    "https://exemplo.com/guia",
                ],
            )
            self.assertFalse((root / "links.json").exists())

    def test_order_mode_drags_inside_the_section_and_saves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            links = root / "links.json"
            version = root / "links.versao"
            links.write_text(
                json.dumps(
                    {
                        "grupos": [
                            {
                                "titulo": "Portais",
                                "links": [
                                    {
                                        "titulo": "Ponto",
                                        "descricao": "Registro de ponto",
                                        "url": "https://exemplo.com/ponto",
                                    },
                                    {
                                        "titulo": "Guia",
                                        "descricao": "Passo a passo",
                                        "url": "https://exemplo.com/guia",
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            version.write_text("1", encoding="utf-8")
            catalog = CatalogData(
                apps=[
                    AppInfo(id="alfa", nome="Alfa"),
                    AppInfo(id="beta", nome="Beta"),
                ],
                links=LinksInfo(url="https://sp/links.json", versao="1"),
            )
            app = ScreenTests()._app(catalog)
            app.apps = list(catalog.apps)
            app.apps_by_id = {item.id: item for item in app.apps}
            app.view_catalog = catalog
            app.favorites = FavoritesStore(root / "favorites.json")
            app.favorites.toggle("beta")
            app.favorites.toggle("alfa")
            app.link_favorites = LinkFavoritesStore(root / "link_favorites.json")
            app.link_favorites.toggle("https://exemplo.com/sumiu")
            app.link_favorites.toggle("https://exemplo.com/guia")
            app.link_favorites.toggle("https://exemplo.com/ponto")
            app.show_favorites = True
            with (
                patch.object(config, "LINKS_FILE", links),
                patch.object(config, "LINKS_VERSION_FILE", version),
            ):
                SuiteApp._render(app)
                button = _order_button(app.content_holder.content)
                self.assertEqual(button.data, "idle")
                self.assertEqual(_drag_targets(app.content_holder.content), [])
                texts = _texts(app.content_holder.content)
                self.assertLess(texts.index("Aplicativos"), texts.index("Links"))
                self.assertLess(texts.index("Beta"), texts.index("Alfa"))
                self.assertLess(texts.index("Guia"), texts.index("Ponto"))

                button.on_click(None)
                self.assertTrue(app.ordering_favorites)
                active = _order_button(app.content_holder.content)
                self.assertEqual(active.data, "active")
                self.assertEqual(active.style.bgcolor, config.COLOR_ACCENT)
                self.assertEqual(
                    {node.group for node in _drag_targets(app.content_holder.content)},
                    {"favorite-apps", "favorite-links"},
                )
                self.assertEqual(len(_drag_targets(app.content_holder.content, "favorite-apps")), 2)
                self.assertEqual(len(_drag_targets(app.content_holder.content, "favorite-links")), 2)
                guia = next(button for button in _buttons(app.content_holder.content) if button.data == "https://exemplo.com/guia")
                guia.on_click(None)
                self.assertEqual(app.page.ran, [])

                _drop_on(app.content_holder.content, "favorite-links", "https://exemplo.com/ponto", "https://exemplo.com/guia")
                self.assertTrue(app.ordering_favorites)
                ordered = _texts(app.content_holder.content)
                self.assertLess(ordered.index("Ponto"), ordered.index("Guia"))
                self.assertNotIn("sumiu", "".join(ordered))
                self.assertEqual(
                    app.link_favorites.list_urls(),
                    [
                        "https://exemplo.com/sumiu",
                        "https://exemplo.com/ponto",
                        "https://exemplo.com/guia",
                    ],
                )
                _drop_on(app.content_holder.content, "favorite-apps", "alfa", "beta")
                self.assertEqual(app.favorites.list_ids(), ["alfa", "beta"])
                self.assertLess(_texts(app.content_holder.content).index("Alfa"), _texts(app.content_holder.content).index("Beta"))
                self.assertTrue(app.ordering_favorites)

                SuiteApp._reorder_favorite_app(app, "https://exemplo.com/ponto", "alfa")
                self.assertEqual(app.favorites.list_ids(), ["alfa", "beta"])
                self.assertEqual(
                    app.link_favorites.list_urls()[0],
                    "https://exemplo.com/sumiu",
                )

                _order_button(app.content_holder.content).on_click(None)
                self.assertFalse(app.ordering_favorites)
                idle = _order_button(app.content_holder.content)
                self.assertEqual(idle.data, "idle")
                self.assertEqual(_drag_targets(app.content_holder.content), [])
                self.assertEqual(app.favorites.list_ids(), ["alfa", "beta"])
                self.assertEqual(
                    app.link_favorites.list_urls(),
                    [
                        "https://exemplo.com/sumiu",
                        "https://exemplo.com/ponto",
                        "https://exemplo.com/guia",
                    ],
                )
                opener = next(button for button in _buttons(app.content_holder.content) if button.data == "https://exemplo.com/ponto")
                opener.on_click(None)
                self.assertEqual(app.page.ran, [(app.page, "https://exemplo.com/ponto")])

                page_links = build_links_view(
                    load_local_links(),
                    app.page,
                    favorite_urls=app.link_favorites.list_urls(),
                    on_toggle_favorite=app._toggle_link_favorite,
                )
                self.assertFalse(any(getattr(node, "content", None) == "Ordenar favoritos" for node in _walk(page_links)))
                self.assertEqual(_drag_targets(page_links), [])
                self.assertEqual(_texts(page_links)[:2], ["Links", "Portais"])


class _AppFavorites:
    def __init__(self, ids: list[str]) -> None:
        self.ids = list(ids)

    def list_ids(self) -> list[str]:
        return list(self.ids)

    def toggle(self, app_id: str) -> bool:
        if app_id in self.ids:
            self.ids = [item for item in self.ids if item != app_id]
            return False
        self.ids.append(app_id)
        return True


if __name__ == "__main__":
    unittest.main()
