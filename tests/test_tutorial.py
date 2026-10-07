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
    tutorial_remote_name,
    upsert_app_entry,
)
from services.download_manager import DownloadManager, DownloadOutcome
from services.sharepoint_manager import SharePointResult
from services.storage import Storage
from services.tutorial import (
    apply_tutorial_uploads,
    bump_version,
    cache_path_for,
    download_to_cache,
    download_tutorial_assets,
    form_videos_from_catalog,
    is_mp4_url,
    prepare_markdown_for_display,
    remote_filename_from_url,
    split_markdown_sections,
    tutorial_catalog_block,
    validate_tutorial_local_files,
    video_row,
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


def _badge_for(control, label: str):
    for node in _walk(control):
        content = getattr(node, "content", None)
        if isinstance(content, ft.Text) and content.value == label:
            return node, content
    raise AssertionError(f"badge {label!r} nao encontrado")


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
        self.assertEqual(app.tutorial_markdown_versao, "1")
        self.assertEqual(app.tutorial_videos, [("Como instalar", "https://x/a.mp4", "1")])
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
                "markdown_versao": "1",
                "videos": [{"titulo": "Como instalar", "url": "https://x/a.mp4", "versao": "1"}],
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
        self.assertEqual(app.tutorial_videos, [("Como instalar", "https://x/a.mp4", "1")])
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
        self.assertEqual(
            saved["videos"],
            [{"titulo": "Como instalar", "url": "https://x/a.mp4", "versao": "1"}],
        )


class TutorialUiTests(unittest.TestCase):
    def test_badge_and_button_only_after_install(self) -> None:
        plain = AppInfo(id="sem", nome="Sem", descricao="d", versao="1")
        with_tutorial = AppInfo(
            id="com",
            nome="Com",
            descricao="d",
            versao="1",
            tutorial_markdown_url="https://x/t.md",
            tutorial_videos=[("Como instalar", "https://x/a.mp4", "1")],
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
        self.assertEqual(_texts(home).count("Tutorial"), 0)
        self.assertEqual(_texts(setor).count("Tutorial"), 0)
        installed = {"com", "sem"}
        home_on = build_home(
            [plain, with_tutorial],
            lambda _id: None,
            gerencia=None,
            favorite_ids=set(),
            on_toggle_favorite=lambda _id: None,
            installed_ids=installed,
        )
        setor_on = build_setor_view(
            SetorInfo(id="s", nome="Setor"),
            [plain, with_tutorial],
            lambda _id: None,
            favorite_ids=set(),
            on_toggle_favorite=lambda _id: None,
            installed_ids=installed,
        )
        self.assertEqual(_texts(home_on).count("Tutorial"), 1)
        self.assertEqual(_texts(setor_on).count("Tutorial"), 1)
        for view in (home_on, setor_on):
            type_box, type_text = _badge_for(view, "EXE")
            tutorial_box, tutorial_text = _badge_for(view, "Tutorial")
            self.assertEqual(tutorial_box.bgcolor, config.COLOR_PRIMARY_DARK)
            self.assertEqual(tutorial_text.color, config.COLOR_ACCENT)
            self.assertEqual(tutorial_box.bgcolor, type_box.bgcolor)
            self.assertEqual(tutorial_text.color, type_text.color)
            self.assertEqual(tutorial_text.size, type_text.size)
            self.assertEqual(tutorial_text.size, 11)

        page = _Page()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "apps", root / "installed.json")
            before = AppDetailView(page, with_tutorial, storage, object()).build()
            plain_file = root / "sem.exe"
            plain_file.write_bytes(b"app")
            storage.set_installed("sem", plain_file, "1")
            installed_plain = AppDetailView(page, plain, storage, object()).build()
            app_file = root / "com.exe"
            app_file.write_bytes(b"app")
            storage.set_installed("com", app_file, "1")
            detail = AppDetailView(page, with_tutorial, storage, object()).build()
        self.assertEqual(_action_labels(before), ["Baixar / Instalar"])
        self.assertNotIn("Tutorial", _action_labels(installed_plain))
        self.assertEqual(_action_labels(detail), ["Executar", "Tutorial", "Desinstalar"])

    def test_videos_stack_title_above_player(self) -> None:
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
        page_col = view.build()
        self.assertIs(page_col.controls[-1], view.markdown_host)
        self.assertIs(page_col.controls[-2], view.videos_host)
        self.assertIsInstance(view.videos_host, ft.Column)
        self.assertEqual(len(view.players), 2)
        self.assertEqual(len(view.videos_host.controls), 2)
        titles = []
        for index, block in enumerate(view.videos_host.controls):
            player = view.players[index]
            self.assertEqual(player.aspect_ratio, 16 / 9)
            self.assertEqual(player.width, 480)
            self.assertEqual(player.height, 270)
            self.assertIsNotNone(player.controls)
            self.assertIsNot(player.show_controls, False)
            self.assertIsInstance(block, ft.Column)
            title = block.controls[0]
            frame = block.controls[1]
            self.assertIsInstance(title, ft.Text)
            self.assertEqual(title.text_align, ft.TextAlign.CENTER)
            self.assertIs(frame.content, player)
            titles.append(title.value)
            for node in _walk(block):
                if node is player:
                    continue
                self.assertIsNone(getattr(node, "on_click", None))
                self.assertNotIn(
                    type(node).__name__,
                    ("IconButton", "ElevatedButton", "FilledButton", "OutlinedButton", "TextButton"),
                )
        self.assertEqual(titles, ["Errado", "Certo"])
        self.assertEqual(view.slots[0].status.value, "Somente .mp4.")
        self.assertEqual(list(view.players[0].playlist), [])
        self.assertEqual(len(page.threads), 1)
        view._show_local(view.slots[1], Path("/tmp/um.mp4"))
        view._show_local(view.slots[1], Path("/tmp/dois.mp4"))
        self.assertEqual(len(view.players[1].playlist), 1)
        self.assertTrue(str(view.players[1].playlist[0].resource).endswith("dois.mp4"))
        self.assertEqual(list(view.players[0].playlist), [])


class TutorialUploadTests(unittest.TestCase):
    def test_markdown_remote_name_is_the_picked_file(self) -> None:
        cache = Path(r"C:\Users\me\AppData\Local\SuiteApps\catalog\tutorials") / (
            "ab12cd34ef567890abcd.md"
        )
        picked = Path(r"C:\Users\me\Desktop\Meu Tutorial.md")
        self.assertEqual(tutorial_remote_name(picked, ""), "Meu Tutorial.md")
        self.assertEqual(tutorial_remote_name(cache, "Meu Tutorial.md"), "Meu Tutorial.md")
        self.assertEqual(tutorial_remote_name(picked, cache.name), "Meu Tutorial.md")
        self.assertEqual(original_upload_name(picked), "Meu Tutorial.md")
        self.assertNotEqual(tutorial_remote_name(cache, "Meu Tutorial.md"), cache.name)

        form = PublishFormState(
            tutorial_markdown_path=str(cache),
            tutorial_markdown_upload_name="Meu Tutorial.md",
        )
        from services.catalog_publish import _tutorial_dest_name

        self.assertEqual(_tutorial_dest_name(form, cache), "Meu Tutorial.md")

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
        self.assertEqual(block["markdown_versao"], "1")
        self.assertEqual(
            block["videos"],
            [{"titulo": "Como instalar", "url": "https://x/a.mp4", "versao": "1"}],
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
        self.assertEqual(block["markdown_versao"], "2")
        self.assertEqual(
            block["videos"],
            [{
                "titulo": "Como instalar",
                "url": "https://empresa.sharepoint.com/:u:/r/sites/x/Pasta/instalar.mp4",
                "versao": "2",
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
                cached_v1 = cache_path_for(url, ".md", "1")
                cached_v2 = cache_path_for(url, ".md", "2")
                self.assertNotEqual(cached_v1, cached_v2)
                cached_v1.parent.mkdir(parents=True, exist_ok=True)
                cached_v1.write_text("velho", encoding="utf-8")

                def upload(_path, _msg):
                    return True, url

                block, err = apply_tutorial_uploads("https://x/outro.md", str(md), [], upload)
                self.assertEqual(err, "")
                self.assertEqual(block["markdown_url"], url)
                self.assertEqual(block["markdown_versao"], "2")
                self.assertTrue(cached_v1.is_file())
                self.assertEqual(cached_v1.read_text(encoding="utf-8"), "velho")
                self.assertFalse(cached_v2.exists())
            finally:
                (config.TUTORIAL_CACHE_DIR,) = previous

    def test_title_edit_keeps_the_local_file(self) -> None:
        row = with_video_part(("Como instalar", "https://x/a.mp4", "/tmp/instalar.mp4"), "titulo", "Passo 1")
        self.assertEqual(row, ("Passo 1", "https://x/a.mp4", "/tmp/instalar.mp4", "", "1"))
        row = with_video_part(row, "url", "https://x/b.mp4")
        self.assertEqual(row[2], "/tmp/instalar.mp4")
        row = with_video_part(row, "nome", "instalar.mp4")
        self.assertEqual(row[2], "/tmp/instalar.mp4")
        self.assertEqual(row[3], "instalar.mp4")
        self.assertEqual(row[4], "1")
        saved = tutorial_catalog_block("", [row])
        self.assertEqual(saved["videos"], [{"titulo": "Passo 1", "url": "https://x/b.mp4", "versao": "1"}])

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
        video_fields = [
            node
            for node in _walk(edit_holder)
            if type(node).__name__ == "TextField" and getattr(node, "value", "") == video_url
        ]
        self.assertEqual(len(video_fields), 1)
        self.assertFalse(getattr(video_fields[0], "read_only", False))
        self.assertIsNotNone(video_fields[0].on_change)
        self.assertTrue(any(node.__class__.__name__ == "OutlinedButton" and getattr(node, "content", "") == "Escolher arquivo" for node in _walk(edit_holder)))
        self.assertTrue(_row_highlighted(edit_holder, "Markdown"))
        self.assertTrue(_row_highlighted(edit_holder, "Videos"))

    def test_video_link_can_be_typed_and_pasted_as_written(self) -> None:
        pasted = "https://empresa.sharepoint.com/sites/x/GuiXT/outro.mkv"
        form = PublishFormState(
            tutorial_videos=[("Como instalar", "https://x/a.mp4")],
        )
        form.capture_baseline()

        def on_field(key: str, value: str) -> None:
            if not key.startswith("tutorial_video_url:"):
                return
            idx = int(key.split(":", 1)[1])
            form.tutorial_videos[idx] = with_video_part(form.tutorial_videos[idx], "url", value)

        edit_holder = ft.Container()
        bind_publish_form(
            CatalogData(),
            form,
            on_select_app=lambda _value: None,
            on_save=lambda: None,
            on_cancel=lambda: None,
            on_pick=lambda _kind: None,
            on_field=on_field,
            on_reopen=lambda: None,
            select_holder=ft.Container(),
            edit_holder=edit_holder,
        )
        fields = [
            node
            for node in _walk(edit_holder)
            if type(node).__name__ == "TextField" and getattr(node, "value", "") == "https://x/a.mp4"
        ]
        self.assertEqual(len(fields), 1)
        field = fields[0]
        self.assertFalse(field.read_only)
        self.assertIsNotNone(field.on_change)
        self.assertIsNotNone(field.on_blur)

        class _Event:
            def __init__(self, control, data: str) -> None:
                self.control = control
                self.data = data

        field.on_change(_Event(field, pasted))
        self.assertEqual(video_row(form.tutorial_videos[0])[1], pasted)
        self.assertEqual(field.value, pasted)

        def refuse(_path, _msg):
            raise AssertionError("link colado nao envia arquivo")

        block, err = apply_tutorial_uploads("", "", form.tutorial_videos, refuse)
        self.assertEqual(err, "")
        self.assertEqual(block["videos"], [{"titulo": "Como instalar", "url": pasted, "versao": "1"}])
        self.assertNotEqual(err, "Somente .mp4.")


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
            if getattr(child, "visible", True) is False:
                continue
            content = getattr(child, "content", None)
            if isinstance(content, str):
                labels.append(content)
        if "Baixar / Instalar" in labels or "Executar" in labels:
            return labels
    return []


class TutorialVersionTests(unittest.TestCase):
    def test_stored_version_roundtrips_and_is_not_a_path(self) -> None:
        app = AppInfo.from_dict(
            {
                "id": "relatorio",
                "nome": "Relatorio",
                "tutorial": {
                    "markdown_url": "https://x/t.md",
                    "markdown_versao": "4",
                    "videos": [{"titulo": "Como instalar", "url": "https://x/a.mp4", "versao": "7"}],
                },
            }
        )
        self.assertEqual(app.tutorial_markdown_versao, "4")
        self.assertEqual(app.tutorial_videos, [("Como instalar", "https://x/a.mp4", "7")])
        rows = form_videos_from_catalog(app.tutorial_videos)
        self.assertEqual(rows, [("Como instalar", "https://x/a.mp4", "", "", "7")])
        _titulo, _url, local, _nome, versao = video_row(rows[0])
        self.assertEqual(local, "")
        self.assertEqual(versao, "7")

    def test_paste_keeps_version_and_new_file_bumps_it(self) -> None:
        self.assertEqual(bump_version("3"), "4")
        self.assertEqual(bump_version(""), "2")

        def refuse(_path, _msg):
            raise AssertionError("link colado nao envia arquivo")

        pasted, err = apply_tutorial_uploads(
            "https://x/t.md",
            "",
            [("Como instalar", "https://x/a.mp4", "", "", "3")],
            refuse,
            markdown_versao="3",
        )
        self.assertEqual(err, "")
        self.assertEqual(pasted["markdown_versao"], "3")
        self.assertEqual(pasted["videos"][0]["versao"], "3")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            md = root / "guia.md"
            mp4 = root / "instalar.mp4"
            md.write_text("# guia", encoding="utf-8")
            mp4.write_bytes(b"mp4")

            def upload(_path, _msg):
                return True, "https://x/novo.md" if Path(_path).suffix == ".md" else "https://x/novo.mp4"

            block, err = apply_tutorial_uploads(
                "https://x/t.md",
                str(md),
                [("Como instalar", "https://x/a.mp4", str(mp4), "instalar.mp4", "3")],
                upload,
                markdown_versao="3",
            )
        self.assertEqual(err, "")
        self.assertEqual(block["markdown_versao"], "4")
        self.assertEqual(block["videos"][0]["versao"], "4")
        self.assertEqual(block["videos"][0]["titulo"], "Como instalar")

    def test_cache_key_follows_version_and_failure_is_not_saved(self) -> None:
        import services.tutorial as tutorial_mod

        with tempfile.TemporaryDirectory() as tmp:
            previous = config.TUTORIAL_CACHE_DIR
            config.TUTORIAL_CACHE_DIR = Path(tmp) / "cache"
            calls = []

            def fake_download(link, pasta_destino, nome_arquivo, progress=None):
                calls.append((link, nome_arquivo))
                if "falha" in link:
                    partial = Path(pasta_destino) / nome_arquivo
                    partial.parent.mkdir(parents=True, exist_ok=True)
                    partial.write_text("parcial", encoding="utf-8")
                    return SharePointResult(ok=False, path=partial, message="rede")
                path = Path(pasta_destino) / nome_arquivo
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"{nome_arquivo}:{len(calls)}", encoding="utf-8")
                return SharePointResult(ok=True, path=path, message="ok")

            original = tutorial_mod.baixar_do_sharepoint
            tutorial_mod.baixar_do_sharepoint = fake_download
            try:
                url = "https://x/guia.md"
                first, err = download_to_cache(url, ".md", version="1")
                second, err2 = download_to_cache(url, ".md", version="1")
                third, err3 = download_to_cache(url, ".md", version="2")
                self.assertEqual(err, "")
                self.assertEqual(err2, "")
                self.assertEqual(err3, "")
                self.assertEqual(first, second)
                self.assertNotEqual(first, third)
                self.assertEqual([nome for link, nome in calls if link == url], ["guia.md", "guia.md"])
                self.assertNotEqual(first.name, "guia.md")
                self.assertNotIn(first.name, [nome for _link, nome in calls])
                self.assertTrue(third.is_file())
                self.assertNotEqual(first.read_text(encoding="utf-8"), third.read_text(encoding="utf-8"))

                failed, fail_err = download_to_cache("https://x/falha.md", ".md", version="1")
                self.assertIsNone(failed)
                self.assertIn("rede", fail_err)
                self.assertFalse(cache_path_for("https://x/falha.md", ".md", "1").exists())

                app = AppInfo(
                    id="com",
                    nome="Com",
                    tutorial_markdown_url="https://x/falha.md",
                    tutorial_markdown_versao="1",
                    tutorial_videos=[
                        ("Como instalar", "https://x/instalar.mp4", "4"),
                        ("ruim", "https://x/clip.mkv", "1"),
                    ],
                )
                note, errors = download_tutorial_assets(app)
                self.assertEqual(note, "")
                self.assertTrue(any("nao foi salvo" in item for item in errors))
                self.assertFalse(any("Tutorial baixado" in item for item in errors))
                self.assertTrue(cache_path_for("https://x/instalar.mp4", ".mp4", "4").is_file())
                self.assertFalse(any(link.endswith(".mkv") for link, _nome in calls))
            finally:
                tutorial_mod.baixar_do_sharepoint = original
                config.TUTORIAL_CACHE_DIR = previous

    def test_install_downloads_tutorial_with_the_app(self) -> None:
        import services.download_manager as download_mod
        import services.tutorial as tutorial_mod

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = config.TUTORIAL_CACHE_DIR
            config.TUTORIAL_CACHE_DIR = root / "tutorials"
            storage = Storage(root / "apps", root / "installed.json")

            def fake_app(link, pasta_destino, nome_arquivo, progress=None):
                path = Path(pasta_destino) / nome_arquivo
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"exe")
                return SharePointResult(ok=True, path=path, message="Download concluido.")

            def fake_tutorial(link, pasta_destino, nome_arquivo, progress=None):
                if link.endswith(".md"):
                    partial = Path(pasta_destino) / nome_arquivo
                    partial.parent.mkdir(parents=True, exist_ok=True)
                    partial.write_text("parcial", encoding="utf-8")
                    return SharePointResult(ok=False, path=partial, message="timeout")
                path = Path(pasta_destino) / nome_arquivo
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"mp4")
                return SharePointResult(ok=True, path=path, message="ok")

            original_app = download_mod.baixar_do_sharepoint
            original_tutorial = tutorial_mod.baixar_do_sharepoint
            download_mod.baixar_do_sharepoint = fake_app
            tutorial_mod.baixar_do_sharepoint = fake_tutorial
            try:
                app = AppInfo(
                    id="relatorio",
                    nome="Relatorio",
                    download_url="https://x/app.xlsm",
                    versao="1.2.0",
                    tutorial_markdown_url="https://x/guia.md",
                    tutorial_markdown_versao="3",
                    tutorial_videos=[("Como instalar", "https://x/instalar.mp4", "5")],
                )
                result = DownloadManager(storage).download(app)
                self.assertEqual(result.outcome, DownloadOutcome.SUCCESS)
                self.assertIn("Tutorial (markdown) nao foi salvo.", result.message)
                self.assertNotIn("Tutorial baixado.", result.message)
                self.assertIn("Download concluido.", result.message)
                self.assertTrue(cache_path_for("https://x/instalar.mp4", ".mp4", "5").is_file())
                self.assertFalse(cache_path_for("https://x/guia.md", ".md", "3").exists())
                from models import InstallStatus

                self.assertEqual(storage.get_state(app.id).status, InstallStatus.INSTALLED)
                names = []

                def recording(link, pasta_destino, nome_arquivo=None, progress=None):
                    names.append(nome_arquivo)
                    path = Path(pasta_destino) / (nome_arquivo or "arquivo")
                    path.write_text("ok", encoding="utf-8")
                    return SharePointResult(ok=True, path=path, message="ok")

                tutorial_mod.baixar_do_sharepoint = recording
                again, again_err = download_to_cache(
                    "https://x/instalar.mp4",
                    ".mp4",
                    version="5",
                )
                self.assertEqual(again_err, "")
                self.assertEqual(again, cache_path_for("https://x/instalar.mp4", ".mp4", "5"))
                self.assertEqual(names, [])
            finally:
                download_mod.baixar_do_sharepoint = original_app
                tutorial_mod.baixar_do_sharepoint = original_tutorial
                config.TUTORIAL_CACHE_DIR = previous


    def test_download_asks_sharepoint_for_the_catalog_name(self) -> None:
        import services.tutorial as tutorial_mod

        url = (
            "https://empresa.sharepoint.com/:u:/r/sites/x/"
            "Documentos%20Compartilhados/GuiXT/Meu%20Tutorial.md"
        )
        self.assertEqual(remote_filename_from_url(url), "Meu Tutorial.md")
        self.assertEqual(remote_filename_from_url(
            "https://empresa.sharepoint.com/:u:/r/sites/x/GuiXT/c99dc33b43f536c78780.md"
        ), "")

        with tempfile.TemporaryDirectory() as tmp:
            previous = config.TUTORIAL_CACHE_DIR
            config.TUTORIAL_CACHE_DIR = Path(tmp) / "cache"
            seen = []

            def fake(link, pasta_destino, nome_arquivo=None, progress=None):
                seen.append(nome_arquivo)
                self.assertNotEqual(nome_arquivo, cache_path_for(url, ".md", "1").name)
                path = Path(pasta_destino) / nome_arquivo
                path.write_text("# tutorial", encoding="utf-8")
                return SharePointResult(ok=True, path=path, message="ok")

            original = tutorial_mod.baixar_do_sharepoint
            tutorial_mod.baixar_do_sharepoint = fake
            try:
                local, err = download_to_cache(url, ".md", version="1")
                self.assertEqual(err, "")
                self.assertEqual(seen, ["Meu Tutorial.md"])
                self.assertEqual(local.name, cache_path_for(url, ".md", "1").name)
                self.assertNotEqual(local.name, "Meu Tutorial.md")
                self.assertEqual(len(local.stem), 20)
                self.assertEqual(local.read_text(encoding="utf-8"), "# tutorial")
                again, again_err = download_to_cache(url, ".md", version="1")
                self.assertEqual(again_err, "")
                self.assertEqual(again, local)
                self.assertEqual(seen, ["Meu Tutorial.md"])
            finally:
                tutorial_mod.baixar_do_sharepoint = original
                config.TUTORIAL_CACHE_DIR = previous

    def test_open_uses_cached_files_without_download(self) -> None:
        import services.tutorial as tutorial_mod

        md_url = "https://x/guia.md"
        video_url = "https://x/instalar.mp4"
        with tempfile.TemporaryDirectory() as tmp:
            previous = config.TUTORIAL_CACHE_DIR
            config.TUTORIAL_CACHE_DIR = Path(tmp)
            cache_path_for(md_url, ".md", "2").write_text("## Usar\nPasso\n", encoding="utf-8")
            cache_path_for(video_url, ".mp4", "4").write_bytes(b"mp4")
            app = AppInfo(
                id="com",
                nome="Com",
                tutorial_markdown_url=md_url,
                tutorial_markdown_versao="2",
                tutorial_videos=[("Certo", video_url, "4")],
            )

            def boom(*_args, **_kwargs):
                raise AssertionError("cache da versao atual nao baixa de novo")

            original = tutorial_mod.baixar_do_sharepoint
            tutorial_mod.baixar_do_sharepoint = boom
            try:
                page = _Page()
                view = TutorialView(page, app, lambda: None)
                view.build()
                self.assertEqual(page.threads, [])
                self.assertIn("Passo", _texts(view.markdown_host))
                self.assertEqual(page.threads, [])
                self.assertEqual(len(view.players), 1)
                self.assertEqual(len(view.players[0].playlist), 1)
                self.assertTrue(str(view.players[0].playlist[0].resource).endswith(".mp4"))
                page_col = view.build()
                self.assertIs(page_col.controls[-1], view.markdown_host)
                self.assertIs(page_col.controls[-2], view.videos_host)
            finally:
                tutorial_mod.baixar_do_sharepoint = original
                config.TUTORIAL_CACHE_DIR = previous


if __name__ == "__main__":
    unittest.main()
