"""Feedback do aplicativo: ponteiro opcional, envio e a tela."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flet as ft

import config
from models import AppInfo, CatalogData, FeedbackInfo, parse_catalog_dict
from services.catalog_publish import PublishFormState, PublishOutcome, StructureFormState
from services.feedback import (
    FeedbackCatalogState,
    FeedbackEntry,
    feedback_app_label,
    feedback_entry_title,
    feedback_screen_numbers,
    feedback_sent_message,
    feedback_user_label,
    ordered_feedback_entries,
    publish_feedback_block,
    save_feedback_pointer,
    should_download_feedback,
    submit_app_feedback,
    sync_feedback,
)
from ui.catalog_view import bind_catalog_view
from ui.feedback_catalog_view import _ENTRY_TITLE_WIDTH, bind_feedback_form, feedback_top_row
from services.sharepoint_manager import SharePointResult
from services.storage import Storage
from ui.app_detail_view import AppDetailView
from ui.feedback_view import FeedbackView
from ui.tutorial_view import TutorialView

PASTED = (
    "https://empresa.sharepoint.com/teams/seu-time/"
    "_layouts/15/download.aspx?UniqueId=11111111-2222-3333-4444-555555555555"
)


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


def _action_labels(control) -> list[str]:
    for node in _walk(control):
        controls = getattr(node, "controls", None) or []
        labels = []
        for child in controls:
            if getattr(child, "visible", True) is False:
                continue
            content = getattr(child, "content", None)
            if isinstance(content, str):
                labels.append(content)
        if "Baixar / Instalar" in labels or "Executar" in labels:
            return labels
    return []


class _Page:
    def __init__(self) -> None:
        self.threads = []
        self.updates = 0

    def run_thread(self, fn) -> None:
        self.threads.append(fn)
        fn()

    def update(self) -> None:
        self.updates += 1


class _Event:
    def __init__(self, control=None) -> None:
        self.control = control


class CatalogFeedbackTests(unittest.TestCase):
    def test_old_catalog_without_feedback_still_parses_and_hides_the_button(self) -> None:
        catalog = parse_catalog_dict({"apps": [{"id": "a", "nome": "Relatorio"}]})
        self.assertEqual(catalog.feedback, FeedbackInfo())
        self.assertFalse(catalog.feedback.configured)
        only_url = parse_catalog_dict({"feedback": {"url": PASTED}})
        only_version = parse_catalog_dict({"feedback": {"versao": "1"}})
        broken = parse_catalog_dict({"feedback": "nao-e-objeto"})
        self.assertFalse(only_url.feedback.configured)
        self.assertFalse(only_version.feedback.configured)
        self.assertFalse(broken.feedback.configured)

        app = AppInfo(id="a", nome="Relatorio")
        page = _Page()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "apps", root / "installed.json")
            hidden = AppDetailView(page, app, storage, object()).build()
            shown = AppDetailView(
                page, app, storage, object(), feedback_enabled=True
            ).build()
            ready = parse_catalog_dict(
                {"feedback": {"url": PASTED, "versao": "2"}, "apps": [{"id": "a", "nome": "Relatorio"}]}
            )
        self.assertTrue(ready.feedback.configured)
        self.assertEqual(ready.feedback.url, PASTED)
        self.assertNotIn("Feedback", _action_labels(hidden))
        self.assertEqual(_action_labels(shown), ["Baixar / Instalar", "Feedback"])
        filtered = ready.filter_for_gerencia("")
        self.assertEqual(filtered.feedback, ready.feedback)

    def test_example_points_at_the_growing_list(self) -> None:
        catalog = json.loads((ROOT / "catalog.example.json").read_text(encoding="utf-8"))
        pointer = catalog["feedback"]
        self.assertTrue({"url", "versao", "introducao", "confirmacao"} <= set(pointer))
        self.assertIn("download.aspx?UniqueId=", pointer["url"])
        self.assertTrue(str(pointer["versao"]).strip())
        self.assertIn("dia a dia", pointer["introducao"])
        parsed = parse_catalog_dict(catalog)
        self.assertEqual(parsed.feedback.introducao, pointer["introducao"])
        self.assertEqual(parsed.feedback.confirmacao, pointer["confirmacao"])
        self.assertTrue(parsed.feedback.configured)
        legacy = parse_catalog_dict({"feedback": {"url": PASTED, "versao": "1"}})
        self.assertEqual(legacy.feedback.introducao, "")
        self.assertEqual(legacy.feedback.confirmacao, "")
        self.assertEqual(feedback_sent_message(""), "Feedback enviado.")
        self.assertEqual(feedback_sent_message("   "), "Feedback enviado.")
        self.assertEqual(feedback_sent_message("Obrigado."), "Obrigado.")
        self.assertTrue(legacy.feedback.configured)
        body = json.loads((ROOT / "feedback.example.json").read_text(encoding="utf-8"))
        self.assertIsInstance(body, list)
        self.assertNotIn("introducao", body[0])
        self.assertEqual(
            set(body[0]),
            {"usuario", "quando", "app_id", "texto"},
        )


class SendTests(unittest.TestCase):
    def _submit(self, *, uploaded: bool, catalog_uploaded: bool = True, now=None, usuario="EMPRESA\\maria"):
        catalog = {
            "apps": [],
            "feedback": {"url": PASTED, "versao": "3"},
        }
        text = json.dumps(catalog)
        existing = [
            {
                "usuario": "EMPRESA\\joao",
                "quando": "2026-11-01 09:00:00",
                "app_id": "outro",
                "texto": "Antigo",
            }
        ]
        bodies: list[str] = []
        catalog_calls: list[dict] = []
        fetches: list[int] = []

        def read() -> tuple[str, str]:
            return json.dumps(existing), ""

        def upload(body: str) -> tuple[bool, str]:
            if not uploaded:
                return False, "Nao foi possivel enviar."
            bodies.append(body)
            return True, ""

        def fetch() -> tuple[str, str]:
            fetches.append(1)
            return text, ""

        def upload_catalog(data: dict) -> tuple[bool, str]:
            catalog_calls.append(json.loads(json.dumps(data)))
            if not catalog_uploaded:
                return False, "Nao foi possivel atualizar a versao."
            return True, ""

        result = submit_app_feedback(
            app_id="relatorio-producao",
            texto="A planilha nao abriu.",
            feedback_url=PASTED,
            usuario=usuario,
            now=now,
            read_feedback=read,
            upload_feedback=upload,
            fetch_catalog=fetch,
            upload_catalog=upload_catalog,
        )
        return result, bodies, catalog_calls, fetches, catalog

    def test_version_bumps_only_after_successful_upload(self) -> None:
        failed, bodies, catalog_calls, fetches, catalog = self._submit(uploaded=False)
        self.assertFalse(failed.ok)
        self.assertEqual(bodies, [])
        self.assertEqual(catalog_calls, [])
        self.assertEqual(fetches, [])
        self.assertEqual(catalog["feedback"]["versao"], "3")
        self.assertEqual(catalog["feedback"]["url"], PASTED)

        saved, bodies, catalog_calls, _fetches, catalog = self._submit(uploaded=True)
        self.assertTrue(saved.ok)
        self.assertEqual(saved.versao, "4")
        self.assertEqual(len(catalog_calls), 1)
        self.assertEqual(
            catalog_calls[0]["feedback"],
            {"url": PASTED, "versao": "4"},
        )
        self.assertNotIn(":u:", catalog_calls[0]["feedback"]["url"])
        self.assertEqual(catalog["feedback"]["versao"], "3")

        blocked = {"feedback": {"url": PASTED, "versao": "3"}}
        self.assertEqual(publish_feedback_block(blocked, uploaded=False), "3")
        self.assertEqual(blocked["feedback"]["url"], PASTED)
        self.assertEqual(blocked["feedback"]["versao"], "3")

        version_failed, _bodies, version_calls, _fetches, catalog = self._submit(
            uploaded=True,
            catalog_uploaded=False,
        )
        self.assertFalse(version_failed.ok)
        self.assertEqual(version_calls[0]["feedback"]["versao"], "4")
        self.assertEqual(catalog["feedback"]["versao"], "3")

    def test_saved_item_has_user_time_app_and_text(self) -> None:
        now = datetime(2026, 11, 3, 18, 4, 5, tzinfo=timezone.utc)
        result, bodies, _calls, _fetches, _catalog = self._submit(
            uploaded=True,
            now=now,
            usuario="EMPRESA\\maria",
        )
        self.assertTrue(result.ok)
        saved = json.loads(bodies[0])
        self.assertEqual(saved[0]["texto"], "Antigo")
        item = saved[-1]
        self.assertEqual(
            item,
            {
                "usuario": "EMPRESA\\maria",
                "quando": "2026-11-03 15:04:05",
                "app_id": "relatorio-producao",
                "texto": "A planilha nao abriu.",
            },
        )
        self.assertEqual(result.item, item)

    def test_live_send_uses_one_weblogin_and_keeps_the_unique_id(self) -> None:
        starts = []
        uploads = []

        class Session:
            def __init__(self, site_url, progress=None) -> None:
                self.site_url = site_url

            def start(self) -> str:
                starts.append(self.site_url)
                return ""

            def close(self) -> None:
                return None

        def download(**kwargs):
            folder = Path(kwargs["pasta_destino"])
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "feedback.json"
            path.write_text("[]", encoding="utf-8")
            self.assertIsInstance(kwargs["session"], Session)
            return SharePointResult(ok=True, path=path)

        def upload_id(arquivo, **kwargs):
            uploads.append(kwargs["unique_id"])
            self.assertIsInstance(kwargs["session"], Session)
            self.assertIn("maria", Path(arquivo).read_text(encoding="utf-8"))
            return SharePointResult(ok=True)

        def fetch(**kwargs):
            self.assertIsInstance(kwargs["session"], Session)
            return json.dumps({"feedback": {"url": PASTED, "versao": "3"}}), ""

        def upload_catalog(data, progress, session=None):
            self.assertIsInstance(session, Session)
            self.assertEqual(data["feedback"]["url"], PASTED)
            self.assertEqual(data["feedback"]["versao"], "4")
            return PublishOutcome(ok=True, message="Catalogo publicado.", catalog=parse_catalog_dict(data))

        with (
            patch("services.feedback.PnPWebLoginSession", Session),
            patch("services.feedback.baixar_do_sharepoint", side_effect=download),
            patch("services.feedback.enviar_por_unique_id", side_effect=upload_id),
            patch("services.feedback.fetch_remote_catalog_text", side_effect=fetch),
            patch("services.feedback._upload_catalog_text", side_effect=upload_catalog),
            patch("services.sharepoint_manager._run_templated_ps1", side_effect=AssertionError("janela")),
            patch("services.feedback.config.REMOTE_CATALOG_URL", PASTED),
            patch("services.feedback.current_windows_login", return_value="EMPRESA\\maria"),
        ):
            result = submit_app_feedback(
                app_id="relatorio-producao",
                texto="Travou",
                feedback_url=PASTED,
                now=datetime(2026, 11, 3, 18, 4, 5, tzinfo=timezone.utc),
            )
        self.assertTrue(result.ok)
        self.assertEqual(len(starts), 1)
        self.assertEqual(uploads, ["11111111-2222-3333-4444-555555555555"])
        self.assertEqual(result.catalog.feedback.url, PASTED)
        self.assertEqual(result.catalog.feedback.versao, "4")
        self.assertEqual(result.item["usuario"], "EMPRESA\\maria")


class FeedbackScreenTests(unittest.TestCase):
    def _assert_same_card(self, card) -> None:
        self.assertEqual(card.bgcolor, config.COLOR_SURFACE)
        self.assertEqual(card.border_radius, 12)
        self.assertEqual(card.padding, 16)
        self.assertEqual(card.border.top.width, 1)
        self.assertEqual(card.border.top.color, "#2C4036")

    def _app(self) -> AppInfo:
        return AppInfo(id="relatorio-producao", nome="Relatorio de Producao")

    def test_back_before_send_discards_the_text(self) -> None:
        page = _Page()
        saved: list[str] = []
        backs: list[str] = []
        view = FeedbackView(
            page,
            self._app(),
            on_back=lambda: backs.append("voltar"),
            on_submit=lambda texto: saved.append(texto) or "",
        )
        built = view.build()
        view.field.value = "rascunho que nao vai"
        view.back_button.on_click(_Event(view.back_button))
        self.assertEqual(saved, [])
        self.assertEqual(backs, ["voltar"])
        self.assertEqual(page.threads, [])
        again = FeedbackView(page, self._app(), lambda: None, lambda texto: saved.append(texto) or "")
        again.build()
        self.assertEqual(again.field.value, "")
        self.assertIn("Feedback de Relatorio de Producao", _texts(built))
        self.assertTrue(view.field.multiline)
        self.assertGreaterEqual(view.field.min_lines or 0, 2)
        self.assertTrue(view.field.autofocus)
        self.assertIsNone(view.field.label)
        header = built.controls[0]
        self.assertEqual(header.alignment, ft.MainAxisAlignment.SPACE_BETWEEN)
        self.assertIs(header.controls[-1], view.back_button)
        tutorial = TutorialView(page, self._app(), lambda: None).build()
        tutorial_header = tutorial.controls[0]
        tutorial_back = tutorial_header.controls[-1]
        self.assertEqual(tutorial_header.alignment, header.alignment)
        self.assertEqual(view.back_button.content, tutorial_back.content)
        self.assertEqual(view.back_button.icon, tutorial_back.icon)
        self.assertEqual(view.back_button.icon, ft.Icons.ARROW_BACK)
        self.assertLess(built.controls.index(view.field_card), built.controls.index(view.send_row))
        self.assertIs(view.send_row.controls[0], view.send_button)
        self.assertNotEqual(view.send_button.expand, True)
        self.assertIsNone(view.send_button.width)
        self.assertIn(view.field, view.field_card.content.controls)
        self.assertEqual(view.field_title.value, "Escreva seu feedback:")
        self.assertIn("Escreva seu feedback:", _texts(view.field_card))
        self.assertEqual(built.horizontal_alignment, ft.CrossAxisAlignment.STRETCH)
        self.assertEqual(
            view.field_card.content.horizontal_alignment,
            ft.CrossAxisAlignment.STRETCH,
        )
        self.assertIsNone(view.field_card.width)
        self.assertIsNone(view.guide_card.width)
        self.assertFalse(view.guide_card.visible)
        self.assertTrue(view.field_card.visible)
        self._assert_same_card(view.field_card)

        guide = "Pode falar do uso no dia a dia, agradecer, sugerir melhoria ou apontar bug."
        guided = FeedbackView(
            page,
            self._app(),
            lambda: None,
            lambda texto: "",
            introducao=guide,
        )
        guided_page = guided.build()
        self.assertTrue(guided.guide_card.visible)
        self.assertIs(guided.guide_card.content, guided.guide_text)
        self.assertEqual(guided.guide_text.value, guide)
        self._assert_same_card(guided.guide_card)
        self._assert_same_card(guided.field_card)
        self.assertLess(
            guided_page.controls.index(guided.guide_card),
            guided_page.controls.index(guided.field_card),
        )
        self.assertLess(
            guided_page.controls.index(guided.field_card),
            guided_page.controls.index(guided.send_row),
        )
        title = guided_page.controls[0]
        self.assertLess(guided_page.controls.index(title), guided_page.controls.index(guided.guide_card))
        self.assertTrue(guided.field.autofocus)
        guided.set_introducao("   ")
        self.assertFalse(guided.guide_card.visible)
        guided._show_sent()
        self.assertFalse(guided.guide_card.visible)
        self.assertFalse(guided.field_card.visible)
        self.assertTrue(guided.success_card.visible)
        self._assert_same_card(guided.success_card)
        self.assertEqual(guided.success_icon.color, config.COLOR_ACCENT)
        self.assertEqual(guided.sent_text.value, "Feedback enviado.")
        guided.set_confirmacao("   ")
        self.assertEqual(guided.sent_text.value, "Feedback enviado.")
        guided.set_confirmacao("Valeu.")
        self.assertEqual(guided.sent_text.value, "Valeu.")
        self.assertTrue(guided.ok_button.visible)

    def test_failure_keeps_the_text_and_success_waits_for_ok_or_back(self) -> None:
        page = _Page()
        backs: list[str] = []

        def fail(_texto: str) -> str:
            self.assertEqual(view.send_button.content, "Enviando...")
            self.assertTrue(view.send_button.disabled)
            self.assertEqual(view.field.value, "Texto que fica")
            return "Nao foi possivel enviar."

        view = FeedbackView(page, self._app(), lambda: backs.append("voltar"), fail)
        view.build()
        view.field.value = "Texto que fica"
        view.send_button.on_click(_Event(view.send_button))
        self.assertEqual(backs, [])
        self.assertEqual(view.field.value, "Texto que fica")
        self.assertTrue(view.field.visible)
        self.assertEqual(view.send_button.content, "Enviar")
        self.assertFalse(view.send_button.disabled)
        self.assertEqual(view.error_text.value, "Nao foi possivel enviar.")
        self.assertTrue(view.error_text.visible)
        self.assertFalse(view.success_card.visible)
        self.assertFalse(view.sent_text.visible)
        self.assertFalse(view.ok_button.visible)

        def ok(_texto: str) -> str:
            self.assertEqual(done.send_button.content, "Enviando...")
            self.assertTrue(done.send_button.disabled)
            self.assertEqual(done.field.value, "Pode ir")
            return ""

        done = FeedbackView(page, self._app(), lambda: backs.append("voltar"), ok)
        done.build()
        done.field.value = "Pode ir"
        done.send_button.on_click(_Event(done.send_button))
        self.assertEqual(backs, [])
        self.assertTrue(done.success_card.visible)
        self._assert_same_card(done.success_card)
        self.assertEqual(done.success_icon.color, config.COLOR_ACCENT)
        self.assertTrue(done.sent_text.visible)
        self.assertEqual(done.sent_text.value, "Feedback enviado.")
        self.assertTrue(done.ok_button.visible)
        self.assertFalse(done.field.visible)
        self.assertFalse(done.guide_card.visible)
        self.assertFalse(done.field_card.visible)
        self.assertFalse(done.send_button.visible)
        done.ok_button.on_click(_Event(done.ok_button))
        self.assertEqual(backs, ["voltar"])

        other = FeedbackView(page, self._app(), lambda: backs.append("voltar"), ok)
        other.build()
        other.field.value = "Outro"
        other.send_button.on_click(_Event(other.send_button))
        self.assertEqual(backs, ["voltar"])
        other.back_button.on_click(_Event(other.back_button))
        self.assertEqual(backs, ["voltar", "voltar"])

    def test_feedback_button_sits_between_run_and_tutorial_at_the_same_size(self) -> None:
        app = AppInfo(
            id="com",
            nome="Com",
            tutorial_markdown_url="https://x/t.md",
        )
        page = _Page()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "apps", root / "installed.json")
            app_file = root / "com.exe"
            app_file.write_bytes(b"app")
            storage.set_installed("com", app_file, app.versao)
            detail = AppDetailView(
                page,
                app,
                storage,
                object(),
                feedback_enabled=True,
            )
            built = detail.build()
        self.assertEqual(
            _action_labels(built),
            ["Executar", "Feedback", "Tutorial", "Desinstalar"],
        )
        self.assertEqual(detail.feedback_button.icon, ft.Icons.CHAT_BUBBLE_OUTLINE)
        self.assertEqual(detail.feedback_button.height, detail.action_button.height)
        self.assertEqual(detail.feedback_button.width, detail.action_button.width)
        self.assertEqual(detail.feedback_button.height, detail.tutorial_button.height)
        self.assertEqual(detail.feedback_button.width, detail.tutorial_button.width)
        self.assertEqual(detail.feedback_button.style, detail.tutorial_button.style)
        self.assertIs(type(detail.feedback_button), type(detail.tutorial_button))


def _entry(usuario: str, quando: str, app_id: str, texto: str) -> FeedbackEntry:
    return FeedbackEntry(usuario=usuario, quando=quando, app_id=app_id, texto=texto)


class FeedbackListTests(unittest.TestCase):
    def test_newest_first_when_every_date_parses_otherwise_file_order(self) -> None:
        older = _entry("EMPRESA\\maria", "2026-11-01 09:00:00", "relatorio-producao", "antigo")
        newer = _entry("EMPRESA\\joao", "2026-11-03T15:04:05", "monitor-ativos", "novo")
        same = _entry("EMPRESA\\ana", "2026-11-03 15:04:05", "outro", "empate")
        ordered = ordered_feedback_entries([older, newer, same])
        self.assertEqual([item.texto for item in ordered], ["empate", "novo", "antigo"])
        self.assertEqual(feedback_screen_numbers([older, newer, same]), [1, 2, 3])
        self.assertEqual(feedback_user_label("EMPRESA\\ana"), "ana")
        self.assertEqual(same.usuario, "EMPRESA\\ana")
        self.assertEqual(
            feedback_entry_title(3, same, {}),
            "3 - ana - 2026-11-03 - outro",
        )
        self.assertEqual(
            feedback_entry_title(1, older, {"relatorio-producao": "Relatorio"}),
            "1 - maria - 2026-11-01 - Relatorio",
        )
        self.assertEqual(feedback_app_label(older, {"relatorio-producao": "Relatorio"}), "Relatorio")
        self.assertEqual(feedback_app_label(same, {}), "outro")

        broken = _entry("EMPRESA\\maria", "ontem", "relatorio-producao", "sem data")
        file_order = ordered_feedback_entries([older, broken, newer])
        self.assertEqual([item.texto for item in file_order], ["antigo", "sem data", "novo"])

    def test_view_lists_entries_without_edit_or_delete(self) -> None:
        form = FeedbackCatalogState(
            url=PASTED,
            entries=[
                _entry("EMPRESA\\maria", "2026-11-01 09:00:00", "relatorio-producao", "antigo"),
                _entry("EMPRESA\\joao", "2026-11-03 15:04:05", "sem-nome", "novo"),
            ],
        )
        select = ft.Container()
        edit = ft.Container()
        intro = bind_feedback_form(
            form,
            app_names={"relatorio-producao": "Relatorio de Producao"},
            on_save=lambda: None,
            on_pick=lambda: None,
            on_field=lambda _key, _value: None,
            on_reopen=lambda: None,
            select_holder=select,
            edit_holder=edit,
        )
        top = feedback_top_row(select, intro)
        self.assertIs(top.controls[0], select)
        self.assertIs(top.controls[1], intro)
        self.assertEqual(top.height, 280)
        self.assertNotEqual(top.expand, True)
        self.assertTrue(select.expand)
        self.assertTrue(intro.expand)
        self.assertEqual(select.height, 280)
        self.assertEqual(intro.height, 280)
        self.assertIsNone(select.width)
        self.assertIsNone(intro.width)
        self.assertIn("Selecionar ou adicionar", _texts(select))
        self.assertIn("Introdução", _texts(intro))
        self.assertNotIn("Feedbacks enviados", _texts(intro))
        labels = _texts(edit)
        self.assertNotIn("Texto", labels)
        self.assertNotIn("Usuario", labels)
        self.assertNotIn("Quando", labels)
        self.assertNotIn("App", labels)
        newest = "2 - joao - 2026-11-03 - sem-nome"
        oldest = "1 - maria - 2026-11-01 - Relatorio de Producao"
        self.assertLess(labels.index(newest), labels.index("novo"))
        self.assertNotIn("EMPRESA", newest)
        item_rows = []
        for node in _walk(edit):
            controls = getattr(node, "controls", None)
            if not isinstance(controls, list) or not controls:
                continue
            title = getattr(getattr(controls[0], "content", None), "value", None)
            if title in {newest, oldest}:
                item_rows.append(node)
        self.assertEqual(len(item_rows), 2)
        self.assertEqual(getattr(item_rows[0].controls[0].content, "value", None), newest)
        self.assertEqual(item_rows[0].controls[0].width, _ENTRY_TITLE_WIDTH)
        self.assertEqual(item_rows[1].controls[0].width, _ENTRY_TITLE_WIDTH)
        self.assertIn("novo", _texts(item_rows[0].controls[1]))
        self.assertLess(labels.index("novo"), labels.index(oldest))
        self.assertLess(labels.index(oldest), labels.index("antigo"))
        self.assertIn("Feedbacks enviados", labels)
        self.assertNotIn("Remover", labels)
        self.assertNotIn("Adicionar", labels)
        fields = [node for node in _walk(intro) if type(node).__name__ == "TextField"]
        self.assertEqual(len(fields), 2)
        self.assertEqual(fields[0].value, "")
        self.assertEqual(fields[1].value, "")
        self.assertIn("Confirmação", _texts(intro))
        self.assertTrue(fields[0].multiline)
        self.assertFalse(any(type(node).__name__ == "TextField" for node in _walk(edit)))
        self.assertTrue(edit.expand)
        self.assertIsNone(edit.width)
        self.assertIn("Link", _texts(select))
        self.assertIn("Pasta destino", _texts(select))
        self.assertIn("Escolher arquivo", _texts(select))

        locked = FeedbackCatalogState()
        bind_feedback_form(
            locked,
            app_names={},
            on_save=lambda: None,
            on_pick=lambda: None,
            on_field=lambda _key, _value: None,
            on_reopen=lambda: None,
            select_holder=select,
            edit_holder=edit,
        )
        self.assertIn("Selecione ou adicione o feedback.json para ver.", _texts(edit))

    def test_save_writes_intro_on_the_catalog_and_not_the_list(self) -> None:
        catalog = {
            "apps": [],
            "feedback": {"url": "https://antiga", "versao": "3", "introducao": "velha"},
        }
        text = json.dumps(catalog)
        calls: list[dict] = []

        def fetch() -> tuple[str, str]:
            return text, ""

        def refuse(data: dict) -> PublishOutcome:
            calls.append(json.loads(json.dumps(data)))
            return PublishOutcome(ok=False, message="Nao foi possivel atualizar a versao.")

        form = FeedbackCatalogState(
            url="  " + PASTED + "  ",
            versao="3",
            introducao="Pode falar do uso no dia a dia.",
            confirmacao="Obrigado pelo aviso.",
        )
        with patch("services.feedback.enviar_por_unique_id", side_effect=AssertionError("lista")):
            failed = save_feedback_pointer(
                form,
                expected_fingerprint="",
                fetch_text=fetch,
                upload_catalog=refuse,
            )
        self.assertFalse(failed.ok)
        self.assertEqual(calls[0]["feedback"]["url"], PASTED)
        self.assertEqual(calls[0]["feedback"]["versao"], "4")
        self.assertEqual(calls[0]["feedback"]["introducao"], "Pode falar do uso no dia a dia.")
        self.assertEqual(calls[0]["feedback"]["confirmacao"], "Obrigado pelo aviso.")
        self.assertNotIn("itens", calls[0]["feedback"])
        self.assertNotIn(":u:", calls[0]["feedback"]["url"])
        self.assertEqual(catalog["feedback"]["versao"], "3")
        self.assertEqual(catalog["feedback"]["introducao"], "velha")

        def accept(data: dict) -> PublishOutcome:
            calls.append(json.loads(json.dumps(data)))
            return PublishOutcome(
                ok=True,
                message="Catalogo publicado.",
                catalog=parse_catalog_dict(data),
            )

        saved = save_feedback_pointer(
            form,
            expected_fingerprint="",
            fetch_text=fetch,
            upload_catalog=accept,
        )
        self.assertTrue(saved.ok)
        self.assertEqual(saved.catalog.feedback.url, PASTED)
        self.assertEqual(saved.catalog.feedback.versao, "4")
        self.assertEqual(saved.catalog.feedback.introducao, "Pode falar do uso no dia a dia.")
        self.assertEqual(saved.catalog.feedback.confirmacao, "Obrigado pelo aviso.")

    def test_send_appends_a_list_and_drops_a_stale_guide(self) -> None:
        catalog = {
            "feedback": {
                "url": PASTED,
                "versao": "3",
                "introducao": "Pode agradecer ou apontar um bug.",
            }
        }
        text = json.dumps(catalog)
        bodies: list[str] = []
        old = {
            "usuario": "EMPRESA\\ana",
            "quando": "2026-11-01 09:00:00",
            "app_id": "outro",
            "texto": "antes",
            "nota": "fica",
        }

        def read() -> tuple[str, str]:
            return json.dumps({"introducao": "nao fica no arquivo", "itens": [old]}), ""

        def upload(body: str) -> tuple[bool, str]:
            bodies.append(body)
            return True, ""

        def fetch() -> tuple[str, str]:
            return text, ""

        def upload_catalog(data: dict) -> tuple[bool, str]:
            self.assertEqual(data["feedback"]["introducao"], "Pode agradecer ou apontar um bug.")
            return True, ""

        result = submit_app_feedback(
            app_id="relatorio-producao",
            texto="novo",
            feedback_url=PASTED,
            usuario="EMPRESA\\maria",
            now=datetime(2026, 11, 3, 18, 4, 5, tzinfo=timezone.utc),
            read_feedback=read,
            upload_feedback=upload,
            fetch_catalog=fetch,
            upload_catalog=upload_catalog,
        )
        self.assertTrue(result.ok)
        saved = json.loads(bodies[0])
        self.assertIsInstance(saved, list)
        self.assertEqual(saved[0], old)
        self.assertEqual(saved[1]["texto"], "novo")
        self.assertNotIn("introducao", saved[0])

    def test_feedback_tab_follows_dicas(self) -> None:
        row = ft.Row()
        host = ft.Container()
        holders = [ft.Container() for _ in range(10)]

        def noop(*_args, **_kwargs):
            return None

        bind_catalog_view(
            parse_catalog_dict({"apps": [{"id": "relatorio-producao", "nome": "Relatorio"}]}),
            PublishFormState(),
            StructureFormState(),
            "feedback",
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
            publish_layout=ft.Column(),
            estrutura_layout=ft.Row(),
            publish_select=holders[0],
            publish_edit=holders[1],
            structure_select=holders[2],
            structure_edit=holders[3],
            dicas_layout=ft.Column(),
            dicas_select=holders[4],
            dicas_edit=holders[5],
            links_layout=ft.Column(),
            links_select=holders[6],
            links_edit=holders[7],
            feedback=FeedbackCatalogState(
                url=PASTED,
                entries=[_entry("EMPRESA\\maria", "2026-11-03 15:04:05", "relatorio-producao", "novo")],
            ),
            feedback_app_names={"relatorio-producao": "Relatorio"},
            feedback_layout=ft.Column(),
            feedback_select=holders[8],
            feedback_edit=holders[9],
        )
        self.assertEqual(_texts(row), ["Publicar", "Estrutura", "Links", "Dicas", "Feedback"])
        host_texts = _texts(host)
        self.assertIn("1 - maria - 2026-11-03 - Relatorio", host_texts)
        top = host.content.controls[0]
        self.assertIs(top.controls[0], holders[8])
        self.assertIn("Introdução", _texts(top.controls[1]))
        self.assertIn("Feedbacks enviados", _texts(host.content.controls[1]))
        self.assertNotIn("Remover", host_texts)


class _DownloadResult:
    def __init__(self, ok: bool, path: Path | None) -> None:
        self.ok = ok
        self.path = path


class FeedbackVersionTests(unittest.TestCase):
    def test_same_version_does_not_download_and_different_does(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "feedback.json"
            version = root / "feedback.versao"
            body.write_text(
                json.dumps([
                    {
                        "usuario": "EMPRESA\\maria",
                        "quando": "2026-11-01 09:00:00",
                        "app_id": "relatorio-producao",
                        "texto": "velho",
                    }
                ]),
                encoding="utf-8",
            )
            version.write_text("2", encoding="utf-8")
            calls: list[str] = []

            def download(url: str, dest: Path) -> _DownloadResult:
                calls.append(url)
                dest.write_text(
                    json.dumps([
                        {
                            "usuario": "EMPRESA\\joao",
                            "quando": "2026-11-03 15:04:05",
                            "app_id": "monitor-ativos",
                            "texto": "novo",
                        }
                    ]),
                    encoding="utf-8",
                )
                return _DownloadResult(True, dest)

            same = CatalogData(feedback=FeedbackInfo(url=PASTED, versao="2"))
            self.assertFalse(
                should_download_feedback(
                    url=same.feedback.url,
                    versao=same.feedback.versao,
                    saved_versao="2",
                    local_exists=True,
                )
            )
            self.assertEqual(
                sync_feedback(same, download=download, feedback_path=body, version_path=version),
                "skipped",
            )
            self.assertEqual(calls, [])
            self.assertIn("velho", body.read_text(encoding="utf-8"))

            changed = CatalogData(feedback=FeedbackInfo(url=PASTED, versao="3"))
            self.assertTrue(
                should_download_feedback(
                    url=changed.feedback.url,
                    versao=changed.feedback.versao,
                    saved_versao="2",
                    local_exists=True,
                )
            )
            self.assertEqual(
                sync_feedback(changed, download=download, feedback_path=body, version_path=version),
                "downloaded",
            )
            self.assertEqual(calls, [PASTED])
            self.assertIn("novo", body.read_text(encoding="utf-8"))
            self.assertEqual(version.read_text(encoding="utf-8"), "3")

    def test_missing_url_or_version_does_not_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "feedback.json"
            version = root / "feedback.versao"
            body.write_text("[]\n", encoding="utf-8")
            version.write_text("1", encoding="utf-8")
            calls: list[str] = []

            def download(url: str, dest: Path) -> _DownloadResult:
                calls.append(url)
                return _DownloadResult(True, dest)

            for info in (
                FeedbackInfo(url="", versao="2"),
                FeedbackInfo(url=PASTED, versao=""),
                FeedbackInfo(),
            ):
                catalog = CatalogData(feedback=info)
                self.assertFalse(
                    should_download_feedback(
                        url=info.url,
                        versao=info.versao,
                        saved_versao="1",
                        local_exists=True,
                    )
                )
                self.assertEqual(
                    sync_feedback(
                        catalog,
                        download=download,
                        feedback_path=body,
                        version_path=version,
                    ),
                    "skipped",
                )
            self.assertEqual(calls, [])
            self.assertEqual(version.read_text(encoding="utf-8"), "1")
