"""Versao das dicas, falha silenciosa, ciclo do balao e o save."""
from __future__ import annotations

import asyncio
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
from models import CatalogData, Dica, DicasInfo, parse_catalog_dict
from services.catalog_publish import PublishOutcome, _upload_tips_document, save_dicas
from services.sharepoint_manager import SharePointResult
from main import SuiteApp
from services.tips import (
    TIP_ROTATE_SECONDS,
    DicasFormState,
    TipCycle,
    publish_dicas_block,
    should_download_tips,
    sync_tips,
    tip_text_pieces,
)
from ui.home_view import apply_tip, build_home, tip_balloon
from ui.dicas_view import bind_dicas_form


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
        content = getattr(node, "content", None)
        if isinstance(content, str) and content:
            found.append(content)
    return found


class _Result:
    def __init__(self, ok: bool, path: Path | None = None) -> None:
        self.ok = ok
        self.path = path
        self.message = "" if ok else "falhou"


class VersionCompareTests(unittest.TestCase):
    def test_missing_url_or_version_does_not_download(self) -> None:
        self.assertFalse(
            should_download_tips(url="", versao="1", saved_versao="", local_exists=False)
        )
        self.assertFalse(
            should_download_tips(
                url="https://empresa.sharepoint.com/tips.json",
                versao="",
                saved_versao="",
                local_exists=False,
            )
        )

    def test_same_version_with_local_file_skips(self) -> None:
        self.assertFalse(
            should_download_tips(
                url="https://empresa.sharepoint.com/tips.json",
                versao="2",
                saved_versao="2",
                local_exists=True,
            )
        )

    def test_same_version_without_file_downloads(self) -> None:
        self.assertTrue(
            should_download_tips(
                url="https://empresa.sharepoint.com/tips.json",
                versao="2",
                saved_versao="2",
                local_exists=False,
            )
        )

    def test_different_version_downloads(self) -> None:
        self.assertTrue(
            should_download_tips(
                url="https://empresa.sharepoint.com/tips.json",
                versao="3",
                saved_versao="2",
                local_exists=True,
            )
        )

    def test_old_catalog_without_dicas_still_parses(self) -> None:
        catalog = parse_catalog_dict({"apps": [{"id": "a", "nome": "A"}]})
        self.assertEqual(catalog.apps[0].id, "a")
        self.assertEqual(catalog.dicas, DicasInfo())
        self.assertFalse(catalog.dicas.configured)

    def test_sync_skips_equal_version_and_updates_only_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tips = root / "tips.json"
            version = root / "tips.versao"
            tips.write_text(
                json.dumps({"dicas": [{"titulo": "Velha", "texto": "fica"}]}),
                encoding="utf-8",
            )
            version.write_text("2", encoding="utf-8")
            calls: list[str] = []

            def download(url: str, dest: Path) -> _Result:
                calls.append(url)
                dest.write_text(
                    json.dumps({"dicas": [{"titulo": "Nova", "texto": "ok"}]}),
                    encoding="utf-8",
                )
                return _Result(True, dest)

            same = CatalogData(dicas=DicasInfo(url="https://sp/tips.json", versao="2"))
            self.assertEqual(
                sync_tips(same, download=download, tips_path=tips, version_path=version),
                "skipped",
            )
            self.assertEqual(calls, [])
            self.assertIn("Velha", tips.read_text(encoding="utf-8"))

            changed = CatalogData(dicas=DicasInfo(url="https://sp/tips.json", versao="3"))
            self.assertEqual(
                sync_tips(changed, download=download, tips_path=tips, version_path=version),
                "downloaded",
            )
            self.assertEqual(calls, ["https://sp/tips.json"])
            self.assertIn("Nova", tips.read_text(encoding="utf-8"))
            self.assertEqual(version.read_text(encoding="utf-8"), "3")


