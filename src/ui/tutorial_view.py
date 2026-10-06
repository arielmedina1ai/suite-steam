"""Pagina de tutorial: player MP4 local, lista de titulos e markdown."""
from __future__ import annotations

from pathlib import Path

import flet as ft
import flet_video as fv

import config
from models import AppInfo
from services.tutorial import (
    download_to_cache,
    is_mp4_url,
    prepare_markdown_for_display,
    split_markdown_sections,
)
from ui.progress_util import bar_value, label as progress_label

_PLAYER_WIDTH = 480
_PLAYER_HEIGHT = 270  # 16:9


def _markdown_sheet() -> ft.MarkdownStyleSheet:
    body = ft.TextStyle(size=15, color="#D6E5DC")
    heading = ft.TextStyle(size=18, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT)
    return ft.MarkdownStyleSheet(
        p_text_style=body,
        h1_text_style=ft.TextStyle(size=22, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
        h2_text_style=heading,
        h3_text_style=ft.TextStyle(size=16, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
        a_text_style=ft.TextStyle(size=15, color=config.COLOR_ACCENT),
        strong_text_style=ft.TextStyle(size=15, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
        block_spacing=10,
        list_indent=22,
    )


class TutorialView:
    def __init__(self, page: ft.Page, app: AppInfo, on_back) -> None:
        self.page = page
        self.app = app
        self.on_back = on_back
        self.selected_index: int | None = None
        self._title_boxes: list[ft.Container] = []
        self._pick_gen = 0
        self._markdown_started = False
        self.player: fv.Video | None = None
        if app.tutorial_videos:
            self.player = fv.Video(
                width=_PLAYER_WIDTH,
                height=_PLAYER_HEIGHT,
                aspect_ratio=16 / 9,
                playlist=[],
                autoplay=True,
                title=app.nome or "Tutorial",
            )
        self.progress = ft.ProgressBar(
            value=0,
            visible=False,
            color=config.COLOR_ACCENT,
            bgcolor="#0A0F0C",
            width=_PLAYER_WIDTH,
        )
        self.status = ft.Text("", size=13, color="#B9CEC3", width=_PLAYER_WIDTH)
        self.markdown_host = ft.Column(spacing=8, tight=True)

    def build(self) -> ft.Control:
        if (self.app.tutorial_markdown_url or "").strip() and not self._markdown_started:
            self._markdown_started = True
            self.markdown_host.controls = [
                ft.Text("Carregando passo a passo...", size=13, color="#8AA797")
            ]
            self.page.run_thread(self._load_markdown)
        elif not (self.app.tutorial_markdown_url or "").strip():
            self.markdown_host.controls = []

        controls: list[ft.Control] = [
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(
                        f"Tutorial — {self.app.nome}",
                        size=22,
                        weight=ft.FontWeight.BOLD,
                        color=config.COLOR_TEXT,
                        expand=True,
                    ),
                    ft.OutlinedButton(
                        "Voltar",
                        icon=ft.Icons.ARROW_BACK,
                        on_click=lambda e: self.on_back(),
                    ),
                ],
            )
        ]
        if self.player is not None:
            controls.append(self._player_row())
        controls.append(self.markdown_host)
        return ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=16,
            controls=controls,
        )

    def _player_row(self) -> ft.Control:
        titles: list[ft.Control] = []
        self._title_boxes = []
        for index, (titulo, _url) in enumerate(self.app.tutorial_videos):
            selected = index == self.selected_index
            label = (titulo or "").strip() or f"Video {index + 1}"
            box = ft.Container(
                ink=True,
                border_radius=8,
                padding=ft.Padding.symmetric(horizontal=10, vertical=8),
                bgcolor=config.COLOR_PRIMARY_DARK if selected else config.COLOR_SURFACE,
                on_click=lambda e, idx=index: self._on_pick(idx),
                content=ft.Text(
                    label,
                    size=14,
                    color=config.COLOR_TEXT,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            )
            self._title_boxes.append(box)
            titles.append(box)
        if not titles:
            titles.append(ft.Text("Nenhum video.", size=13, color="#8AA797"))
        return ft.Row(
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Column(
                    spacing=8,
                    tight=True,
                    controls=[
                        ft.Container(
                            width=_PLAYER_WIDTH,
                            height=_PLAYER_HEIGHT,
                            bgcolor="#000000",
                            border_radius=8,
                            clip_behavior=ft.ClipBehavior.HARD_EDGE,
                            content=self.player,
                        ),
                        self.progress,
                        self.status,
                    ],
                ),
                ft.Container(
                    width=280,
                    height=_PLAYER_HEIGHT,
                    content=ft.Column(
                        scroll=ft.ScrollMode.AUTO,
                        spacing=8,
                        controls=titles,
                    ),
                ),
            ],
        )

    def _on_pick(self, index: int) -> None:
        videos = self.app.tutorial_videos
        if index < 0 or index >= len(videos):
            return
        _titulo, url = videos[index]
        self.selected_index = index
        self._paint_titles()
        self._pick_gen += 1
        gen = self._pick_gen
        if not is_mp4_url(url):
            self.progress.visible = False
            self.status.value = "Somente .mp4."
            self.status.color = config.COLOR_ACCENT
            self._safe_update()
            return
        self.status.color = "#B9CEC3"
        self._set_progress(-1.0, "Baixando video...")
        self.page.run_thread(lambda: self._load_video(index, url, gen))

    def _paint_titles(self) -> None:
        for index, box in enumerate(self._title_boxes):
            box.bgcolor = (
                config.COLOR_PRIMARY_DARK if index == self.selected_index else config.COLOR_SURFACE
            )

    def _load_video(self, index: int, url: str, gen: int) -> None:
        path, err = download_to_cache(
            url,
            ".mp4",
            progress=lambda pct, msg: self._on_video_progress(gen, pct, msg),
        )
        if gen != self._pick_gen:
            return
        self.progress.visible = False
        if err or path is None:
            self.status.value = err or "Falha no download."
            self.status.color = config.COLOR_ACCENT
            self._safe_update()
            return
        self._show_local(path)
        self.status.value = ""
        self._safe_update()

    def _show_local(self, path: Path) -> None:
        if self.player is None:
            return
        media = fv.VideoMedia(str(path.resolve()))
        self.player.playlist.clear()
        self.player.playlist.append(media)
        self.player.autoplay = True
        try:
            self.player.update()
        except Exception:
            pass

    def _on_video_progress(self, gen: int, pct: float, msg: str) -> None:
        if gen != self._pick_gen:
            return
        self._set_progress(pct, msg)

    def _load_markdown(self) -> None:
        url = (self.app.tutorial_markdown_url or "").strip()
        if not url:
            return
        path, err = download_to_cache(url, ".md", progress=self._on_markdown_progress)
        if err or path is None:
            self.markdown_host.controls = [
                ft.Text(err or "Falha ao baixar o passo a passo.", size=14, color=config.COLOR_ACCENT)
            ]
            self._safe_update()
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.markdown_host.controls = [
                ft.Text(str(exc), size=14, color=config.COLOR_ACCENT)
            ]
            self._safe_update()
            return
        intro, sections = split_markdown_sections(text)
        blocks: list[ft.Control] = []
        if intro.strip():
            blocks.append(self._markdown_block(intro))
        for title, body in sections:
            blocks.append(
                ft.ExpansionTile(
                    title=title.strip() or "Topico",
                    expanded=False,
                    controls=[self._markdown_block(body)] if body.strip() else [],
                    controls_padding=ft.Padding.only(left=8, right=8, bottom=8),
                    bgcolor=config.COLOR_SURFACE,
                    collapsed_bgcolor=config.COLOR_SURFACE,
                    text_color=config.COLOR_TEXT,
                    collapsed_text_color=config.COLOR_TEXT,
                    icon_color=config.COLOR_ACCENT,
                    collapsed_icon_color=config.COLOR_ACCENT,
                    expanded_cross_axis_alignment=ft.CrossAxisAlignment.START,
                )
            )
        if not blocks:
            blocks.append(ft.Text("Passo a passo vazio.", size=14, color="#8AA797"))
        self.markdown_host.controls = blocks
        self._safe_update()

    def _markdown_block(self, text: str) -> ft.Control:
        shown = prepare_markdown_for_display(text).strip("\n")
        if not shown.strip():
            return ft.Container()
        return ft.Container(
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Markdown(
                value=shown,
                selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                shrink_wrap=True,
                fit_content=True,
                md_style_sheet=_markdown_sheet(),
                on_tap_link=self._open_link,
            ),
        )

    def _open_link(self, e) -> None:
        url = str(getattr(e, "data", "") or "").strip()
        if not url:
            return
        launch = getattr(self.page, "launch_url", None)
        if not callable(launch):
            return
        try:
            launch(url)
        except Exception:
            pass

    def _on_markdown_progress(self, pct: float, msg: str) -> None:
        if not self.markdown_host.controls:
            return
        first = self.markdown_host.controls[0]
        if isinstance(first, ft.Text) and (first.value or "").startswith("Carregando"):
            first.value = progress_label(pct, msg) or "Carregando passo a passo..."
            self._safe_update()

    def _set_progress(self, pct: float | None, msg: str) -> None:
        self.progress.visible = True
        self.progress.value = bar_value(pct)
        self.status.value = progress_label(pct, msg)
        self.status.color = "#B9CEC3"
        self._safe_update()

    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass
