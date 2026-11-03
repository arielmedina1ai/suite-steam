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

from models import AppInfo, FeedbackInfo, parse_catalog_dict
from services.catalog_publish import PublishOutcome
from services.feedback import publish_feedback_block, submit_app_feedback
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
        self.assertEqual(set(pointer), set(catalog["dicas"]))
        self.assertIn("download.aspx?UniqueId=", pointer["url"])
        self.assertTrue(str(pointer["versao"]).strip())
        body = json.loads((ROOT / "feedback.example.json").read_text(encoding="utf-8"))
        self.assertIsInstance(body, list)
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
        field_at = built.controls.index(view.field)
        send_at = built.controls.index(view.send_button)
        self.assertEqual(send_at, field_at + 1)

    def test_failure_keeps_the_text_and_success_waits_for_ok_or_back(self) -> None:
        page = _Page()
        backs: list[str] = []

        def fail(_texto: str) -> str:
            return "Nao foi possivel enviar."

        view = FeedbackView(page, self._app(), lambda: backs.append("voltar"), fail)
        view.build()
        view.field.value = "Texto que fica"
        view.send_button.on_click(_Event(view.send_button))
        self.assertEqual(backs, [])
        self.assertEqual(view.field.value, "Texto que fica")
        self.assertTrue(view.field.visible)
        self.assertEqual(view.error_text.value, "Nao foi possivel enviar.")
        self.assertTrue(view.error_text.visible)
        self.assertFalse(view.sent_text.visible)
        self.assertFalse(view.ok_button.visible)

        def ok(_texto: str) -> str:
            return ""

        done = FeedbackView(page, self._app(), lambda: backs.append("voltar"), ok)
        done.build()
        done.field.value = "Pode ir"
        done.send_button.on_click(_Event(done.send_button))
        self.assertEqual(backs, [])
        self.assertTrue(done.sent_text.visible)
        self.assertEqual(done.sent_text.value, "Feedback enviado.")
        self.assertTrue(done.ok_button.visible)
        self.assertFalse(done.field.visible)
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
