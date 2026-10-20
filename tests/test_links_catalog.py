"""Aba Links do Catalogo: versao, ordem e o que entra no links.json."""
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

from models import CatalogData, LinksInfo, parse_catalog_dict, parse_links_payload
from services.catalog_publish import PublishFormState, PublishOutcome, StructureFormState, _upload_links_document, save_links
from services.links import (
    LinkDraft,
    LinkGroupDraft,
    LinksFormState,
    add_group,
    add_item,
    links_payload,
    move_group,
    move_item,
    publish_links_block,
    relocate_item,
    store_local_links,
)
from services.sharepoint_manager import SharePointResult
from main import SuiteApp
from ui.catalog_view import bind_catalog_view
from ui.links_form_view import bind_links_form


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


def _sample() -> list[LinkGroupDraft]:
    return [
        LinkGroupDraft(
            "Portais",
            [
                LinkDraft("Ponto", "Registro de ponto", "https://exemplo.com/ponto"),
                LinkDraft("Folha", "", "https://exemplo.com/folha"),
            ],
        ),
        LinkGroupDraft(
            "Manuais",
            [LinkDraft("Guia", "Passo a passo", "https://exemplo.com/guia")],
        ),
    ]


class OrderTests(unittest.TestCase):
    def test_move_group_and_item_and_the_page_keeps_that_order(self) -> None:
        groups = _sample()
        self.assertTrue(move_group(groups, 1, -1))
        self.assertEqual([group.titulo for group in groups], ["Manuais", "Portais"])
        self.assertFalse(move_group(groups, 0, -1))
        self.assertTrue(move_item(groups, 1, 1, -1))
        self.assertEqual([item.titulo for item in groups[1].items], ["Folha", "Ponto"])
        self.assertFalse(move_item(groups, 1, 0, -1))

        parsed = parse_links_payload(links_payload(groups))
        self.assertEqual([group.titulo for group in parsed], ["Manuais", "Portais"])
        self.assertEqual([item.titulo for item in parsed[1].links], ["Folha", "Ponto"])

    def test_new_group_and_item_go_to_the_end(self) -> None:
        groups = _sample()
        add_item(groups, 0)
        self.assertEqual(groups[0].items[-1].titulo, "")
        self.assertEqual(groups[0].items[-1].url, "")
        add_group(groups)
        self.assertEqual(groups[-1].titulo, "")
        self.assertEqual(groups[-1].items, [])

    def test_changing_the_group_field_moves_the_item_to_the_end(self) -> None:
        groups = _sample()
        self.assertTrue(relocate_item(groups, 0, 0, "Manuais"))
        self.assertEqual([item.titulo for item in groups[0].items], ["Folha"])
        self.assertEqual([item.titulo for item in groups[1].items], ["Guia", "Ponto"])
        self.assertFalse(relocate_item(groups, 1, 1, "Manuais"))

        self.assertTrue(relocate_item(groups, 0, 0, "  Novo  "))
        self.assertEqual(groups[-1].titulo, "Novo")
        self.assertEqual([item.titulo for item in groups[-1].items], ["Folha"])
        self.assertEqual([group.titulo for group in groups], ["Portais", "Manuais", "Novo"])

    def test_handler_reorders_group_and_item(self) -> None:
        app = SuiteApp.__new__(SuiteApp)
        app.links_form = LinksFormState(url="https://sp/links.json", groups=_sample())
        app.renders = 0
        app._render = lambda: setattr(app, "renders", app.renders + 1)

        SuiteApp._links_field(app, "descer_grupo:0", "1")
        self.assertEqual([group.titulo for group in app.links_form.groups], ["Manuais", "Portais"])
        SuiteApp._links_field(app, "subir:1:1", "1")
        self.assertEqual(
            [item.titulo for item in app.links_form.groups[1].items],
            ["Folha", "Ponto"],
        )
        SuiteApp._links_field(app, "grupo_item:1:0", "Manuais")
        manuais = app.links_form.groups[0]
        self.assertEqual([item.titulo for item in manuais.items], ["Guia", "Folha"])
        self.assertGreater(app.renders, 0)


class PayloadTests(unittest.TestCase):
    def test_item_without_title_or_url_stays_out(self) -> None:
        groups = [
            LinkGroupDraft(
                "Portais",
                [
                    LinkDraft("Ponto", "", "https://exemplo.com/ponto"),
                    LinkDraft("", "tem descricao", "https://exemplo.com/sem-titulo"),
                    LinkDraft("Sem url", "texto", "  "),
                    LinkDraft("   ", "vazio", "https://exemplo.com/titulo-vazio"),
                ],
            ),
            LinkGroupDraft(
                "  ",
                [LinkDraft("Some", "d", "https://exemplo.com/grupo-sem-titulo")],
            ),
            LinkGroupDraft("Vazio", [LinkDraft("", "", "")]),
        ]
        payload = links_payload(groups)
        self.assertEqual(
            payload,
            {
                "grupos": [
                    {
                        "titulo": "Portais",
                        "links": [
                            {
                                "titulo": "Ponto",
                                "descricao": "",
                                "url": "https://exemplo.com/ponto",
                            }
                        ],
                    }
                ]
            },
        )
        page = parse_links_payload(payload)
        self.assertEqual(len(page), 1)
        self.assertEqual(page[0].links[0].descricao, "")
        self.assertEqual(page[0].links[0].titulo, "Ponto")


