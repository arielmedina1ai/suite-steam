"""Parser do tutorial, catalogo com e sem o bloco, e a montagem da UI."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flet as ft

import config
from catalog.provider import hydrate_catalog_images
from models import AppInfo, CatalogData, SetorInfo, parse_catalog_dict
from services.catalog_publish import (
    PublishFormState,
    original_upload_name,
    upsert_app_entry,
)
from services.storage import Storage
from services.tutorial import (
    apply_tutorial_uploads,
    cache_path_for,
    is_mp4_url,
    prepare_markdown_for_display,
    split_markdown_sections,
    tutorial_catalog_block,
    validate_tutorial_local_files,
    with_video_part,
)
from ui.app_detail_view import AppDetailView
from ui.home_view import build_home, build_setor_view
from ui.publish_view import bind_publish_form
from ui.tutorial_view import TutorialView


def _walk(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None and not isinstance(content, str):
        yield from _walk(content)
    controls = getattr(control, "controls", None) or []
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


class _Page:
    def __init__(self) -> None:
        self.threads = []

    def run_thread(self, fn) -> None:
        self.threads.append(fn)

    def update(self) -> None:
        return None


class TutorialParseTests(unittest.TestCase):
    def test_split_keeps_intro_and_h2_only(self) -> None:
        text = (
            "Antes do primeiro topico.\n\n"
            "## Instalar\n"
            "Passo 1\n"
            "```\n"
            "## isso fica no codigo\n"
            "```\n"
            "### detalhe\n"
            "\n"
            "## Usar\n"
            "Passo 2\n"
        )
        intro, sections = split_markdown_sections(text)
        self.assertEqual(intro, "Antes do primeiro topico.")
        self.assertEqual([title for title, _body in sections], ["Instalar", "Usar"])
        self.assertIn("## isso fica no codigo", sections[0][1])
        self.assertIn("### detalhe", sections[0][1])
        self.assertIn("Passo 2", sections[1][1])

    def test_public_image_stays_sharepoint_image_becomes_link(self) -> None:
        raw = (
            "![capa](https://empresa.sharepoint.com/sites/x/a.png)\n"
            "![ok](https://cdn.example.com/a.png)\n"
            "[video](https://cdn.example.com/demo.mp4)\n"
        )
        shown = prepare_markdown_for_display(raw)
        self.assertNotIn("![capa]", shown)
        self.assertIn("[capa](https://empresa.sharepoint.com/sites/x/a.png)", shown)
        self.assertIn("![ok](https://cdn.example.com/a.png)", shown)
        self.assertIn("[video](https://cdn.example.com/demo.mp4)", shown)

    def test_mp4_extension(self) -> None:
        self.assertTrue(is_mp4_url("https://x/pasta/instalar.mp4"))
        self.assertTrue(is_mp4_url("https://x/pasta/Instalar.MP4?web=1"))
        self.assertTrue(
            is_mp4_url(
                "https://empresa.sharepoint.com/:u:/r/sites/x/Documentos/tutoriais/instalar.mp4"
            )
        )
        self.assertFalse(is_mp4_url("https://x/pasta/clip.mkv"))
        self.assertFalse(is_mp4_url("https://x/pasta/clip.webm"))
        self.assertFalse(is_mp4_url(""))


class CatalogTutorialTests(unittest.TestCase):
    def test_catalog_without_tutorial(self) -> None:
        app = AppInfo.from_dict({"id": "monitor", "nome": "Monitor"})
        self.assertEqual(app.tutorial_markdown_url, "")
        self.assertEqual(app.tutorial_videos, [])
        self.assertFalse(app.has_tutorial)
        catalog = parse_catalog_dict({"apps": [{"id": "monitor", "nome": "Monitor"}]})
        self.assertFalse(catalog.apps[0].has_tutorial)

    def test_catalog_with_tutorial_drops_empty_url(self) -> None:
        app = AppInfo.from_dict(
            {
                "id": "relatorio",
                "nome": "Relatorio",
                "tutorial": {
                    "markdown_url": " https://x/t.md ",
                    "videos": [
                        {"titulo": "vazio", "url": "  "},
                        {"titulo": " Como instalar ", "url": " https://x/a.mp4 "},
                        "ignorar",
                    ],
                },
            }
        )
        self.assertEqual(app.tutorial_markdown_url, "https://x/t.md")
        self.assertEqual(app.tutorial_videos, [("Como instalar", "https://x/a.mp4")])
        self.assertTrue(app.has_tutorial)

    def test_example_catalog_mixes_apps(self) -> None:
        data = json.loads((ROOT / "catalog.example.json").read_text(encoding="utf-8"))
        catalog = parse_catalog_dict(data)
        by_id = {app.id: app for app in catalog.apps}
        self.assertTrue(by_id["relatorio-producao"].has_tutorial)
        self.assertEqual(by_id["relatorio-producao"].tutorial_videos[0][0], "Como instalar")
        self.assertFalse(by_id["monitor-ativos"].has_tutorial)

    def test_publish_block_and_hydrate_keep_tutorial(self) -> None:
        block = tutorial_catalog_block(
            " https://x/t.md ",
            [("Como instalar", " https://x/a.mp4 "), ("sem link", " ")],
        )
        self.assertEqual(
            block,
            {
                "markdown_url": "https://x/t.md",
                "videos": [{"titulo": "Como instalar", "url": "https://x/a.mp4"}],
            },
        )
        data = {
            "apps": [
                {
                    "id": "relatorio",
                    "nome": "Relatorio",
                    "imagem": "https://cdn.example.com/capa.png",
                    "icone": "https://cdn.example.com/icone.png",
                }
            ]
        }
        upsert_app_entry(
            data,
            {
                "id": "relatorio",
                "nome": "Relatorio",
                "imagem": "https://cdn.example.com/capa.png",
                "icone": "https://cdn.example.com/icone.png",
                "tutorial": block,
            },
        )
        self.assertEqual(data["apps"][0]["tutorial"], block)
        self.assertEqual(data["apps"][0]["imagem"], "https://cdn.example.com/capa.png")

        saved = json.dumps(data)
        catalog = parse_catalog_dict(json.loads(saved))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = (
                config.CATALOG_CACHE_DIR,
                config.CATALOG_IMAGES_DIR,
                config.CATALOG_IMAGES_MANIFEST,
            )
            config.CATALOG_CACHE_DIR = root
            config.CATALOG_IMAGES_DIR = root / "images"
            config.CATALOG_IMAGES_MANIFEST = root / "images_manifest.json"
            try:
                hydrate_catalog_images(catalog)
            finally:
                (
                    config.CATALOG_CACHE_DIR,
                    config.CATALOG_IMAGES_DIR,
                    config.CATALOG_IMAGES_MANIFEST,
                ) = previous
        app = catalog.apps[0]
        self.assertEqual(app.tutorial_markdown_url, "https://x/t.md")
        self.assertEqual(app.tutorial_videos, [("Como instalar", "https://x/a.mp4")])
        self.assertTrue(app.has_tutorial)
        again = parse_catalog_dict(json.loads(saved))
        self.assertEqual(again.apps[0].imagem, "https://cdn.example.com/capa.png")
        self.assertTrue(again.apps[0].has_tutorial)

    def test_publish_form_highlights_dirty_tutorial_fields(self) -> None:
        form = PublishFormState(
            tutorial_markdown_url="https://x/t.md",
            tutorial_videos=[("Como instalar", "https://x/a.mp4")],
        )
        form.capture_baseline()
        self.assertFalse(form.is_changed("tutorial_markdown_url"))
        self.assertFalse(form.is_changed("tutorial_videos"))
        self.assertFalse(form.video_part_changed(0, "url"))
        form.tutorial_markdown_url = "https://x/outro.md"
        form.tutorial_videos.append(("", ""))
        self.assertTrue(form.is_changed("tutorial_markdown_url"))
        self.assertTrue(form.is_changed("tutorial_videos"))
        self.assertTrue(form.video_part_changed(1, "titulo"))
        saved = tutorial_catalog_block(form.tutorial_markdown_url, form.tutorial_videos)
        self.assertEqual(saved["videos"], [{"titulo": "Como instalar", "url": "https://x/a.mp4"}])


class TutorialUiTests(unittest.TestCase):
    def test_badge_and_button_follow_content(self) -> None:
        plain = AppInfo(id="sem", nome="Sem", descricao="d", versao="1")
        with_tutorial = AppInfo(
            id="com",
            nome="Com",
            descricao="d",
            versao="1",
            tutorial_markdown_url="https://x/t.md",
            tutorial_videos=[("Como instalar", "https://x/a.mp4")],
        )
        home = build_home(
            [plain, with_tutorial],
            lambda _id: None,
            gerencia=None,
            favorite_ids=set(),
            on_toggle_favorite=lambda _id: None,
        )
        setor = build_setor_view(
            SetorInfo(id="s", nome="Setor"),
            [plain, with_tutorial],
            lambda _id: None,
            favorite_ids=set(),
            on_toggle_favorite=lambda _id: None,
        )
        self.assertEqual(_texts(home).count("Tutorial"), 1)
        self.assertEqual(_texts(setor).count("Tutorial"), 1)

        page = _Page()
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "apps", Path(tmp) / "installed.json")
            detail = AppDetailView(page, with_tutorial, storage, object()).build()
            hidden = AppDetailView(page, plain, storage, object()).build()
        self.assertEqual(
            _action_labels(detail),
            ["Baixar / Instalar", "Tutorial", "Atualizar versao", "Desinstalar"],
        )
        self.assertNotIn("Tutorial", _action_labels(hidden))

    def test_player_switches_one_local_mp4(self) -> None:
        app = AppInfo(
            id="com",
            nome="Com",
            tutorial_videos=[
                ("Errado", "https://x/clip.mkv"),
                ("Certo", "https://x/instalar.mp4"),
            ],
        )
        page = _Page()
        view = TutorialView(page, app, lambda: None)
        view.build()
        self.assertIsNotNone(view.player)
        self.assertEqual(view.player.aspect_ratio, 16 / 9)
        self.assertEqual(view.player.width, 480)
        self.assertEqual(view.player.height, 270)
        self.assertEqual(list(view.player.playlist), [])
        view._on_pick(0)
        self.assertEqual(view.status.value, "Somente .mp4.")
        self.assertEqual(list(view.player.playlist), [])
        self.assertEqual(page.threads, [])
        view._show_local(Path("/tmp/um.mp4"))
        view._show_local(Path("/tmp/dois.mp4"))
        self.assertEqual(len(view.player.playlist), 1)
        self.assertTrue(str(view.player.playlist[0].resource).endswith("dois.mp4"))


class TutorialUploadTests(unittest.TestCase):
    def test_pasted_link_is_saved_and_not_uploaded(self) -> None:
        def upload(_path, _msg):
            raise AssertionError("link colado nao envia arquivo")

        block, err = apply_tutorial_uploads(
            " https://x/t.md ",
            "",
            [("Como instalar", " https://x/a.mp4 ", ""), ("", "  ", "")],
            upload,
        )
        self.assertEqual(err, "")
        self.assertEqual(block["markdown_url"], "https://x/t.md")
        self.assertEqual(
            block["videos"],
            [{"titulo": "Como instalar", "url": "https://x/a.mp4"}],
        )
        self.assertNotIn("\\", json.dumps(block))

    def test_chosen_file_replaces_old_link_and_keeps_original_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            md = root / "Guia do Usuario.md"
            mp4 = root / "instalar.mp4"
            md.write_text("# guia", encoding="utf-8")
            mp4.write_bytes(b"mp4")
            calls = []

            def upload(path, msg):
                calls.append((Path(path), msg))
                name = original_upload_name(Path(path))
                return True, f"https://empresa.sharepoint.com/:u:/r/sites/x/Pasta/{name}"

            block, err = apply_tutorial_uploads(
                "https://x/antigo.md",
                str(md),
                [("Como instalar", "https://x/antigo.mp4", str(mp4))],
                upload,
            )
        self.assertEqual(err, "")
        self.assertEqual([msg for _path, msg in calls], ["Enviando markdown...", "Enviando video..."])
        self.assertEqual(original_upload_name(calls[0][0]), "Guia do Usuario.md")
        self.assertEqual(original_upload_name(calls[1][0]), "instalar.mp4")
        self.assertEqual(
            block["markdown_url"],
            "https://empresa.sharepoint.com/:u:/r/sites/x/Pasta/Guia do Usuario.md",
        )
        self.assertEqual(
            block["videos"],
            [{
                "titulo": "Como instalar",
                "url": "https://empresa.sharepoint.com/:u:/r/sites/x/Pasta/instalar.mp4",
            }],
        )
        dumped = json.dumps(block)
        self.assertNotIn(str(md), dumped)
        self.assertNotIn(str(mp4), dumped)

    def test_bad_extension_and_missing_file_are_rejected_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_md = Path(tmp) / "ausente.md"
            missing_mp4 = Path(tmp) / "ausente.mp4"
            self.assertEqual(validate_tutorial_local_files(str(Path(tmp) / "nota.txt"), []), "Somente .md.")
            self.assertEqual(
                validate_tutorial_local_files("", [("T", "https://x/a.mp4", str(Path(tmp) / "clip.mkv"))]),
                "Somente .mp4.",
            )
            self.assertEqual(validate_tutorial_local_files(str(missing_md), []), "Arquivo de markdown nao encontrado.")
            self.assertEqual(
                validate_tutorial_local_files("", [("T", "", str(missing_mp4))]),
                "Arquivo de video nao encontrado.",
            )
            calls = []

            def upload(path, msg):
                calls.append((path, msg))
                return True, "https://x/nao"

            block, err = apply_tutorial_uploads("", "", [("T", "https://x/old.mp4", str(Path(tmp) / "clip.mkv"))], upload)
        self.assertEqual(err, "Somente .mp4.")
        self.assertIsNone(block)
        self.assertEqual(calls, [])

    def test_upload_drops_the_cached_copy_of_the_new_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = (
                config.TUTORIAL_CACHE_DIR,
            )
            config.TUTORIAL_CACHE_DIR = root / "cache"
            try:
                md = root / "guia.md"
                md.write_text("# novo", encoding="utf-8")
                url = "https://empresa.sharepoint.com/:u:/r/sites/x/Pasta/guia.md"
                cached = cache_path_for(url, ".md")
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text("velho", encoding="utf-8")

                def upload(_path, _msg):
                    return True, url

                block, err = apply_tutorial_uploads("https://x/outro.md", str(md), [], upload)
                self.assertEqual(err, "")
                self.assertEqual(block["markdown_url"], url)
                self.assertFalse(cached.exists())
            finally:
                (config.TUTORIAL_CACHE_DIR,) = previous

    def test_title_edit_keeps_the_local_file(self) -> None:
        row = with_video_part(("Como instalar", "https://x/a.mp4", "/tmp/instalar.mp4"), "titulo", "Passo 1")
        self.assertEqual(row, ("Passo 1", "https://x/a.mp4", "/tmp/instalar.mp4"))
        row = with_video_part(row, "url", "https://x/b.mp4")
        self.assertEqual(row[2], "/tmp/instalar.mp4")
        saved = tutorial_catalog_block("", [row])
        self.assertEqual(saved["videos"], [{"titulo": "Passo 1", "url": "https://x/b.mp4"}])

    def test_form_highlights_local_file_until_cleared(self) -> None:
        form = PublishFormState(
            tutorial_markdown_url="https://x/t.md",
            tutorial_videos=[("Como instalar", "https://x/a.mp4")],
        )
        form.capture_baseline()
        self.assertFalse(form.is_changed("tutorial_markdown_path"))
        self.assertFalse(form.video_part_changed(0, "local"))
        form.tutorial_markdown_path = "/tmp/guia.md"
        form.tutorial_videos[0] = ("Como instalar", "https://x/a.mp4", "/tmp/instalar.mp4")
        self.assertTrue(form.is_changed("tutorial_markdown_path"))
        self.assertTrue(form.video_part_changed(0, "local"))
        self.assertFalse(form.video_part_changed(0, "url"))
        form.tutorial_markdown_path = ""
        form.tutorial_videos = [("Como instalar", "https://x/a.mp4")]
        form.capture_baseline()
        self.assertFalse(form.is_changed("tutorial_markdown_path"))
        self.assertFalse(form.is_changed("tutorial_videos"))


class TutorialPublishUiTests(unittest.TestCase):
    def test_fields_show_catalog_url_and_local_file_hint(self) -> None:
        md_url = "https://empresa.sharepoint.com/sites/x/Documentos/Pasta/guia.md"
        video_url = "https://empresa.sharepoint.com/sites/x/Documentos/Pasta/antigo.mp4"
        form = PublishFormState(
            tutorial_markdown_url=md_url,
            tutorial_videos=[("Como instalar", video_url)],
        )
        form.capture_baseline()
        form.tutorial_markdown_path = "/home/me/docs/Guia do Usuario.md"
        form.tutorial_videos[0] = ("Como instalar", video_url, "/home/me/clips/instalar.mp4")
        select_holder = ft.Container()
        edit_holder = ft.Container()
        bind_publish_form(
            CatalogData(),
            form,
            on_select_app=lambda _value: None,
            on_save=lambda: None,
            on_cancel=lambda: None,
            on_pick=lambda _kind: None,
            on_field=lambda _key, _value: None,
            on_reopen=lambda: None,
            select_holder=select_holder,
            edit_holder=edit_holder,
        )
        shown = _texts(edit_holder)
        self.assertIn(md_url, shown)
        self.assertIn(video_url, shown)
        self.assertIn("Arquivo local a enviar (nome original): Guia do Usuario.md", shown)
        self.assertIn("Arquivo local a enviar (nome original): instalar.mp4", shown)
        self.assertNotIn("/home/me/docs/Guia do Usuario.md", shown)
        self.assertNotIn("/home/me/clips/instalar.mp4", shown)
        self.assertTrue(_row_highlighted(edit_holder, "Markdown"))
        self.assertTrue(_row_highlighted(edit_holder, "Videos"))


def _row_highlighted(control, label: str) -> bool:
    for node in _walk(control):
        if getattr(node, "bgcolor", None) != "#2A3820":
            continue
        if label in _texts(node):
            return True
    return False


def _action_labels(control) -> list[str]:
    for node in _walk(control):
        controls = getattr(node, "controls", None) or []
        labels = []
        for child in controls:
            content = getattr(child, "content", None)
            if isinstance(content, str):
                labels.append(content)
        if "Baixar / Instalar" in labels or "Executar" in labels:
            return labels
    return []


if __name__ == "__main__":
    unittest.main()
