"""Aba Links: selecionar o links.json e editar grupos e itens."""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

import config
from services.links import LinksFormState
from ui.progress_util import bar_value, label as progress_label
from ui.publish_view import (
    _remember_scroll,
    bind_form_section,
    field_kwargs,
    notice_banner,
    option7_row,
    option7_text,
)

_DEL_ICON = getattr(ft.Icons, "DELETE_OUTLINE", None) or ft.Icons.CLOSE


def _pair_divider() -> ft.Control:
    return ft.Divider(height=16, thickness=1, color="#22332B")


def _group_move_field(value: str, on_commit: Callable[[str], None]) -> ft.Container:
    """Campo Grupo do item. A troca so vale ao sair do campo, para nao mover a cada letra."""
    field = ft.TextField(
        value=value,
        **field_kwargs(changed=False),
    )
    box = option7_row("Grupo", field, changed=False)
    initial = value or ""

    def _finish(e) -> None:
        current = getattr(e.control, "value", None) or ""
        if current == initial:
            return
        on_commit(current)

    field.on_blur = _finish
    field.on_submit = _finish
    return box


def bind_links_form(
    form: LinksFormState,
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
                "Selecione ou adicione o links.json para editar.",
                size=13,
                color="#8AA797",
            )
        )
    else:
        last_group = len(form.groups) - 1
        for gi, group in enumerate(form.groups):
            if gi > 0:
                edit_controls.append(_pair_divider())

            def _grupo(value: str, g: int = gi) -> None:
                on_field(f"grupo:{g}", value)

            edit_controls.append(
                option7_text(
                    "Grupo",
                    group.titulo,
                    changed=False,
                    on_commit=_grupo,
                    is_changed=lambda: False,
                )
            )
            edit_controls.append(
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.TextButton(
                            content="Subir grupo",
                            disabled=form.busy or gi == 0,
                            on_click=lambda e, g=gi: on_field(f"subir_grupo:{g}", "1"),
                        ),
                        ft.TextButton(
                            content="Descer grupo",
                            disabled=form.busy or gi == last_group,
                            on_click=lambda e, g=gi: on_field(f"descer_grupo:{g}", "1"),
                        ),
                        ft.TextButton(
                            content="Remover grupo",
                            icon=_DEL_ICON,
                            disabled=form.busy,
                            on_click=lambda e, g=gi: on_field(f"remover_grupo:{g}", "1"),
                        ),
                    ],
                )
            )
            last_item = len(group.items) - 1
            for ii, item in enumerate(group.items):
                if ii > 0:
                    edit_controls.append(_pair_divider())

                def _titulo(value: str, g: int = gi, i: int = ii) -> None:
                    on_field(f"titulo:{g}:{i}", value)

                def _descricao(value: str, g: int = gi, i: int = ii) -> None:
                    on_field(f"descricao:{g}:{i}", value)

                def _link(value: str, g: int = gi, i: int = ii) -> None:
                    on_field(f"link:{g}:{i}", value)

                def _mover_grupo(value: str, g: int = gi, i: int = ii) -> None:
                    on_field(f"grupo_item:{g}:{i}", value)

                edit_controls.append(_group_move_field(group.titulo, _mover_grupo))
                edit_controls.append(
                    option7_text(
                        "Título",
                        item.titulo,
                        changed=False,
                        on_commit=_titulo,
                        is_changed=lambda: False,
                    )
                )
                edit_controls.append(
                    option7_text(
                        "Descrição",
                        item.descricao,
                        changed=False,
                        on_commit=_descricao,
                        is_changed=lambda: False,
                    )
                )
                edit_controls.append(
                    option7_text(
                        "Link",
                        item.url,
                        changed=False,
                        on_commit=_link,
                        is_changed=lambda: False,
                    )
                )
                edit_controls.append(
                    ft.Row(
                        spacing=8,
                        controls=[
                            ft.TextButton(
                                content="Subir",
                                disabled=form.busy or ii == 0,
                                on_click=lambda e, g=gi, i=ii: on_field(f"subir:{g}:{i}", "1"),
                            ),
                            ft.TextButton(
                                content="Descer",
                                disabled=form.busy or ii == last_item,
                                on_click=lambda e, g=gi, i=ii: on_field(f"descer:{g}:{i}", "1"),
                            ),
                            ft.TextButton(
                                content="Remover",
                                icon=_DEL_ICON,
                                disabled=form.busy,
                                on_click=lambda e, g=gi, i=ii: on_field(f"remover:{g}:{i}", "1"),
                            ),
                        ],
                    )
                )
            edit_controls.append(
                ft.OutlinedButton(
                    content="Adicionar link",
                    icon=ft.Icons.ADD,
                    disabled=form.busy,
                    on_click=lambda e, g=gi: on_field(f"adicionar:{g}", "1"),
                )
            )
        edit_controls.append(
            ft.OutlinedButton(
                content="Adicionar grupo",
                icon=ft.Icons.ADD,
                disabled=form.busy,
                on_click=lambda e: on_field("adicionar_grupo", "1"),
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