class SilentFailureTests(unittest.TestCase):
    def test_download_failure_keeps_previous_copy_and_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tips = root / "tips.json"
            version = root / "tips.versao"
            original = '{"dicas":[{"titulo":"Antiga","texto":"fica"}]}'
            tips.write_text(original, encoding="utf-8")
            version.write_text("1", encoding="utf-8")

            def boom(url: str, dest: Path) -> _Result:
                dest.write_text("lixo", encoding="utf-8")
                raise RuntimeError("rede caiu")

            catalog = CatalogData(dicas=DicasInfo(url="https://sp/tips.json", versao="4"))
            self.assertEqual(
                sync_tips(catalog, download=boom, tips_path=tips, version_path=version),
                "failed",
            )
            self.assertEqual(tips.read_text(encoding="utf-8"), original)
            self.assertEqual(version.read_text(encoding="utf-8"), "1")
            self.assertFalse((root / "tips.json.partial").exists())

    def test_invalid_payload_does_not_replace_or_bump(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tips = root / "tips.json"
            version = root / "tips.versao"
            tips.write_text('{"dicas":[{"titulo":"Antiga","texto":"fica"}]}', encoding="utf-8")
            version.write_text("1", encoding="utf-8")

            def bad(url: str, dest: Path) -> _Result:
                dest.write_text("<html>nao</html>", encoding="utf-8")
                return _Result(True, dest)

            catalog = CatalogData(dicas=DicasInfo(url="https://sp/tips.json", versao="9"))
            self.assertEqual(
                sync_tips(catalog, download=bad, tips_path=tips, version_path=version),
                "failed",
            )
            self.assertIn("Antiga", tips.read_text(encoding="utf-8"))
            self.assertEqual(version.read_text(encoding="utf-8"), "1")

    def test_provider_sync_stays_quiet_when_tips_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "catalog"
            cache.mkdir()
            (cache / "images").mkdir()
            tips = cache / "tips.json"
            version = cache / "tips.versao"
            tips.write_text('{"dicas":[{"titulo":"Antiga","texto":"fica"}]}', encoding="utf-8")
            version.write_text("1", encoding="utf-8")
            body = json.dumps(
                {
                    "apps": [],
                    "dicas": {
                        "url": "https://empresa.sharepoint.com/sites/s/tips.json",
                        "versao": "2",
                    },
                }
            )

            def fake(link, pasta_destino=None, nome_arquivo=None, progress=None, session=None):
                if nome_arquivo == "catalog.json":
                    path = Path(pasta_destino) / "catalog.json"
                    path.write_text(body, encoding="utf-8")
                    return SharePointResult(ok=True, path=path, message="")
                return SharePointResult(ok=False, message="tips explodiu no powershell")

            with (
                patch.object(config, "CATALOG_CACHE_DIR", cache),
                patch.object(config, "CATALOG_CACHE_FILE", cache / "catalog.json"),
                patch.object(config, "CATALOG_IMAGES_DIR", cache / "images"),
                patch.object(config, "CATALOG_IMAGES_MANIFEST", cache / "images_manifest.json"),
                patch.object(config, "TIPS_FILE", tips),
                patch.object(config, "TIPS_VERSION_FILE", version),
                patch("catalog.provider.baixar_do_sharepoint", side_effect=fake),
                patch("services.tips.baixar_do_sharepoint", side_effect=fake),
            ):
                result = SharePointCatalogProvider(
                    "https://empresa.sharepoint.com/sites/s/catalog.json"
                ).sync()
            self.assertTrue(result.ok)
            self.assertEqual(result.message, "")
            self.assertNotIn("tips", result.message.lower())
            self.assertNotIn("explodiu", result.message.lower())
            self.assertIn("Antiga", tips.read_text(encoding="utf-8"))
            self.assertEqual(version.read_text(encoding="utf-8"), "1")


class ShuffleCycleTests(unittest.TestCase):
    def test_no_repeat_until_the_cycle_ends_then_a_new_order(self) -> None:
        class Order:
            def __init__(self) -> None:
                self.calls = 0

            def shuffle(self, seq) -> None:
                self.calls += 1
                if self.calls == 1:
                    seq.sort(key=lambda item: item.titulo)
                else:
                    seq.sort(key=lambda item: item.titulo, reverse=True)

        tips = [Dica("b", "2"), Dica("a", "1"), Dica("c", "3")]
        cycle = TipCycle(tips, rng=Order())
        first = []
        for index in range(3):
            current = cycle.current()
            self.assertIsNotNone(current)
            first.append(current.titulo)
            if index < 2:
                cycle.advance()
        self.assertEqual(first, ["a", "b", "c"])
        self.assertEqual(len(set(first)), 3)
        cycle.advance()
        second = [cycle.current().titulo]
        second.append(cycle.advance().titulo)
        second.append(cycle.advance().titulo)
        self.assertEqual(second, ["c", "b", "a"])
        self.assertEqual(len(set(second)), 3)

    def test_single_tip_shows_again_on_the_next_turn(self) -> None:
        cycle = TipCycle([Dica("So essa", "texto")])
        self.assertEqual(cycle.current().titulo, "So essa")
        self.assertEqual(cycle.advance().titulo, "So essa")
        self.assertEqual(cycle.advance().texto, "texto")

    def test_empty_list_has_no_tip(self) -> None:
        cycle = TipCycle([])
        self.assertIsNone(cycle.current())
        self.assertIsNone(cycle.advance())


class SaveVersionTests(unittest.TestCase):
    def test_block_bumps_only_when_upload_succeeded(self) -> None:
        data = {"apps": [], "dicas": {"url": "https://antiga", "versao": "3"}}
        self.assertEqual(
            publish_dicas_block(data, url="https://nova", uploaded=False),
            "3",
        )
        self.assertEqual(data["dicas"]["versao"], "3")
        self.assertEqual(data["dicas"]["url"], "https://antiga")
        self.assertEqual(
            publish_dicas_block(data, url="https://nova/tips.json", uploaded=True),
            "4",
        )
        self.assertEqual(data["dicas"], {"url": "https://nova/tips.json", "versao": "4"})

    def test_save_bumps_only_after_successful_tips_upload(self) -> None:
        catalog = {
            "apps": [],
            "dicas": {"url": "https://antiga/tips.json", "versao": "3"},
        }
        text = json.dumps(catalog)
        form = DicasFormState(
            url="https://antiga/tips.json",
            pairs=[("Atalho", "Texto novo")],
            versao="3",
        )
        catalog_calls: list[dict] = []

        def fetch() -> tuple[str, str]:
            return text, ""

        def tips_fail() -> tuple[bool, str, str]:
            return False, "Falha ao enviar tips.json.", ""

        def catalog_upload(data: dict) -> PublishOutcome:
            catalog_calls.append(data)
            return PublishOutcome(ok=True)

        failed = save_dicas(
            form,
            expected_fingerprint="",
            fetch_text=fetch,
            upload_tips=tips_fail,
            upload_catalog=catalog_upload,
        )
        self.assertFalse(failed.ok)
        self.assertEqual(catalog_calls, [])
        self.assertIn("tips.json", failed.message)
        self.assertEqual(catalog["dicas"]["versao"], "3")

        def tips_ok() -> tuple[bool, str, str]:
            return True, "", "https://empresa.sharepoint.com/sites/s/tips.json"

        def catalog_ok(data: dict) -> PublishOutcome:
            catalog_calls.append(json.loads(json.dumps(data)))
            return PublishOutcome(ok=True, message="Catalogo publicado.")

        saved = save_dicas(
            form,
            expected_fingerprint="",
            fetch_text=fetch,
            upload_tips=tips_ok,
            upload_catalog=catalog_ok,
        )
        self.assertTrue(saved.ok)
        self.assertEqual(len(catalog_calls), 1)
        self.assertEqual(
            catalog_calls[0]["dicas"],
            {
                "url": "https://empresa.sharepoint.com/sites/s/tips.json",
                "versao": "4",
            },
        )
        self.assertEqual(catalog["dicas"]["versao"], "3")


class TipLinkTests(unittest.TestCase):
    def test_detects_https_and_markdown_link(self) -> None:
        pieces = tip_text_pieces(
            "Veja https://exemplo.com/a e [o guia](https://exemplo.com/b)."
        )
        linked = [(text, url) for text, url in pieces if url]
        self.assertEqual(
            linked,
            [
                ("https://exemplo.com/a", "https://exemplo.com/a"),
                ("o guia", "https://exemplo.com/b"),
            ],
        )
        plain = tip_text_pieces("So texto, sem endereco.")
        self.assertEqual(plain, [("So texto, sem endereco.", "")])
        odd = "".join(text for text, url in tip_text_pieces("veja [x](nao-e-url) e [y]()"))
        self.assertIn("[x](nao-e-url)", odd)
        self.assertIn("[y]()", odd)
        self.assertFalse(any(url for _text, url in tip_text_pieces("veja [x](nao-e-url) e [y]()")))

        opened: list[str] = []
        balloon = tip_balloon(
            Dica("Titulo puro https://nao.abre", "Abra [o guia](https://exemplo.com/guia)"),
            on_open_url=opened.append,
        )
        title = next(node for node in _walk(balloon) if getattr(node, "value", None) == "Titulo puro https://nao.abre")
        self.assertFalse(getattr(title, "spans", None))
        spans = []
        for node in _walk(balloon):
            for span in getattr(node, "spans", None) or []:
                spans.append(span)
        guide = next(span for span in spans if getattr(span, "text", None) == "o guia")
        guide.on_click(None)
        self.assertEqual(opened, ["https://exemplo.com/guia"])

        quiet = tip_balloon(Dica("T", "veja [x]() e texto"), on_open_url=opened.append)
        self.assertIn("veja [x]() e texto", _texts(quiet))
        self.assertEqual(opened, ["https://exemplo.com/guia"])


class UniqueIdTipsUrlTests(unittest.TestCase):
    def test_pasted_download_aspx_url_is_stored_unchanged(self) -> None:
        pasted = (
            "https://empresa.sharepoint.com/teams/seu-time/"
            "_layouts/15/download.aspx?UniqueId=11111111-2222-3333-4444-555555555555"
        )
        form = DicasFormState(
            url=pasted,
            local_path="/tmp/tips.json",
            local_name="tips.json",
            dest_folder="https://empresa.sharepoint.com/sites/seu-site/Documentos%20Compartilhados",
            pairs=[("Atalho", "Texto")],
        )
        with (
            patch("services.catalog_publish.enviar_por_unique_id") as upload,
            patch("services.catalog_publish.sharing_url") as sharing,
        ):
            upload.return_value = SharePointResult(ok=True, message="ok")
            ok, _message, url = _upload_tips_document(object(), form, "{}", None)
        self.assertTrue(ok)
        self.assertEqual(url, pasted)
        self.assertNotIn(":u:", url)
        sharing.assert_not_called()
        self.assertEqual(
            upload.call_args.kwargs["unique_id"],
            "11111111-2222-3333-4444-555555555555",
        )


class TipLineTests(unittest.TestCase):
    def test_dica_line_sits_above_the_title_with_matching_icons(self) -> None:
        balloon = tip_balloon(Dica("Titulo da dica", "Corpo da dica"))
        labels = _texts(balloon)
        self.assertLess(labels.index("Dica!"), labels.index("Titulo da dica"))
        self.assertLess(labels.index("Titulo da dica"), labels.index("Corpo da dica"))

        kicker = next(node for node in _walk(balloon) if getattr(node, "value", None) == "Dica!")
        title = next(node for node in _walk(balloon) if getattr(node, "value", None) == "Titulo da dica")
        body = next(node for node in _walk(balloon) if getattr(node, "value", None) == "Corpo da dica")
        self.assertEqual(title.size, 14)
        self.assertEqual(title.weight, ft.FontWeight.BOLD)
        self.assertEqual(title.color, config.COLOR_ACCENT)
        self.assertEqual(body.size, 13)
        self.assertEqual(body.color, config.COLOR_TEXT)
        self.assertEqual(balloon.left, 0)
        self.assertEqual(balloon.right, 0)
        self.assertEqual(balloon.bottom, 0)

        row = next(
            node
            for node in _walk(balloon)
            if isinstance(node, ft.Row) and any(getattr(child, "value", None) == "Dica!" for child in node.controls)
        )
        self.assertIs(row.controls[1], kicker)
        self.assertEqual(row.controls[0].icon, ft.Icons.LIGHTBULB)
        self.assertEqual(row.controls[2].icon, ft.Icons.ARROW_FORWARD)
        for icon in (row.controls[0], row.controls[2]):
            self.assertIsInstance(icon, ft.Icon)
            self.assertEqual(icon.size, kicker.size)
            self.assertEqual(icon.color, kicker.color)

    def test_apply_tip_keeps_the_line_and_the_title_style(self) -> None:
        opened: list[str] = []
        balloon = tip_balloon(Dica("Um", "corpo um"), on_open_url=opened.append)
        title = next(node for node in _walk(balloon) if getattr(node, "value", None) == "Um")
        apply_tip(balloon, Dica("Dois", "Abra [o guia](https://exemplo.com/g)"), opened.append)
        self.assertIs(title, balloon._tip_title)
        self.assertEqual(title.value, "Dois")
        self.assertEqual(title.size, 14)
        self.assertEqual(title.weight, ft.FontWeight.BOLD)
        self.assertEqual(title.color, config.COLOR_ACCENT)
        self.assertIn("Dica!", _texts(balloon))
        spans = []
        for node in _walk(balloon):
            for span in getattr(node, "spans", None) or []:
                spans.append(span)
        guide = next(span for span in spans if getattr(span, "text", None) == "o guia")
        guide.on_click(None)
        self.assertEqual(opened, ["https://exemplo.com/g"])


class _TipPage:
    def __init__(self) -> None:
        self.handler = None
        self.updates: list[str] = []

    def run_task(self, handler, *args, **kwargs) -> None:
        self.handler = handler

    def update(self) -> None:
        self.updates.append("page")


class TipRefreshTests(unittest.TestCase):
    def _app(self, balloon, tip) -> tuple[SuiteApp, _TipPage, list[str]]:
        app = SuiteApp.__new__(SuiteApp)
        app._exiting = False
        app.selected_id = None
        app.selected_setor = None
        app.show_favorites = False
        app.show_publish = False
        app._sync_screen_visible = False
        app.renders = 0
        app._render = lambda: setattr(app, "renders", app.renders + 1)
        app._home_tip_balloon = balloon
        app._current_tip = tip
        app._open_tip_link = lambda _url: None
        page = _TipPage()
        app.page = page
        control_updates: list[str] = []
        balloon.update = lambda: control_updates.append("control")
        return app, page, control_updates

    def test_rotation_refreshes_the_balloon_on_the_page_task(self) -> None:
        self.assertEqual(TIP_ROTATE_SECONDS, 60)
        first = Dica("Primeira", "texto um")
        second = Dica("Segunda", "texto dois")
        balloon = tip_balloon(first)
        app, page, control_updates = self._app(balloon, first)

        class Cycle:
            def advance(self):
                return second

        app._tip_cycle = Cycle()
        sleeps: list[float] = []

        def sleep(seconds: float) -> bool:
            sleeps.append(seconds)
            return len(sleeps) == 1

        app._interruptible_sleep = sleep
        SuiteApp._tip_loop(app)

        self.assertEqual(sleeps[0], 60)
        self.assertEqual(app.renders, 0)
        self.assertEqual(page.updates, [])
        self.assertEqual(control_updates, [])
        self.assertIn("Primeira", _texts(balloon))
        self.assertNotIn("Segunda", _texts(balloon))
        self.assertIsNotNone(page.handler)

        asyncio.run(page.handler())

        self.assertIn("Segunda", _texts(balloon))
        self.assertIn("texto dois", _texts(balloon))
        self.assertIn("Dica!", _texts(balloon))
        self.assertEqual(control_updates, ["control"])
        self.assertEqual(page.updates, [])
        self.assertEqual(app.renders, 0)
        title = next(node for node in _walk(balloon) if getattr(node, "value", None) == "Segunda")
        self.assertEqual(title.size, 14)
        self.assertEqual(title.weight, ft.FontWeight.BOLD)
        self.assertEqual(title.color, config.COLOR_ACCENT)

    def test_rotation_away_from_home_does_not_paint(self) -> None:
        first = Dica("Primeira", "texto um")
        balloon = tip_balloon(first)
        app, page, control_updates = self._app(balloon, first)
        app.selected_id = "algum-app"

        class Cycle:
            def advance(self):
                return Dica("Segunda", "texto dois")

        app._tip_cycle = Cycle()
        sleeps: list[float] = []

        def sleep(_seconds: float) -> bool:
            sleeps.append(1)
            return len(sleeps) == 1

        app._interruptible_sleep = sleep
        SuiteApp._tip_loop(app)
        self.assertIsNone(page.handler)
        self.assertEqual(control_updates, [])
        self.assertIn("Primeira", _texts(balloon))
        self.assertNotIn("Segunda", _texts(balloon))
        self.assertEqual(app.renders, 0)


class DicasUiTests(unittest.TestCase):
    def test_home_balloon_only_when_there_is_a_tip(self) -> None:
        plain = build_home(
            [],
            lambda _app: None,
            gerencia=None,
            favorite_ids=set(),
            on_toggle_favorite=lambda _app: None,
        )
        self.assertNotIn("Atalho", _texts(plain))
        self.assertNotIsInstance(plain, ft.Stack)
        tipped = build_home(
            [],
            lambda _app: None,
            gerencia=None,
            favorite_ids=set(),
            on_toggle_favorite=lambda _app: None,
            tip=Dica("Atalho", "Texto da dica."),
        )
        self.assertIsInstance(tipped, ft.Stack)
        labels = _texts(tipped)
        self.assertIn("Atalho", labels)
        self.assertIn("Texto da dica.", labels)

    def test_edit_block_waits_for_the_file_and_separates_pairs(self) -> None:
        select = ft.Container()
        edit = ft.Container()
        empty = DicasFormState()
        bind_dicas_form(
            empty,
            on_save=lambda: None,
            on_pick=lambda: None,
            on_field=lambda _key, _value: None,
            on_reopen=lambda: None,
            select_holder=select,
            edit_holder=edit,
        )
        locked = _texts(edit)
        self.assertIn("Selecione ou adicione o tips.json para editar.", locked)
        self.assertNotIn("Título da dica", locked)

        ready = DicasFormState(
            url="https://empresa.sharepoint.com/tips.json",
            pairs=[("Um", "primeiro"), ("Dois", "segundo")],
        )
        bind_dicas_form(
            ready,
            on_save=lambda: None,
            on_pick=lambda: None,
            on_field=lambda _key, _value: None,
            on_reopen=lambda: None,
            select_holder=select,
            edit_holder=edit,
        )
        labels = _texts(edit)
        self.assertEqual(labels.count("Título da dica"), 2)
        self.assertEqual(labels.count("Dica"), 2)
        dividers = [node for node in _walk(edit) if isinstance(node, ft.Divider)]
        self.assertEqual(len(dividers), 1)


if __name__ == "__main__":
    unittest.main()
