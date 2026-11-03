"""Aba Feedback: selecionar o feedback.json e ver o que foi enviado."""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

import config
from services.feedback import (
    FeedbackCatalogState,
    feedback_app_label,
    ordered_feedback_entries,
)
from ui.progress_util import bar_value, label as progress_label
from ui.publish_view import _remember_scroll, bind_form_section, notice_banner, option7_row, option7_text

_VALUE_FILL = "#1A2621"


def _pair_divider() -> ft.Control:
    return ft.Divider(height=16, thickness=1, color="#22332B")


def _read_value(text: str, *, multiline: bool = False) -> ft.Container:
    return ft.Container(
        bgcolor=_VALUE_FILL,
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        content=ft.Text(
            text if text else " ",
            size=12,
            color=config.COLOR_TEXT,
            no_wrap=not multiline,
        ),
    )


def bind_feedback_form(
    form: FeedbackCatalogState,
    *,
    app_names: dict[str, str],
    on_save: Callable[[], None],
    on_pick: Callable[[], None],
    on_field: Callable[[str, str], None],
    on_reopen: Callable[[], None],
    select_holder: ft.Container,
    edit_holder: ft.Container,
) -> None:
    picked = (form.local_name or "").strip()
    select_controls: list[ft.Control] = [
        option7_text(
            "Link",
            form.url,
            changed=False,
            on_commit=lambda value: on_field("url", value),
            is_changed=lambda: False,
            multiline=True,
            min_lines=2,
            max_lines=4,
        ),
        option7_text(
            "Pasta destino",
            form.dest_folder,
            changed=False,
            on_commit=lambda value: on_field("dest_folder", value),
            is_changed=lambda: False,
            multiline=True,
            min_lines=2,
            max_lines=4,
        ),
        ft.Row(
            spacing=12,
            controls=[
                ft.OutlinedButton(
                    content="Escolher arquivo",
                    icon=ft.Icons.FOLDER_OPEN,
                    disabled=form.busy,
                    on_click=lambda e: on_pick(),
                ),
            ],
        ),
        ft.Text(
            "Cole o link do SharePoint ou escolha um arquivo local para ver os envios. "
            "Salvar grava o link no catalogo, como foi colado.",
            size=12,
            color="#8AA797",
        ),
    ]
    if picked:
        select_controls.append(
            ft.Text(
                f"Arquivo local: {picked}",
                size=12,
                color=config.COLOR_ACCENT,
                weight=ft.FontWeight.W_600,
            )
        )
    bind_form_section(
        select_holder,
        "Selecionar ou adicionar",
        select_controls,
        on_scroll_offset=lambda value: _remember_scroll(form, "select_scroll", value),
        expand=False,
        height=280,
    )

    list_controls: list[ft.Control] = []
    if not form.has_file:
        list_controls.append(
            ft.Text(
                "Selecione ou adicione o feedback.json para ver.",
                size=13,
                color="#8AA797",
            )
        )
    else:
        shown = ordered_feedback_entries(form.entries)
        if not shown:
            list_controls.append(
                ft.Text("Nenhum feedback.", size=13, color="#8AA797")
            )
        for index, entry in enumerate(shown):
            if index > 0:
                list_controls.append(_pair_divider())
            list_controls.append(option7_row("Usuario", _read_value(entry.usuario)))
            list_controls.append(option7_row("Quando", _read_value(entry.quando)))
            list_controls.append(
                option7_row("App", _read_value(feedback_app_label(entry, app_names)))
            )
            list_controls.append(
                option7_row(
                    "Texto",
                    _read_value(entry.texto, multiline=True),
                    align=ft.CrossAxisAlignment.START,
                )
            )

    done_text = form.notice if form.notice else ("" if form.busy else form.message)
    intro_box = ft.Container()
    list_box = ft.Container()
    bind_form_section(
        intro_box,
        "Introdução",
        [
            option7_text(
                "Introdução",
                form.introducao,
                changed=False,
                on_commit=lambda value: on_field("introducao", value),
                is_changed=lambda: False,
                multiline=True,
                min_lines=3,
                max_lines=8,
            )
        ],
        expand=False,
    )
    bind_form_section(
        list_box,
        "Feedbacks enviados",
        list_controls,
        on_scroll_offset=lambda value: _remember_scroll(form, "edit_scroll", value),
        preserve_inner=form.hold_scroll,
        footer=[
            notice_banner(
                done_text,
                success=form.notice_ok,
                conflict=form.conflict,
                busy=form.busy,
            ),
            ft.ProgressBar(
                value=bar_value(form.progress),
                visible=form.busy,
                color=config.COLOR_ACCENT,
                bgcolor="#0A0F0C",
            ),
            ft.Text(
                progress_label(form.progress, form.message) if form.busy else "",
                size=13,
                color="#B9CEC3",
                visible=form.busy,
            ),
            ft.Row(
                spacing=12,
                controls=[
                    ft.FilledButton(
                        content="Salvar",
                        icon=ft.Icons.SAVE,
                        disabled=form.busy or not (form.url or "").strip(),
                        on_click=lambda e: on_save(),
                    ),
                    ft.TextButton(
                        content="Reabrir catalogo",
                        visible=form.conflict,
                        on_click=lambda e: on_reopen(),
                    ),
                ],
            ),
        ],
    )
    edit_holder.height = None
    edit_holder.expand = True
    edit_holder.bgcolor = None
    edit_holder.padding = 0
    edit_holder.content = ft.Column(spacing=16, controls=[intro_box, list_box])
