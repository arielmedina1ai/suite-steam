"""Tela Catálogo: abas Publicar e Estrutura."""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

import config
from models import CatalogData
from services.catalog_publish import PublishFormState, StructureFormState
from ui.publish_view import bind_publish_form
from ui.structure_view import bind_structure_form


def _tab_chip(label: str, *, selected: bool, on_click: Callable[[], None]) -> ft.Control:
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=14, vertical=8),
        border=ft.Border(
            bottom=ft.BorderSide(2, config.COLOR_ACCENT if selected else "#22332B")
        ),
        on_click=lambda e: on_click(),
        content=ft.Text(
            label,
            size=14,
            weight=ft.FontWeight.BOLD if selected else ft.FontWeight.W_500,
            color=config.COLOR_ACCENT if selected else config.COLOR_TEXT,
        ),
    )


def session_holder() -> ft.Container:
    return ft.Container(
        expand=True,
        bgcolor=config.COLOR_BG,
        border_radius=10,
        padding=16,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )


def bind_catalog_view(
    catalog: CatalogData,
    form: PublishFormState,
    structure: StructureFormState,
    tab: str,
    *,
    on_tab: Callable[[str], None],
    on_select_app: Callable[[str], None],
    on_save: Callable[[], None],
    on_cancel: Callable[[], None],
    on_pick: Callable[[str], None],
    on_field: Callable[[str, str], None],
    on_reopen: Callable[[], None],
    on_refresh_folders: Callable[[], None] | None = None,
    on_structure_select: Callable[[str], None],
    on_structure_field: Callable[[str, str], None],
    on_structure_toggle_app: Callable[[str, bool], None],
    on_structure_new: Callable[[str], None],
    on_structure_new_subsetor: Callable[[int], None],
    on_structure_delete: Callable[[str], None],
    on_structure_save: Callable[[], None],
    on_structure_reopen: Callable[[], None],
    tab_row: ft.Row,
    session_host: ft.Container,
    publish_layout: ft.Column,
    estrutura_layout: ft.Row,
    publish_select: ft.Container,
    publish_edit: ft.Container,
    structure_select: ft.Container,
    structure_edit: ft.Container,
) -> None:
    tab_row.controls = [
        _tab_chip("Publicar", selected=tab != "estrutura", on_click=lambda: on_tab("publish")),
        _tab_chip("Estrutura", selected=tab == "estrutura", on_click=lambda: on_tab("estrutura")),
    ]
    if tab == "estrutura":
        bind_structure_form(
            catalog,
            structure,
            on_select=on_structure_select,
            on_field=on_structure_field,
            on_toggle_app=on_structure_toggle_app,
            on_new=on_structure_new,
            on_new_subsetor=on_structure_new_subsetor,
            on_delete=on_structure_delete,
            on_save=on_structure_save,
            on_reopen=on_structure_reopen,
            select_holder=structure_select,
            edit_holder=structure_edit,
        )
        structure_select.expand = True
        structure_edit.expand = True
        structure_select.height = None
        structure_edit.height = None
        cur = list(estrutura_layout.controls or [])
        if len(cur) != 2 or cur[0] is not structure_select or cur[1] is not structure_edit:
            estrutura_layout.controls = [structure_select, structure_edit]
        session_host.content = estrutura_layout
    else:
        bind_publish_form(
            catalog,
            form,
            on_select_app=on_select_app,
            on_save=on_save,
            on_cancel=on_cancel,
            on_pick=on_pick,
            on_field=on_field,
            on_reopen=on_reopen,
            on_refresh_folders=on_refresh_folders,
            select_holder=publish_select,
            edit_holder=publish_edit,
        )
        cur = list(publish_layout.controls or [])
        if len(cur) != 2 or cur[0] is not publish_select or cur[1] is not publish_edit:
            publish_layout.controls = [publish_select, publish_edit]
        session_host.content = publish_layout