class SaveVersionTests(unittest.TestCase):
    def test_block_bumps_only_when_upload_succeeded(self) -> None:
        data = {"apps": [], "links": {"url": "https://antiga", "versao": "3"}}
        self.assertEqual(
            publish_links_block(data, url="https://nova", uploaded=False),
            "3",
        )
        self.assertEqual(data["links"]["versao"], "3")
        self.assertEqual(data["links"]["url"], "https://antiga")
        self.assertEqual(
            publish_links_block(data, url="https://nova/links.json", uploaded=True),
            "4",
        )
        self.assertEqual(data["links"], {"url": "https://nova/links.json", "versao": "4"})

    def test_save_bumps_only_after_successful_links_upload(self) -> None:
        catalog = {
            "apps": [],
            "links": {"url": "https://antiga/links.json", "versao": "3"},
        }
        text = json.dumps(catalog)
        form = LinksFormState(
            url="https://antiga/links.json",
            groups=_sample(),
            versao="3",
        )
        catalog_calls: list[dict] = []
        stored: list[tuple] = []

        def fetch() -> tuple[str, str]:
            return text, ""

        def links_fail() -> tuple[bool, str, str]:
            return False, "Falha ao enviar links.json.", ""

        def catalog_upload(data: dict) -> PublishOutcome:
            catalog_calls.append(data)
            return PublishOutcome(ok=True)

        def remember(groups, versao, **_kwargs) -> None:
            stored.append((list(groups), versao))

        with patch("services.catalog_publish.store_local_links", side_effect=remember):
            failed = save_links(
                form,
                expected_fingerprint="",
                fetch_text=fetch,
                upload_links=links_fail,
                upload_catalog=catalog_upload,
            )
        self.assertFalse(failed.ok)
        self.assertEqual(catalog_calls, [])
        self.assertEqual(stored, [])
        self.assertIn("links.json", failed.message)
        self.assertEqual(catalog["links"]["versao"], "3")

        def links_ok() -> tuple[bool, str, str]:
            return True, "", "https://empresa.sharepoint.com/sites/s/links.json"

        def catalog_ok(data: dict) -> PublishOutcome:
            catalog_calls.append(json.loads(json.dumps(data)))
            return PublishOutcome(
                ok=True,
                message="Catalogo publicado.",
                catalog=parse_catalog_dict(data),
            )

        with patch("services.catalog_publish.store_local_links", side_effect=remember):
            saved = save_links(
                form,
                expected_fingerprint="",
                fetch_text=fetch,
                upload_links=links_ok,
                upload_catalog=catalog_ok,
            )
        self.assertTrue(saved.ok)
        self.assertEqual(len(catalog_calls), 1)
        self.assertEqual(
            catalog_calls[0]["links"],
            {
                "url": "https://empresa.sharepoint.com/sites/s/links.json",
                "versao": "4",
            },
        )
        self.assertEqual(catalog["links"]["versao"], "3")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0][1], "4")
        self.assertEqual(stored[0][0][0].titulo, "Portais")

    def test_local_copy_updates_only_with_the_saved_version(self) -> None:
        groups = [
            LinkGroupDraft(
                "Portais",
                [
                    LinkDraft("Ponto", "Registro de ponto", "https://exemplo.com/ponto"),
                    LinkDraft("", "fora", "https://exemplo.com/sem-titulo"),
                ],
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dest = root / "links.json"
            version = root / "links.versao"
            version.write_text("3", encoding="utf-8")
            store_local_links(groups, "4", links_path=dest, version_path=version)
            body = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(body["grupos"][0]["links"][0]["titulo"], "Ponto")
            self.assertEqual(len(body["grupos"][0]["links"]), 1)
            self.assertEqual(version.read_text(encoding="utf-8"), "4")
            self.assertFalse((root / "links.json.writing").exists())


class UniqueIdLinksUrlTests(unittest.TestCase):
    def test_pasted_download_aspx_url_is_stored_unchanged(self) -> None:
        pasted = (
            "https://empresa.sharepoint.com/teams/seu-time/"
            "_layouts/15/download.aspx?UniqueId=11111111-2222-3333-4444-555555555555"
        )
        form = LinksFormState(
            url=pasted,
            local_path="/tmp/links.json",
            local_name="links.json",
            dest_folder="https://empresa.sharepoint.com/sites/seu-site/Documentos%20Compartilhados",
            groups=_sample(),
        )
        session = object()
        with (
            patch("services.catalog_publish.enviar_por_unique_id") as upload,
            patch("services.catalog_publish.sharing_url") as sharing,
        ):
            upload.return_value = SharePointResult(ok=True, message="ok")
            ok, _message, url = _upload_links_document(session, form, "{}", None)
        self.assertTrue(ok)
        self.assertEqual(url, pasted)
        self.assertNotIn(":u:", url)
        sharing.assert_not_called()
        self.assertEqual(
            upload.call_args.kwargs["unique_id"],
            "11111111-2222-3333-4444-555555555555",
        )
        self.assertIs(upload.call_args.kwargs["session"], session)


class LinksUiTests(unittest.TestCase):
    def test_edit_block_waits_for_the_file(self) -> None:
        select = ft.Container()
        edit = ft.Container()
        bind_links_form(
            LinksFormState(),
            on_save=lambda: None,
            on_pick=lambda: None,
            on_field=lambda _key, _value: None,
            on_reopen=lambda: None,
            select_holder=select,
            edit_holder=edit,
        )
        locked = _texts(edit)
        self.assertIn("Selecione ou adicione o links.json para editar.", locked)
        self.assertNotIn("Título", locked)
        self.assertNotIn("Ordenar favoritos", _texts(select) + locked)

    def test_fields_follow_the_dicas_style_and_buttons_move_without_drag(self) -> None:
        select = ft.Container()
        edit = ft.Container()
        calls: list[tuple[str, str]] = []
        bind_links_form(
            LinksFormState(url="https://empresa.sharepoint.com/links.json", groups=_sample()),
            on_save=lambda: None,
            on_pick=lambda: None,
            on_field=lambda key, value: calls.append((key, value)),
            on_reopen=lambda: None,
            select_holder=select,
            edit_holder=edit,
        )
        labels = _texts(edit)
        self.assertEqual(labels.count("Título"), 3)
        self.assertEqual(labels.count("Descrição"), 3)
        self.assertEqual(labels.count("Link"), 3)
        self.assertGreaterEqual(labels.count("Grupo"), 5)
        self.assertIn("Subir grupo", labels)
        self.assertIn("Descer grupo", labels)
        self.assertIn("Subir", labels)
        self.assertIn("Descer", labels)
        self.assertNotIn("Ordenar favoritos", labels)
        title = next(node for node in _walk(edit) if getattr(node, "value", None) == "Título")
        self.assertEqual(title.weight, ft.FontWeight.BOLD)
        none_border = getattr(getattr(ft, "InputBorder", None), "NONE", None)
        fields = [node for node in _walk(edit) if isinstance(node, ft.TextField)]
        self.assertGreaterEqual(len(fields), 3)
        for field in fields:
            if none_border is not None:
                self.assertEqual(getattr(field, "border", None), none_border)

        buttons = [
            (getattr(node, "content", None), bool(getattr(node, "disabled", False)))
            for node in _walk(edit)
            if getattr(node, "content", None) in {"Subir grupo", "Descer grupo", "Subir", "Descer"}
        ]
        self.assertEqual(
            buttons,
            [
                ("Subir grupo", True),
                ("Descer grupo", False),
                ("Subir", True),
                ("Descer", False),
                ("Subir", False),
                ("Descer", True),
                ("Subir grupo", False),
                ("Descer grupo", True),
                ("Subir", True),
                ("Descer", True),
            ],
        )
        movers = [
            node
            for node in _walk(edit)
            if isinstance(node, ft.TextField) and getattr(node, "on_blur", None)
        ]
        self.assertEqual(len(movers), 3)
        movers[0].value = "Manuais"
        movers[0].on_blur(type("E", (), {"control": movers[0]})())
        self.assertEqual(calls, [("grupo_item:0:0", "Manuais")])

    def test_catalog_tabs_put_links_between_estrutura_and_dicas(self) -> None:
        row = ft.Row()
        host = ft.Container()
        links_layout = ft.Column()
        dicas_layout = ft.Column()
        publish_layout = ft.Column()
        estrutura_layout = ft.Row()
        holders = [ft.Container() for _ in range(8)]

        def noop(*_args, **_kwargs):
            return None

        bind_catalog_view(
            CatalogData(),
            PublishFormState(),
            StructureFormState(),
            "links",
            on_tab=noop,
            on_select_app=noop,
            on_save=noop,
            on_cancel=noop,
            on_pick=noop,
            on_field=noop,
            on_reopen=noop,
            on_structure_select=noop,
            on_structure_field=noop,
            on_structure_toggle_app=noop,
            on_structure_new=noop,
            on_structure_new_subsetor=noop,
            on_structure_delete=noop,
            on_structure_save=noop,
            on_structure_reopen=noop,
            tab_row=row,
            session_host=host,
            publish_layout=publish_layout,
            estrutura_layout=estrutura_layout,
            publish_select=holders[0],
            publish_edit=holders[1],
            structure_select=holders[2],
            structure_edit=holders[3],
            dicas_layout=dicas_layout,
            dicas_select=holders[4],
            dicas_edit=holders[5],
            links=LinksFormState(url="https://empresa.sharepoint.com/links.json"),
            links_layout=links_layout,
            links_select=holders[6],
            links_edit=holders[7],
        )
        self.assertEqual(_texts(row), ["Publicar", "Estrutura", "Links", "Dicas"])
        self.assertIs(host.content, links_layout)


if __name__ == "__main__":
    unittest.main()
