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
    on_structure_select: Callable[[str], None],
    on_structure_field: Callable[[str, str], None],
    on_structure_toggle_app: Callable[[str, bool], None],
    on_structure_new: Callable[[str], None],
    on_structure_save: Callable[[], None],
    on_structure_reopen: Callable[[], None],
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
        )
        if tab != "estrutura"
        else build_structure_form(
            catalog,
            structure,
            on_select=on_structure_select,
            on_field=on_structure_field,
            on_toggle_app=on_structure_toggle_app,
            on_new=on_structure_new,
            on_save=on_structure_save,
            on_reopen=on_structure_reopen,
        )
    )
    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=16,
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
                bgcolor=config.COLOR_SURFACE,
                border_radius=10,
                padding=20,
                content=body,
            ),
        ],
    )
