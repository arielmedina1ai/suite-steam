"""Aba Estrutura: gerencias, setores, sub-setores e onde os apps ficam."""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

import config
from models import CatalogData
from services.catalog_publish import DraftGerencia, StructureFormState
from ui.progress_util import bar_value, label as progress_label
from ui.publish_view import field_kwargs, option7_row


def _node(
    title: str,
    subtitle: str,
    *,
    selected: bool,
    indent: int,
    on_click: Callable[[], None],
) -> ft.Control:
    return ft.Container(
        margin=ft.Margin.only(left=indent),
        bgcolor=config.COLOR_PRIMARY_DARK if selected else config.COLOR_BG,
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        ink=True,
        on_click=lambda e: on_click(),
        content=ft.Column(
            spacing=2,
            tight=True,
            controls=[
                ft.Text(title, size=13, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                ft.Text(subtitle, size=11, color="#8AA797") if subtitle else ft.Container(),
            ],
        ),
    )


def _app_chip(nome: str) -> ft.Control:
    return ft.Container(
        bgcolor="#1C2A24",
        border_radius=6,
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        content=ft.Text(nome, size=11, color="#B9CEC3"),
    )


def _apps_row(catalog: CatalogData, app_ids: list[str]) -> ft.Control:
    by_id = {a.id: a for a in catalog.apps}
    chips: list[ft.Control] = []
    for aid in app_ids:
        app = by_id.get(aid)
        chips.append(_app_chip(app.nome if app is not None else aid))
    if not chips:
        chips.append(ft.Text("nenhum app", size=11, color="#8AA797"))
    return ft.Container(
        padding=ft.Padding.only(left=12, top=4, bottom=8),
        content=ft.Row(wrap=True, spacing=6, run_spacing=6, controls=chips),
    )


def _setor_apps(catalog: CatalogData, setor_id: str, sub_id: str = "") -> list[str]:
    out: list[str] = []
    for app in catalog.apps:
        if (app.setor or "").strip() != setor_id:
            continue
        if sub_id:
            if (app.sub_setor or "").strip() == sub_id:
                out.append(app.id)
        elif not (app.sub_setor or "").strip():
            out.append(app.id)
    return out


def _apps_sem_gerencia(catalog: CatalogData, gerencias: list[DraftGerencia]) -> list[str]:
    assigned = {aid for g in gerencias for aid in g.apps}
    return [a.id for a in catalog.apps if a.id not in assigned]


def build_structure_form(
    catalog: CatalogData,
    form: StructureFormState,
    *,
    on_select: Callable[[str], None],
    on_field: Callable[[str, str], None],
    on_toggle_app: Callable[[str, bool], None],
    on_new: Callable[[str], None],
    on_save: Callable[[], None],
    on_reopen: Callable[[], None],
) -> ft.Control:
    tree: list[ft.Control] = [
        ft.Text("Gerencias", size=14, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
        ft.Row(
            spacing=8,
            controls=[
                ft.OutlinedButton(content="Nova gerencia", icon=ft.Icons.ADD, on_click=lambda e: on_new("gerencia")),
            ],
        ),
        _node(
            f"(Geral) — {form.gerencia_geral or 'Geral'}",
            "catalog default / sem gerencia especifica",
            selected=form.sel == "geral",
            indent=0,
            on_click=lambda: on_select("geral"),
        ),
        _apps_row(catalog, _apps_sem_gerencia(catalog, form.gerencias)),
    ]
    for i, g in enumerate(form.gerencias):
        key = f"g:{i}"
        tree.append(
            _node(
                g.nome or g.id or "Gerencia",
                g.id,
                selected=form.sel == key,
                indent=0,
                on_click=lambda k=key: on_select(k),
            )
        )
        tree.append(_apps_row(catalog, g.apps))

    tree.extend(
        [
            ft.Text("Setores", size=14, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
            ft.Row(
                spacing=8,
                controls=[
                    ft.OutlinedButton(content="Novo setor", icon=ft.Icons.ADD, on_click=lambda e: on_new("setor")),
                    ft.OutlinedButton(
                        content="Novo sub-setor",
                        icon=ft.Icons.ADD,
                        on_click=lambda e: on_new("subsetor"),
                    ),
                ],
            ),
        ]
    )
    for si, s in enumerate(form.setores):
        skey = f"s:{si}"
        tree.append(
            _node(
                s.nome or s.id or "Setor",
                s.id,
                selected=form.sel == skey,
                indent=0,
                on_click=lambda k=skey: on_select(k),
            )
        )
        tree.append(_apps_row(catalog, _setor_apps(catalog, s.orig_id or s.id)))
        for subi, sub in enumerate(s.sub_setores):
            subkey = f"sub:{si}:{subi}"
            tree.append(
                _node(
                    sub.nome or sub.id or "Sub-setor",
                    sub.id,
                    selected=form.sel == subkey,
                    indent=20,
                    on_click=lambda k=subkey: on_select(k),
                )
            )
            tree.append(
                ft.Container(
                    padding=ft.Padding.only(left=20),
                    content=_apps_row(catalog, _setor_apps(catalog, s.orig_id or s.id, sub.orig_id or sub.id)),
                )
            )

    editor = _editor(catalog, form, on_field=on_field, on_toggle_app=on_toggle_app)
    return ft.Column(
        spacing=14,
        tight=True,
        controls=[
            ft.Text(
                "Arvore do catalog.json: gerencia, setor, sub-setor e os apps em cada ponto.",
                size=13,
                color="#8AA797",
            ),
            *tree,
            ft.Divider(color="#22332B"),
            editor,
            ft.ProgressBar(
                value=bar_value(form.progress),
                visible=form.busy,
                color=config.COLOR_ACCENT,
                bgcolor="#0A0F0C",
            ),
            ft.Text(
                progress_label(form.progress, form.message) if form.busy else form.message,
                size=13,
                color=config.COLOR_ACCENT if form.conflict else "#B9CEC3",
            ),
            ft.Row(
                spacing=12,
                controls=[
                    ft.FilledButton(
                        content="Salvar estrutura",
                        icon=ft.Icons.SAVE,
                        disabled=form.busy,
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


def _editor(
    catalog: CatalogData,
    form: StructureFormState,
    *,
    on_field: Callable[[str, str], None],
    on_toggle_app: Callable[[str, bool], None],
) -> ft.Control:
    kw = field_kwargs()
    sel = form.sel or ""
    if sel == "geral" or not sel:
        return ft.Column(
            spacing=10,
            tight=True,
            controls=[
                ft.Text("Geral", size=16, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                option7_row(
                    "Rotulo Geral",
                    ft.TextField(value=form.gerencia_geral, on_change=lambda e: on_field("gerencia_geral", e.control.value or ""), **kw),
                ),
                ft.Text(
                    "Opcao vazia do filtro de gerencia (gerencia_geral). Apps sem gerencia aparecem acima.",
                    size=12,
                    color="#8AA797",
                ),
            ],
        )

    if sel.startswith("g:"):
        idx = int(sel.split(":")[1])
        g = form.gerencias[idx]
        checks = [
            ft.Checkbox(
                label=app.nome,
                value=app.id in g.apps,
                on_change=lambda e, aid=app.id: on_toggle_app(aid, bool(e.control.value)),
            )
            for app in catalog.apps
        ]
        return ft.Column(
            spacing=10,
            tight=True,
            controls=[
                ft.Text("Gerencia", size=16, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                option7_row("id", ft.TextField(value=g.id, on_change=lambda e: on_field("id", e.control.value or ""), **kw)),
                option7_row("Nome", ft.TextField(value=g.nome, on_change=lambda e: on_field("nome", e.control.value or ""), **kw)),
                option7_row(
                    "Descricao",
                    ft.TextField(
                        value=g.descricao,
                        multiline=True,
                        min_lines=2,
                        max_lines=5,
                        on_change=lambda e: on_field("descricao", e.control.value or ""),
                        **kw,
                    ),
                    align=ft.CrossAxisAlignment.START,
                ),
                ft.Text("Apps nesta gerencia", size=13, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                *checks,
            ],
        )

    if sel.startswith("sub:"):
        _, s_raw, sub_raw = sel.split(":")
        s = form.setores[int(s_raw)]
        sub = s.sub_setores[int(sub_raw)]
        return ft.Column(
            spacing=10,
            tight=True,
            controls=[
                ft.Text(f"Sub-setor de {s.nome or s.id}", size=16, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                option7_row("id", ft.TextField(value=sub.id, on_change=lambda e: on_field("id", e.control.value or ""), **kw)),
                option7_row("Nome", ft.TextField(value=sub.nome, on_change=lambda e: on_field("nome", e.control.value or ""), **kw)),
                option7_row(
                    "Descricao",
                    ft.TextField(
                        value=sub.descricao,
                        multiline=True,
                        min_lines=2,
                        max_lines=5,
                        on_change=lambda e: on_field("descricao", e.control.value or ""),
                        **kw,
                    ),
                    align=ft.CrossAxisAlignment.START,
                ),
            ],
        )

    if sel.startswith("s:"):
        s = form.setores[int(sel.split(":")[1])]
        return ft.Column(
            spacing=10,
            tight=True,
            controls=[
                ft.Text("Setor", size=16, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                option7_row("id", ft.TextField(value=s.id, on_change=lambda e: on_field("id", e.control.value or ""), **kw)),
                option7_row("Nome", ft.TextField(value=s.nome, on_change=lambda e: on_field("nome", e.control.value or ""), **kw)),
                option7_row(
                    "Descricao",
                    ft.TextField(
                        value=s.descricao,
                        multiline=True,
                        min_lines=2,
                        max_lines=5,
                        on_change=lambda e: on_field("descricao", e.control.value or ""),
                        **kw,
                    ),
                    align=ft.CrossAxisAlignment.START,
                ),
            ],
        )

    return ft.Container()
