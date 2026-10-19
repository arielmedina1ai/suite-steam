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
    CatalogData,
    LinksInfo,
    parse_catalog_dict,
    parse_links_payload,
)
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


if __name__ == "__main__":
    unittest.main()
