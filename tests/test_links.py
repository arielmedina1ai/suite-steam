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
from services.favorites import (
    HOLD_SECONDS,
    FavoritesStore,
    card_hit_index,
    grid_insertion_index,
    insertion_index,
    layout_slots,
    order_after_drop,
)
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


def _parents(root):
    parents = {}

    def visit(node, parent):
        parents[id(node)] = parent
        content = getattr(node, "content", None)
        if content is not None and not isinstance(content, str):
            visit(content, node)
        controls = getattr(node, "controls", None)
        if isinstance(controls, (list, tuple)):
            for child in controls:
                visit(child, node)

    visit(root, None)
    return parents


def _up(parents, node):
    chain = []
    while node is not None:
        chain.append(node)
        node = parents.get(id(node))
    return chain


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
        self.assertFalse(any(getattr(node, "content", None) == "Ordenar favoritos" for node in _walk(both)))
        self.assertFalse(any(isinstance(node, ft.DragTarget) or isinstance(node, ft.Draggable) for node in _walk(both)))
        self.assertNotIsInstance(both._hold_links.control(), ft.GestureDetector)
        self.assertNotIsInstance(both._hold_apps.control(), ft.GestureDetector)
        self.assertFalse(any(isinstance(child, ft.GestureDetector) for child in both._hold_apps.control().controls))
        self.assertFalse(any(isinstance(child, ft.GestureDetector) for child in both._hold_links.control().controls))
        parents = _parents(both)
        for label in ("Relatorio", "Guia", "Ponto"):
            text = next(node for node in _walk(both) if getattr(node, "value", None) == label)
            chain = _up(parents, text)
            surface = next(
                node
                for node in chain
                if getattr(node, "ink", False) and getattr(node, "on_tap_down", None) is not None
            )
            between = chain[: chain.index(surface)]
            self.assertFalse(any(isinstance(node, ft.GestureDetector) for node in between))
            above = chain[chain.index(surface) + 1 :]
            self.assertTrue(any(isinstance(node, ft.GestureDetector) for node in above))
            self.assertFalse(
                any(
                    getattr(node, "icon", None) in (ft.Icons.STAR, ft.Icons.STAR_BORDER)
                    for node in _walk(surface)
                )
            )
        self.assertIn("1 aplicativo(s) e 2 link(s) favorito(s)", texts)
        guia = _rows_with_url(both, "https://exemplo.com/guia")[0]
        self.assertEqual(_star_in(guia).icon, ft.Icons.STAR)
        _star_in(guia).on_click(None)
        self.assertEqual(toggled, ["https://exemplo.com/guia"])
        self.assertEqual(page.ran, [])
        both._hold_links.press("https://exemplo.com/guia", 0.0, x=8, y=20)
        self.assertEqual(both._hold_links.release(0.4), "click")
        self.assertEqual(page.ran, [(page, "https://exemplo.com/guia")])
        self.assertFalse(both._hold_links.armed)

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
        self.assertIn("2 link(s) favorito(s)", only_texts)
        self.assertNotIn("aplicativo(s)", "".join(only_texts))
        self.assertIn("Guia", only_texts)

        only_apps = build_favoritos_view(
            apps,
            lambda _app_id: None,
            favorite_ids={"relatorio"},
            on_toggle_favorite=lambda _app_id: None,
        )
        app_texts = _texts(only_apps)
        self.assertIn("Aplicativos", app_texts)
        self.assertIn("1 aplicativo(s) favorito(s)", app_texts)
        self.assertNotIn("link(s)", "".join(app_texts))
        self.assertNotIn("Links", app_texts)
        self.assertNotIn("Guia", app_texts)

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


