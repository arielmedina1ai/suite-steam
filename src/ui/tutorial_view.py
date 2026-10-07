"""Pagina de tutorial: um bloco por video (titulo + player) e o markdown abaixo."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import flet as ft
import flet_video as fv

import config
from models import AppInfo, tutorial_video_fields
from services.tutorial import (
    cached_tutorial_file,
    download_to_cache,
    is_mp4_url,
    prepare_markdown_for_display,
    split_markdown_sections,
)
from ui.progress_util import bar_value, label as progress_label

_PLAYER_WIDTH = 480
_PLAYER_HEIGHT = 270  # 16:9
_FRAME_BORDER = "#2C4036"


def _framed_box(content: ft.Control) -> ft.Container:
    return ft.Container(
        bgcolor=config.COLOR_SURFACE,
        border=ft.Border.all(1, _FRAME_BORDER),
        border_radius=12,
        padding=16,
        content=content,
    )


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


@dataclass
class _VideoSlot:
    index: int
    url: str
    versao: str
    player: fv.Video
    progress: ft.ProgressBar
    status: ft.Text
    block: ft.Column
    gen: int = 0


def _video_player(title: str) -> fv.Video:
    # controls fica no padrao do player (play, pause e o resto dentro do quadro).
    return fv.Video(
        width=_PLAYER_WIDTH,
        height=_PLAYER_HEIGHT,
        aspect_ratio=16 / 9,
        playlist=[],
        autoplay=False,
        title=title,
    )


class TutorialView:
    def __init__(self, page: ft.Page, app: AppInfo, on_back) -> None:
        self.page = page
        self.app = app
        self.on_back = on_back
        self._videos_started = False
        self._markdown_started = False
        self.slots: list[_VideoSlot] = []
        self.players: list[fv.Video] = []
        blocks: list[ft.Control] = []
        for index, item in enumerate(app.tutorial_videos):
            titulo, url, versao = tutorial_video_fields(item)
            label = (titulo or "").strip() or f"Video {index + 1}"
            player = _video_player(label)
            progress = ft.ProgressBar(
                value=0,
                visible=False,
                color=config.COLOR_ACCENT,
                bgcolor="#0A0F0C",
                width=_PLAYER_WIDTH,
            )
            status = ft.Text("", size=13, color="#B9CEC3", width=_PLAYER_WIDTH, text_align=ft.TextAlign.CENTER)
            frame = ft.Container(
                width=_PLAYER_WIDTH,
                height=_PLAYER_HEIGHT,
                bgcolor="#000000",
                border_radius=8,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=player,
            )
            block = ft.Column(
                width=_PLAYER_WIDTH,
                spacing=8,
                tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(
                        label,
                        size=15,
                        color=config.COLOR_TEXT,
                        text_align=ft.TextAlign.CENTER,
                        width=_PLAYER_WIDTH,
                    ),
                    frame,
                    progress,
                    status,
                ],
            )
            self.slots.append(
                _VideoSlot(
                    index=index,
                    url=url,
                    versao=versao,
                    player=player,
                    progress=progress,
                    status=status,
                    block=block,
                )
            )
            self.players.append(player)
            blocks.append(_framed_box(block))
        self.player = self.players[0] if self.players else None
        self.videos_host = ft.Column(
            spacing=16,
            tight=True,
            controls=blocks,
        )
        self.markdown_host = ft.Column(spacing=8, tight=True)
        self.markdown_frame = _framed_box(self.markdown_host)

    def build(self) -> ft.Control:
        if (self.app.tutorial_markdown_url or "").strip() and not self._markdown_started:
            self._markdown_started = True
            cached = cached_tutorial_file(
                self.app.tutorial_markdown_url,
                ".md",
                self.app.tutorial_markdown_versao,
            )
            if cached is not None:
                self._show_markdown(cached)
            else:
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
        if self.slots:
            controls.append(self.videos_host)
            if not self._videos_started:
                self._videos_started = True
                for slot in self.slots:
                    self._begin_load(slot)
        if (self.app.tutorial_markdown_url or "").strip() or self.markdown_host.controls:
            controls.append(self.markdown_frame)
        return ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=16,
            controls=controls,
        )

    def _begin_load(self, slot: _VideoSlot) -> None:
        slot.gen += 1
        gen = slot.gen
        if not is_mp4_url(slot.url):
            slot.progress.visible = False
            slot.status.value = "Somente .mp4."
            slot.status.color = config.COLOR_ACCENT
            return
        cached = cached_tutorial_file(slot.url, ".mp4", slot.versao)
        if cached is not None:
            slot.progress.visible = False
            slot.status.value = ""
            slot.status.color = "#B9CEC3"
            self._show_local(slot, cached)
            return
        slot.status.color = "#B9CEC3"
        self._set_slot_progress(slot, -1.0, "Baixando video...")
        self.page.run_thread(lambda s=slot, g=gen: self._load_video(s, g))

    def _load_video(self, slot: _VideoSlot, gen: int) -> None:
        path, err = download_to_cache(
            slot.url,
            ".mp4",
            progress=lambda pct, msg: self._on_video_progress(slot, gen, pct, msg),
            version=slot.versao,
        )
        if gen != slot.gen:
            return
        slot.progress.visible = False
        if err or path is None:
            slot.status.value = err or "Falha no download."
            slot.status.color = config.COLOR_ACCENT
            self._safe_update()
            return
        self._show_local(slot, path)
        slot.status.value = ""
        self._safe_update()

    def _show_local(self, slot: _VideoSlot, path: Path) -> None:
        media = fv.VideoMedia(str(path.resolve()))
        slot.player.playlist.clear()
        slot.player.playlist.append(media)
        try:
            slot.player.update()
        except Exception:
            pass

    def _on_video_progress(self, slot: _VideoSlot, gen: int, pct: float, msg: str) -> None:
        if gen != slot.gen:
            return
        self._set_slot_progress(slot, pct, msg)

    def _set_slot_progress(self, slot: _VideoSlot, pct: float | None, msg: str) -> None:
        slot.progress.visible = True
        slot.progress.value = bar_value(pct)
        slot.status.value = progress_label(pct, msg)
        slot.status.color = "#B9CEC3"
        self._safe_update()

    def _load_markdown(self) -> None:
        url = (self.app.tutorial_markdown_url or "").strip()
        if not url:
            return
        cached = cached_tutorial_file(url, ".md", self.app.tutorial_markdown_versao)
        if cached is not None:
            self._show_markdown(cached)
            return
        path, err = download_to_cache(
            url,
            ".md",
            progress=self._on_markdown_progress,
            version=self.app.tutorial_markdown_versao,
        )
        if err or path is None:
            self.markdown_host.controls = [
                ft.Text(err or "Falha ao baixar o passo a passo.", size=14, color=config.COLOR_ACCENT)
            ]
            self._safe_update()
            return
        self._show_markdown(path)

    def _show_markdown(self, path: Path) -> None:
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

    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass
