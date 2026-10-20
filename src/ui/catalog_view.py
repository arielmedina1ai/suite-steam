"""Tela Catálogo: abas Publicar, Estrutura, Links e Dicas."""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

import config
from models import CatalogData
from services.catalog_publish import PublishFormState, StructureFormState
from services.links import LinksFormState
from services.tips import DicasFormState
from ui.dicas_view import bind_dicas_form
from ui.links_form_view import bind_links_form
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
    on_delete_app: Callable[[], None] | None = None,
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
    dicas: DicasFormState | None = None,
    on_dicas_save: Callable[[], None] | None = None,
    on_dicas_pick: Callable[[], None] | None = None,
    on_dicas_field: Callable[[str, str], None] | None = None,
    dicas_layout: ft.Column | None = None,
    dicas_select: ft.Container | None = None,
    dicas_edit: ft.Container | None = None,
    links: LinksFormState | None = None,
    on_links_save: Callable[[], None] | None = None,
    on_links_pick: Callable[[], None] | None = None,
    on_links_field: Callable[[str, str], None] | None = None,
    links_layout: ft.Column | None = None,
    links_select: ft.Container | None = None,
    links_edit: ft.Container | None = None,
) -> None:
    tab_row.controls = [
        _tab_chip("Publicar", selected=tab == "publish", on_click=lambda: on_tab("publish")),
        _tab_chip("Estrutura", selected=tab == "estrutura", on_click=lambda: on_tab("estrutura")),
        _tab_chip("Links", selected=tab == "links", on_click=lambda: on_tab("links")),
        _tab_chip("Dicas", selected=tab == "dicas", on_click=lambda: on_tab("dicas")),
    ]
    if tab == "links" and links is not None and links_layout is not None and links_select is not None and links_edit is not None:
        bind_links_form(
            links,
            on_save=on_links_save or (lambda: None),
            on_pick=on_links_pick or (lambda: None),
            on_field=on_links_field or (lambda _key, _value: None),
            on_reopen=on_reopen,
            select_holder=links_select,
            edit_holder=links_edit,
        )
        cur = list(links_layout.controls or [])
        if len(cur) != 2 or cur[0] is not links_select or cur[1] is not links_edit:
            links_layout.controls = [links_select, links_edit]
        session_host.content = links_layout
    elif tab == "dicas" and dicas is not None and dicas_layout is not None and dicas_select is not None and dicas_edit is not None:
        bind_dicas_form(
            dicas,
            on_save=on_dicas_save or (lambda: None),
            on_pick=on_dicas_pick or (lambda: None),
            on_field=on_dicas_field or (lambda _key, _value: None),
            on_reopen=on_reopen,
            select_holder=dicas_select,
            edit_holder=dicas_edit,
        )
        cur = list(dicas_layout.controls or [])
        if len(cur) != 2 or cur[0] is not dicas_select or cur[1] is not dicas_edit:
            dicas_layout.controls = [dicas_select, dicas_edit]
        session_host.content = dicas_layout
    elif tab == "estrutura":
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
            on_delete_app=on_delete_app,
            select_holder=publish_select,
            edit_holder=publish_edit,
        )
        cur = list(publish_layout.controls or [])
        if len(cur) != 2 or cur[0] is not publish_select or cur[1] is not publish_edit:
            publish_layout.controls = [publish_select, publish_edit]
        session_host.content = publish_layout