class FavoriteOrderTests(unittest.TestCase):
    def test_insertion_index_picks_the_nearest_slot(self) -> None:
        self.assertEqual(HOLD_SECONDS, 0.5)
        size, spacing = 84.0, 8.0
        self.assertEqual(insertion_index(42, count=3, size=size, spacing=spacing), 0)
        self.assertEqual(insertion_index(134, count=3, size=size, spacing=spacing), 1)
        self.assertEqual(insertion_index(226, count=3, size=size, spacing=spacing), 2)
        self.assertEqual(insertion_index(-80, count=3, size=size, spacing=spacing), 0)
        self.assertEqual(insertion_index(900, count=3, size=size, spacing=spacing), 2)
        self.assertEqual(insertion_index(70, count=3, size=size, spacing=spacing), 0)
        self.assertEqual(insertion_index(110, count=3, size=size, spacing=spacing), 1)
        self.assertEqual(
            grid_insertion_index(
                130, 115, count=3, columns=2, card_w=260, card_h=230, spacing_x=16, spacing_y=16
            ),
            0,
        )
        self.assertEqual(
            grid_insertion_index(
                406, 115, count=3, columns=2, card_w=260, card_h=230, spacing_x=16, spacing_y=16
            ),
            1,
        )
        self.assertEqual(
            grid_insertion_index(
                130, 361, count=3, columns=2, card_w=260, card_h=230, spacing_x=16, spacing_y=16
            ),
            2,
        )
        self.assertEqual(
            grid_insertion_index(
                -40, -40, count=3, columns=2, card_w=260, card_h=230, spacing_x=16, spacing_y=16
            ),
            0,
        )
        self.assertEqual(
            grid_insertion_index(
                2000, 2000, count=3, columns=2, card_w=260, card_h=230, spacing_x=16, spacing_y=16
            ),
            2,
        )

    def test_click_on_the_empty_end_of_the_row_selects_nothing(self) -> None:
        from ui.favorite_hold import HoldSection

        common = dict(count=5, columns=3, card_w=260, card_h=230, spacing_x=16, spacing_y=16)
        self.assertEqual(card_hit_index(10, 10, **common), 0)
        self.assertEqual(card_hit_index(10, 230 + 16 + 10, **common), 3)
        self.assertEqual(card_hit_index(260 + 16 + 10, 230 + 16 + 10, **common), 4)
        self.assertIsNone(card_hit_index(2 * (260 + 16) + 10, 230 + 16 + 10, **common))
        self.assertIsNone(card_hit_index(260 + 4, 20, **common))

        opened: list[str] = []
        section = HoldSection(
            ["a", "b", "c", "d", "e"],
            axis="grid",
            card_w=260,
            card_h=230,
            spacing_x=16,
            spacing_y=16,
            columns=3,
            build_card=lambda key: ft.Text(key),
            on_open=opened.append,
            on_drop=lambda _key, _index: None,
        )
        self.assertIsNone(section.pointer_down_at(2 * (260 + 16) + 10, 230 + 16 + 10, 0.0))
        self.assertIsNone(section.key)
        self.assertEqual(section.release(0.2), "cancel")
        self.assertEqual(opened, [])
        self.assertEqual(section.pointer_down_at(10, 230 + 16 + 8, 1.0), "d")
        self.assertEqual(section.release(1.2), "click")
        self.assertEqual(opened, ["d"])

    def test_drop_saves_the_section_order_and_keeps_the_other_list(self) -> None:
        self.assertIsNone(order_after_drop(["so"], "so", 0))
        self.assertIsNone(order_after_drop(["a", "b"], "link", 0))
        self.assertIsNone(order_after_drop(["a", "b", "c"], "b", 1))
        self.assertEqual(order_after_drop(["a", "b", "c"], "c", 0), ["c", "a", "b"])
        self.assertEqual(order_after_drop(["a", "b", "c"], "a", 2), ["b", "c", "a"])
        self.assertEqual(
            layout_slots(["a", "b", "c"], "c", 0),
            [("gap", "c"), ("card", "a"), ("card", "b")],
        )
        self.assertEqual(layout_slots(["a", "b", "c"], None, None), [("card", "a"), ("card", "b"), ("card", "c")])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            apps = FavoritesStore(root / "favorites.json")
            links = LinkFavoritesStore(root / "link_favorites.json")
            apps.toggle("oculto")
            apps.toggle("beta")
            apps.toggle("alfa")
            before = apps.path.read_text(encoding="utf-8")
            self.assertFalse(apps.move_to_index("beta", 0, ["beta"]))
            self.assertEqual(apps.path.read_text(encoding="utf-8"), before)
            self.assertFalse(apps.move_to_index("https://exemplo.com/guia", 0, ["beta", "alfa"]))
            self.assertTrue(apps.move_to_index("alfa", 0, ["beta", "alfa"]))
            self.assertEqual(apps.list_ids(), ["oculto", "alfa", "beta"])
            apps.toggle("gama")
            self.assertEqual(apps.list_ids(), ["oculto", "alfa", "beta", "gama"])
            apps.toggle("beta")
            self.assertEqual(apps.list_ids(), ["oculto", "alfa", "gama"])

            links.toggle("https://exemplo.com/sumiu")
            links.toggle("https://exemplo.com/guia")
            links.toggle("https://exemplo.com/ponto")
            self.assertTrue(
                links.move_to_index(
                    "https://exemplo.com/ponto",
                    0,
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

    def test_hold_opens_a_gap_and_saves_when_released(self) -> None:
        from ui.favorite_hold import HoldSection

        dropped: list[tuple[str, int]] = []
        opened: list[str] = []
        section = HoldSection(
            ["guia", "ponto", "norma"],
            axis="line",
            card_w=640,
            card_h=84,
            spacing_x=0,
            spacing_y=8,
            columns=1,
            build_card=lambda key: ft.Text(key),
            on_open=opened.append,
            on_drop=lambda key, index: dropped.append((key, index)),
        )
        self.assertIsNotNone(section.floater.content)
        self.assertEqual(section.floater.height, 84)
        self.assertEqual(section.floater.opacity, 0)
        self.assertTrue(section.floater.visible)
        self.assertEqual(section.gap.height, 84)
        self.assertEqual(section.gap.opacity, 0)
        self.assertIsNone(section.gap.data)
        self.assertIn(section.gap, section.visual.controls)
        self.assertEqual(section.visual_host.opacity, 0)
        self.assertTrue(section.visual_host.visible)
        self.assertEqual(section.flow.on_size_change, section._resized)
        warm_gap = section.gap
        warm_floater = section.floater.content
        warm_cards = dict(section.visual_cards)
        section.press("ponto", 0.0, x=10, y=134)
        self.assertEqual(section.release(0.4), "click")
        self.assertEqual(opened, ["ponto"])
        self.assertEqual(dropped, [])
        self.assertFalse(section.armed)
        self.assertFalse(any(getattr(node, "data", None) == "reorder-gap" for node in _walk(section.control())))

        section.press("ponto", 10.0, x=10, y=134)
        self.assertFalse(section.advance(10.4))
        self.assertTrue(section.advance(10.5))
        self.assertTrue(section.armed)
        gap = next(node for node in _walk(section.control()) if getattr(node, "data", None) == "reorder-gap")
        self.assertEqual(gap.border.top.color, config.COLOR_ACCENT)
        self.assertIsNone(gap.content)
        self.assertEqual(gap.height, 84)
        self.assertIs(gap, warm_gap)
        self.assertIs(section.floater.content, warm_floater)
        self.assertEqual(section.visual_cards, warm_cards)
        self.assertEqual(section._float_faces["ponto"].opacity, 1)
        self.assertEqual(section._float_faces["guia"].opacity, 0)
        self.assertIn(gap, section.visual.controls)
        self.assertNotIn(gap, section.flow.controls)
        self.assertTrue(section.visual_host.ignore_interactions)
        self.assertEqual(section.visual_host.opacity, 1)
        self.assertEqual(section.floater.opacity, 1)
        self.assertEqual(section.flow.opacity, 0)
        detector = section.cards["ponto"].content
        self.assertIsInstance(detector, ft.GestureDetector)
        mounted = list(section.flow.controls)
        self.assertEqual(mounted, [section.cards[key] for key in ("guia", "ponto", "norma")])
        floater = next(node for node in _walk(section.control()) if getattr(node, "data", None) == "reorder-float")
        self.assertTrue(floater.visible)
        self.assertEqual(floater.scale, 1.04)
        self.assertIsNotNone(floater.shadow)
        self.assertEqual(section.move(10, -40), 0)
        self.assertEqual(
            layout_slots(section.keys, "ponto", section.index)[0],
            ("gap", "ponto"),
        )
        self.assertEqual(
            [getattr(node, "data", None) for node in section.visual.controls],
            ["reorder-gap", None, None],
        )
        self.assertIs(section.cards["ponto"].content, detector)
        self.assertEqual(list(section.flow.controls), mounted)
        self.assertTrue(section.armed)
        self.assertEqual(floater.top, -40 - 84 / 2)
        self.assertEqual(dropped, [])
        section._resized(type("Size", (), {"width": 700.0})())
        self.assertEqual(section.card_w, 700.0)
        self.assertEqual(section.floater.width, 700.0)
        self.assertTrue(section.armed)
        self.assertIs(section.cards["ponto"].content, detector)
        self.assertEqual(list(section.flow.controls), mounted)
        self.assertEqual(dropped, [])
        self.assertEqual(section.move(10, 900), 2)
        self.assertEqual(
            [getattr(node, "data", None) for node in section.visual.controls],
            [None, None, "reorder-gap"],
        )
        self.assertIs(section.cards["ponto"].content, detector)
        self.assertEqual(list(section.flow.controls), mounted)
        self.assertTrue(section.armed)
        self.assertTrue(floater.visible)
        self.assertEqual(floater.top, 900 - 84 / 2)
        self.assertEqual(dropped, [])
        self.assertEqual(section.release(12.0, x=10, y=900), "drop")
        self.assertEqual(dropped, [("ponto", 2)])
        self.assertFalse(section.armed)
        self.assertEqual(floater.opacity, 0)
        self.assertTrue(floater.visible)
        self.assertEqual(section.flow.opacity, 1)
        self.assertEqual(section.visual_host.opacity, 0)
        self.assertTrue(section.visual_host.visible)
        self.assertIs(section.gap, warm_gap)
        self.assertEqual(section.cards["ponto"]._hold_face.opacity, 1)
        self.assertFalse(any(getattr(node, "data", None) == "reorder-gap" for node in _walk(section.control())))
        self.assertEqual(section.release(13.0), "cancel")

        section.press("guia", 30.0, x=10, y=10)
        self.assertTrue(section.advance(30.5))
        self.assertEqual(floater.opacity, 1)
        self.assertIn(section.cards["guia"], section.flow.controls)
        section._card_pan_cancel("guia")
        self.assertEqual(dropped[-1], ("guia", 0))
        self.assertFalse(section.armed)
        self.assertEqual(floater.opacity, 0)
        self.assertEqual(section.cards["guia"]._hold_face.opacity, 1)
        self.assertFalse(any(getattr(node, "data", None) == "reorder-gap" for node in _walk(section.control())))

        alone = HoldSection(
            ["so"],
            axis="line",
            card_w=100,
            card_h=40,
            spacing_x=0,
            spacing_y=8,
            columns=1,
            build_card=lambda key: ft.Text(key),
            on_open=opened.append,
            on_drop=lambda key, index: dropped.append((key, index)),
        )
        alone.press("so", 0.0, y=10)
        self.assertFalse(alone.advance(2.0))
        self.assertEqual(alone.release(2.1), "cancel")
        self.assertEqual(dropped, [("ponto", 2), ("guia", 0)])

        grid = HoldSection(
            ["a", "b", "c", "d"],
            axis="grid",
            card_w=260,
            card_h=230,
            spacing_x=16,
            spacing_y=16,
            columns=3,
            build_card=lambda key: ft.Text(key),
            on_open=lambda _key: None,
            on_drop=lambda _key, _index: None,
        )
        grid_detector = grid.cards["a"].content
        grid_mounted = list(grid.flow.controls)
        grid._resized(type("Size", (), {"width": 500.0})())
        self.assertEqual(grid.columns, 1)
        self.assertEqual(grid.gap.height, 230)
        self.assertIs(grid.cards["a"].content, grid_detector)
        self.assertEqual(list(grid.flow.controls), grid_mounted)

    def test_release_on_the_favorites_screen_saves_and_clears_the_gesture(self) -> None:
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
                view = app.content_holder.content
                self.assertFalse(any(getattr(node, "content", None) == "Ordenar favoritos" for node in _walk(view)))
                self.assertFalse(any(isinstance(node, (ft.DragTarget, ft.Draggable)) for node in _walk(view)))
                texts = _texts(view)
                self.assertLess(texts.index("Aplicativos"), texts.index("Links"))
                self.assertLess(texts.index("Beta"), texts.index("Alfa"))
                self.assertLess(texts.index("Guia"), texts.index("Ponto"))

                links_hold = view._hold_links
                self.assertEqual(links_hold.release(0.2), "cancel")
                links_hold.press("https://exemplo.com/ponto", 0.0, x=8, y=134)
                self.assertEqual(links_hold.release(0.3), "click")
                self.assertEqual(app.page.ran, [(app.page, "https://exemplo.com/ponto")])
                self.assertEqual(
                    app.link_favorites.list_urls(),
                    [
                        "https://exemplo.com/sumiu",
                        "https://exemplo.com/guia",
                        "https://exemplo.com/ponto",
                    ],
                )

                links_hold.press("https://exemplo.com/ponto", 5.0, x=8, y=134)
                self.assertTrue(links_hold.advance(6.0))
                self.assertEqual(links_hold.move(8, -20), 0)
                self.assertEqual(links_hold.release(6.4, x=8, y=-20), "drop")
                self.assertFalse(links_hold.armed)
                self.assertEqual(
                    app.link_favorites.list_urls(),
                    [
                        "https://exemplo.com/sumiu",
                        "https://exemplo.com/ponto",
                        "https://exemplo.com/guia",
                    ],
                )
                self.assertLess(_texts(app.content_holder.content).index("Ponto"), _texts(app.content_holder.content).index("Guia"))
                self.assertEqual(app.favorites.list_ids(), ["beta", "alfa"])

                apps_hold = app.content_holder.content._hold_apps
                apps_hold.press("alfa", 20.0, x=406, y=115)
                self.assertTrue(apps_hold.advance(21.0))
                self.assertEqual(apps_hold.move(130, 115), 0)
                self.assertEqual(apps_hold.release(21.2), "drop")
                self.assertEqual(app.favorites.list_ids(), ["alfa", "beta"])
                self.assertFalse(apps_hold.armed)
                SuiteApp._reorder_favorite_app_to(app, "https://exemplo.com/ponto", 0)
                self.assertEqual(app.favorites.list_ids(), ["alfa", "beta"])
                self.assertEqual(app.link_favorites.list_urls()[0], "https://exemplo.com/sumiu")

                page_links = build_links_view(
                    load_local_links(),
                    app.page,
                    favorite_urls=app.link_favorites.list_urls(),
                    on_toggle_favorite=app._toggle_link_favorite,
                )
                self.assertFalse(any(getattr(node, "content", None) == "Ordenar favoritos" for node in _walk(page_links)))
                self.assertFalse(any(isinstance(node, (ft.DragTarget, ft.Draggable)) for node in _walk(page_links)))
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
