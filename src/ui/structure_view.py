"""Aba Estrutura: gerencias, setores, sub-setores e onde os apps ficam."""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

import config
from models import CatalogData
from services.catalog_publish import StructureFormState
from ui.progress_util import bar_value, label as progress_label
from ui.publish_view import _remember_scroll, bind_form_section, notice_banner, option7_text

_DEL_ICON = getattr(ft.Icons, "DELETE", None) or getattr(ft.Icons, "DELETE_FOREVER", ft.Icons.CLOSE)


def _section_divider() -> ft.Control:
    return ft.Container(
        height=1,
        bgcolor="#2A3A33",
        margin=ft.Margin.symmetric(vertical=10),
    )


def _node(
    title: str,
    subtitle: str,
    *,
    selected: bool,
    on_click: Callable[[], None],
) -> ft.Control:
    return ft.Container(
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


def _apps_side(catalog: CatalogData, app_ids: list[str]) -> ft.Control:
    by_id = {a.id: a for a in catalog.apps}
    chips: list[ft.Control] = []
    for aid in app_ids:
        app = by_id.get(aid)
        chips.append(_app_chip(app.nome if app is not None else aid))
    if not chips:
        chips.append(ft.Text("nenhum app", size=11, color="#8AA797"))
    return ft.Row(wrap=True, spacing=6, run_spacing=6, controls=chips)


def _icon_btn(icon, tooltip: str, on_click: Callable[[], None]) -> ft.Control:
    attempts = [
        {
            "icon": icon,
            "icon_size": 18,
            "icon_color": config.COLOR_ACCENT,
            "tooltip": tooltip,
            "on_click": lambda e: on_click(),
        },
        {
            "icon": icon,
            "icon_color": config.COLOR_ACCENT,
            "on_click": lambda e: on_click(),
        },
    ]
    for kwargs in attempts:
        try:
            return ft.IconButton(**kwargs)
        except TypeError:
            continue
    return ft.OutlinedButton(content=tooltip, on_click=lambda e: on_click())


def _tree_row(
    node: ft.Control,
    catalog: CatalogData,
    app_ids: list[str],
    *,
    indent: int = 0,
    actions: list[ft.Control] | None = None,
) -> ft.Control:
    row_controls: list[ft.Control] = [
        ft.Container(width=240, content=node),
    ]
    if actions:
        row_controls.append(ft.Row(spacing=2, controls=actions))
    row_controls.append(ft.Container(expand=True, content=_apps_side(catalog, app_ids)))
    return ft.Container(
        margin=ft.Margin.only(left=indent),
        content=ft.Row(
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=row_controls,
        ),
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


def _all_app_ids(catalog: CatalogData) -> list[str]:
    return [a.id for a in catalog.apps]


def bind_structure_form(
    catalog: CatalogData,
    form: StructureFormState,
    *,
    on_select: Callable[[str], None],
    on_field: Callable[[str, str], None],
    on_toggle_app: Callable[[str, bool], None],
    on_new: Callable[[str], None],
    on_new_subsetor: Callable[[int], None],
    on_delete: Callable[[str], None],
    on_save: Callable[[], None],
    on_reopen: Callable[[], None],
    select_holder: ft.Container,
    edit_holder: ft.Container,
) -> None:
    tree: list[ft.Control] = [
        _section_divider(),
        ft.Text("Gerencias", size=14, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
        ft.Row(
            spacing=8,
            controls=[
                ft.OutlinedButton(content="Nova gerencia", icon=ft.Icons.ADD, on_click=lambda e: on_new("gerencia")),
            ],
        ),
        _tree_row(
            _node(
                f"(Geral) — {form.gerencia_geral or 'Geral'}",
                "lista completa do catalogo",
                selected=form.sel == "geral",
                on_click=lambda: on_select("geral"),
            ),
            catalog,
            _all_app_ids(catalog),
        ),
    ]
    for i, g in enumerate(form.gerencias):
        key = f"g:{i}"
        tree.append(
            _tree_row(
                _node(
                    g.nome or g.id or "Gerencia",
                    g.id,
                    selected=form.sel == key,
                    on_click=lambda k=key: on_select(k),
                ),
                catalog,
                g.apps,
            )
        )

    tree.extend(
        [
            _section_divider(),
            ft.Text("Setores", size=14, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
            ft.Row(
                spacing=8,
                controls=[
                    ft.OutlinedButton(content="Novo setor", icon=ft.Icons.ADD, on_click=lambda e: on_new("setor")),
                ],
            ),
        ]
    )
    for si, s in enumerate(form.setores):
        skey = f"s:{si}"
        tree.append(
            _tree_row(
                _node(
                    s.nome or s.id or "Setor",
                    s.id,
                    selected=form.sel == skey,
                    on_click=lambda k=skey: on_select(k),
                ),
                catalog,
                _setor_apps(catalog, s.orig_id or s.id),
                actions=[
                    _icon_btn(ft.Icons.ADD, "Novo sub-setor", lambda i=si: on_new_subsetor(i)),
                    _icon_btn(_DEL_ICON, "Excluir setor", lambda k=skey: on_delete(k)),
                ],
            )
        )
        for subi, sub in enumerate(s.sub_setores):
            subkey = f"sub:{si}:{subi}"
            tree.append(
                _tree_row(
                    _node(
                        sub.nome or sub.id or "Sub-setor",
                        sub.id,
                        selected=form.sel == subkey,
                        on_click=lambda k=subkey: on_select(k),
                    ),
                    catalog,
                    _setor_apps(catalog, s.orig_id or s.id, sub.orig_id or sub.id),
                    indent=20,
                    actions=[
                        _icon_btn(_DEL_ICON, "Excluir sub-setor", lambda k=subkey: on_delete(k)),
                    ],
                )
            )

    bind_form_section(
        select_holder,
        "Selecionar ou adicionar",
        [
            ft.Text(
                "Arvore do catalog.json. Apps de cada no aparecem a direita. (Geral) mostra todos.",
                size=13,
                color="#8AA797",
            ),
            *tree,
        ],
        on_scroll_offset=lambda v: _remember_scroll(form, "select_scroll", v),
    )
    editor = _editor(catalog, form, on_field=on_field, on_toggle_app=on_toggle_app)
    done_text = form.notice if form.notice else ("" if form.busy else form.message)
    bind_form_section(
        edit_holder,
        "Editar",
        [editor],
        on_scroll_offset=lambda v: _remember_scroll(form, "edit_scroll", v),
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
    def _draft_text(obj, label: str, key: str, *, multiline: bool = False) -> ft.Control:
        return option7_text(
            label,
            getattr(obj, key),
            changed=obj.is_changed(key),
            on_commit=lambda v, k=key: on_field(k, v),
            is_changed=lambda k=key: obj.is_changed(k),
            multiline=multiline,
            min_lines=2 if multiline else 1,
            max_lines=5 if multiline else 1,
        )

    sel = form.sel or ""
    if sel == "geral" or not sel:
        return ft.Column(
            spacing=10,
            tight=True,
            controls=[
                ft.Text("Geral", size=16, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                option7_text(
                    "Rotulo Geral",
                    form.gerencia_geral,
                    changed=form.gerencia_geral != form.orig_gerencia_geral,
                    on_commit=lambda v: on_field("gerencia_geral", v),
                    is_changed=lambda: form.gerencia_geral != form.orig_gerencia_geral,
                ),
                ft.Text(
                    "Opcao vazia do filtro de gerencia (gerencia_geral). "
                    "A direita desta sessao, (Geral) lista todos os apps do catalogo — "
                    "atribuir a uma gerencia nao remove daqui.",
                    size=12,
                    color="#8AA797",
                ),
            ],
        )

    if sel.startswith("g:"):
        idx = int(sel.split(":")[1])
        g = form.gerencias[idx]
        apps_changed = g.is_changed("apps")
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
                _draft_text(g, "id", "id"),
                _draft_text(g, "Nome", "nome"),
                _draft_text(g, "Descricao", "descricao", multiline=True),
                ft.Container(
                    bgcolor="#2A3820" if apps_changed else None,
                    border_radius=8,
                    padding=8 if apps_changed else 0,
                    border=ft.Border(left=ft.BorderSide(3, config.COLOR_ACCENT)) if apps_changed else None,
                    content=ft.Column(
                        spacing=6,
                        tight=True,
                        controls=[
                            ft.Text("Apps nesta gerencia", size=13, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                            *checks,
                        ],
                    ),
                ),
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
                _draft_text(sub, "id", "id"),
                _draft_text(sub, "Nome", "nome"),
                _draft_text(sub, "Descricao", "descricao", multiline=True),
            ],
        )

    if sel.startswith("s:"):
        s = form.setores[int(sel.split(":")[1])]
        return ft.Column(
            spacing=10,
            tight=True,
            controls=[
                ft.Text("Setor", size=16, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                _draft_text(s, "id", "id"),
                _draft_text(s, "Nome", "nome"),
                _draft_text(s, "Descricao", "descricao", multiline=True),
            ],
        )

    return ft.Container()
