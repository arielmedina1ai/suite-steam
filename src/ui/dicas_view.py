"""Aba Dicas: selecionar o tips.json e editar os pares titulo/texto."""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

import config
from services.tips import DicasFormState
from ui.progress_util import bar_value, label as progress_label
from ui.publish_view import _remember_scroll, bind_form_section, notice_banner, option7_text

_DEL_ICON = getattr(ft.Icons, "DELETE_OUTLINE", None) or ft.Icons.CLOSE


def _pair_divider() -> ft.Control:
    return ft.Divider(height=16, thickness=1, color="#22332B")


def bind_dicas_form(
    form: DicasFormState,
    *,
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
            "Cole o link do SharePoint ou escolha um arquivo local. "
            "O envio usa o nome original na pasta de destino.",
            size=12,
            color="#8AA797",
        ),
    ]
    if picked:
        select_controls.append(
            ft.Text(
                f"Arquivo local a enviar (nome original): {picked}",
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

    edit_controls: list[ft.Control] = []
    if not form.has_file:
        edit_controls.append(
            ft.Text(
                "Selecione ou adicione o tips.json para editar.",
                size=13,
                color="#8AA797",
            )
        )
    else:
        for index, (titulo, texto) in enumerate(form.pairs):
            if index > 0:
                edit_controls.append(_pair_divider())

            def _titulo(value: str, idx: int = index) -> None:
                on_field(f"titulo:{idx}", value)

            def _texto(value: str, idx: int = index) -> None:
                on_field(f"texto:{idx}", value)

            edit_controls.append(
                option7_text(
                    "Título da dica",
                    titulo,
                    changed=False,
                    on_commit=_titulo,
                    is_changed=lambda: False,
                )
            )
            edit_controls.append(
                option7_text(
                    "Dica",
                    texto,
                    changed=False,
                    on_commit=_texto,
                    is_changed=lambda: False,
                    multiline=True,
                    min_lines=2,
                    max_lines=6,
                )
            )
            edit_controls.append(
                ft.TextButton(
                    content="Remover",
                    icon=_DEL_ICON,
                    disabled=form.busy,
                    on_click=lambda e, idx=index: on_field(f"remover:{idx}", "1"),
                )
            )
        edit_controls.append(
            ft.OutlinedButton(
                content="Adicionar dica",
                icon=ft.Icons.ADD,
                disabled=form.busy,
                on_click=lambda e: on_field("adicionar", "1"),
            )
        )

    done_text = form.notice if form.notice else ("" if form.busy else form.message)
    bind_form_section(
        edit_holder,
        "Editar",
        edit_controls,
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
                        disabled=form.busy or not form.has_file,
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
