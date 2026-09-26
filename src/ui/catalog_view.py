"""Tela Catálogo: abas Publicar e Estrutura."""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

import config
from models import CatalogData
from services.catalog_publish import PublishFormState, StructureFormState
from ui.publish_view import build_publish_form
from ui.structure_view import build_structure_form


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


def build_catalog_view(
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
    publish_select_scroll_ref: ft.Ref | None = None,
    publish_edit_scroll_ref: ft.Ref | None = None,
    structure_select_scroll_ref: ft.Ref | None = None,
    structure_edit_scroll_ref: ft.Ref | None = None,
) -> ft.Control:
    body = (
        build_publish_form(
            catalog,
            form,
            on_select_app=on_select_app,
            on_save=on_save,
            on_cancel=on_cancel,
            on_pick=on_pick,
            on_field=on_field,
            on_reopen=on_reopen,
            on_refresh_folders=on_refresh_folders,
            select_scroll_ref=publish_select_scroll_ref,
            edit_scroll_ref=publish_edit_scroll_ref,
        )
        if tab != "estrutura"
        else build_structure_form(
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
            select_scroll_ref=structure_select_scroll_ref,
            edit_scroll_ref=structure_edit_scroll_ref,
        )
    )
    return ft.Column(
        expand=True,
        spacing=12,
        controls=[
            ft.Text("Catalogo", size=22, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
            ft.Row(
                spacing=8,
                controls=[
                    _tab_chip("Publicar", selected=tab != "estrutura", on_click=lambda: on_tab("publish")),
                    _tab_chip("Estrutura", selected=tab == "estrutura", on_click=lambda: on_tab("estrutura")),
                ],
            ),
            ft.Container(
                expand=True,
                bgcolor=config.COLOR_SURFACE,
                border_radius=10,
                padding=12,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=body,
            ),
        ],
    )
