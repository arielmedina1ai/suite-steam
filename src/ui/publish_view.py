"""Tela Publicar: lista de apps e formulario de criar/editar."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import flet as ft

import config
from models import CatalogData
from services.catalog_publish import PublishFormState
from ui.progress_util import bar_value, label as progress_label


def _none_to_empty(value: str | None) -> str:
    raw = (value or "").strip()
    return "" if raw in {"", "_none_"} else raw


def build_publish_view(
    catalog: CatalogData,
    form: PublishFormState,
    *,
    on_new: Callable[[], None],
    on_edit: Callable[[str], None],
    on_save: Callable[[], None],
    on_cancel: Callable[[], None],
    on_pick: Callable[[str], None],
    on_field: Callable[[str, str], None],
    on_reopen: Callable[[], None],
) -> ft.Control:
    setor_options = [ft.DropdownOption(key="_none_", text="(nenhum)")]
    for setor in catalog.setores:
        setor_options.append(ft.DropdownOption(key=setor.id, text=setor.nome))

    sub_options = [ft.DropdownOption(key="_none_", text="(nenhum)")]
    setor = catalog.setor_by_id(form.setor_id)
    if setor is not None:
        for sub in setor.sub_setores:
            sub_options.append(ft.DropdownOption(key=sub.id, text=sub.nome))

    gerencia_options = [ft.DropdownOption(key="_none_", text="(nenhuma)")]
    for g in catalog.gerencias:
        gerencia_options.append(ft.DropdownOption(key=g.id, text=g.nome))

    tipo_value = form.tipo if form.tipo in {"exe", "xlsx", "xlsm"} else "exe"

    rows: list[ft.Control] = []
    for app in catalog.apps:
        setor_nome = ""
        s = catalog.setor_by_id(app.setor)
        if s is not None:
            setor_nome = s.nome
        selected = form.editing_id == app.id
        rows.append(
            ft.Container(
                bgcolor=config.COLOR_PRIMARY_DARK if selected else config.COLOR_SURFACE,
                border_radius=8,
                padding=12,
                on_click=lambda e, aid=app.id: on_edit(aid),
                ink=True,
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Column(
                            spacing=2,
                            expand=True,
                            tight=True,
                            controls=[
                                ft.Text(app.nome, size=14, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                                ft.Text(
                                    f"{setor_nome or app.setor or '—'}  ·  v{app.versao}  ·  {app.tipo.value}",
                                    size=12,
                                    color="#8AA797",
                                ),
                            ],
                        ),
                        ft.TextButton("Editar", on_click=lambda e, aid=app.id: on_edit(aid)),
                    ],
                ),
            )
        )
    if not rows:
        rows.append(ft.Text("Nenhum aplicativo no catalogo.", size=13, color="#8AA797"))

    def _tf(label: str, key: str, value: str, *, multiline: bool = False) -> ft.TextField:
        return ft.TextField(
            label=label,
            value=value,
            multiline=multiline,
            min_lines=3 if multiline else 1,
            max_lines=6 if multiline else 1,
            filled=True,
            fill_color=config.COLOR_BG,
            border_color="#22332B",
            color=config.COLOR_TEXT,
            on_change=lambda e, k=key: on_field(k, e.control.value or ""),
        )

    def _file_row(label: str, key: str, path: str, keep_hint: bool) -> ft.Control:
        name = Path(path).name if path else ("manter atual" if keep_hint else "nenhum arquivo")
        return ft.Row(
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.OutlinedButton(
                    label,
                    icon=ft.Icons.FOLDER_OPEN,
                    disabled=form.busy,
                    on_click=lambda e, k=key: on_pick(k),
                ),
                ft.Text(name, size=12, color="#B9CEC3", expand=True),
            ],
        )

    title = "Novo aplicativo" if not form.editing_id else f"Editar: {form.nome or form.editing_id}"

    form_controls: list[ft.Control] = [
        ft.Text(title, size=18, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
        _tf("Nome", "nome", form.nome),
        _tf("Descricao", "descricao", form.descricao, multiline=True),
        _tf("Versao", "versao", form.versao),
        ft.Dropdown(
            label="Tipo",
            value=tipo_value,
            options=[
                ft.DropdownOption(key="exe", text="exe"),
                ft.DropdownOption(key="xlsx", text="xlsx"),
                ft.DropdownOption(key="xlsm", text="xlsm"),
            ],
            filled=True,
            fill_color=config.COLOR_BG,
            border_color="#22332B",
            color=config.COLOR_TEXT,
            on_select=lambda e: on_field("tipo", e.control.value or "exe"),
        ),
        ft.Dropdown(
            label="Gerencia",
            value=form.gerencia_id or "_none_",
            options=gerencia_options,
            filled=True,
            fill_color=config.COLOR_BG,
            border_color="#22332B",
            color=config.COLOR_TEXT,
            on_select=lambda e: on_field("gerencia_id", _none_to_empty(e.control.value)),
        ),
        ft.Dropdown(
            label="Setor",
            value=form.setor_id or "_none_",
            options=setor_options,
            filled=True,
            fill_color=config.COLOR_BG,
            border_color="#22332B",
            color=config.COLOR_TEXT,
            on_select=lambda e: on_field("setor_id", _none_to_empty(e.control.value)),
        ),
        ft.Dropdown(
            label="Sub-setor",
            value=form.sub_setor_id or "_none_",
            options=sub_options,
            filled=True,
            fill_color=config.COLOR_BG,
            border_color="#22332B",
            color=config.COLOR_TEXT,
            on_select=lambda e: on_field("sub_setor_id", _none_to_empty(e.control.value)),
        ),
        _file_row("Arquivo do app", "app", form.app_path, keep_hint=bool(form.editing_id)),
        _file_row("Capa", "capa", form.capa_path, keep_hint=bool(form.editing_id)),
        _file_row("Icone", "icone", form.icone_path, keep_hint=bool(form.editing_id)),
        _tf("upload_url (opcional)", "upload_url", form.upload_url),
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
                    "Salvar no catalogo",
                    icon=ft.Icons.SAVE,
                    disabled=form.busy,
                    on_click=lambda e: on_save(),
                ),
                ft.TextButton("Cancelar", disabled=form.busy, on_click=lambda e: on_cancel()),
                ft.TextButton(
                    "Reabrir catalogo",
                    visible=form.conflict,
                    on_click=lambda e: on_reopen(),
                ),
            ],
        ),
    ]

    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=16,
        controls=[
            ft.Text("Publicar", size=22, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
            ft.Text(
                "Cria ou edita entradas do catalog.json no SharePoint. "
                "Gerencias e setores novos continuam sendo feitos no JSON.",
                size=13,
                color="#8AA797",
            ),
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Text("Aplicativos", size=16, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
                    ft.FilledButton("Novo aplicativo", icon=ft.Icons.ADD, on_click=lambda e: on_new()),
                ],
            ),
            ft.Column(spacing=8, controls=rows),
            ft.Container(
                bgcolor=config.COLOR_SURFACE,
                border_radius=10,
                padding=20,
                content=ft.Column(spacing=12, tight=True, controls=form_controls),
            )
            if form.show_form or form.busy or form.message
            else ft.Container(),
        ],
    )
