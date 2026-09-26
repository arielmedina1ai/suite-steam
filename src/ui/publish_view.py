"""Tela Catálogo: formulario Publicar (Opcao 7, uma coluna)."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import flet as ft

import config
from models import CatalogData
from services.catalog_publish import (
    KEEP_FOLDER,
    NEW_FOLDER,
    PublishFormState,
    ROOT_FOLDER,
)
from ui.progress_util import bar_value, label as progress_label

NEW_APP_KEY = "__new__"
GERAL_KEY = "_none_"

_NONE = getattr(getattr(ft, "InputBorder", None), "NONE", None)
_LABEL_CHARS = 15
_LABEL_WIDTH = 128
_FIELD_SIZE = 12
_CHANGED_FILL = "#2A3820"
_CHANGED_BORDER = config.COLOR_ACCENT


def _none_to_empty(value: str | None) -> str:
    raw = (value or "").strip()
    return "" if raw in {"", GERAL_KEY} else raw


def _borderless() -> dict:
    return {"border": _NONE} if _NONE is not None else {}


def _fit_label(label: str) -> str:
    raw = (label or "").strip()
    if len(raw) <= _LABEL_CHARS:
        return raw
    return raw[: _LABEL_CHARS - 1] + "…"


def _image_preview(src: str, *, size: int = 72) -> ft.Control:
    empty = ft.Container(
        width=size,
        height=size,
        border_radius=8,
        bgcolor=config.COLOR_BG,
        alignment=ft.Alignment.CENTER,
        content=ft.Text("sem imagem", size=10, color="#8AA797", text_align=ft.TextAlign.CENTER),
    )
    url = (src or "").strip()
    if not url.startswith(("http://", "https://")):
        return empty
    return ft.Container(
        width=size,
        height=size,
        border_radius=8,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        bgcolor=config.COLOR_BG,
        content=ft.Image(
            src=url,
            width=size,
            height=size,
            fit=ft.BoxFit.COVER,
            error_content=empty,
        ),
    )


def _full_link(url: str, empty: str) -> ft.Control:
    raw = (url or "").strip()
    if raw and not raw.lower().startswith(("http://", "https://")):
        raw = ""
    shown = (
        raw.replace("/", "/\u200b").replace("?", "?\u200b").replace("&", "&\u200b")
        if raw
        else empty
    )
    overflow_kw = {}
    visible = getattr(getattr(ft, "TextOverflow", None), "VISIBLE", None)
    if visible is not None:
        overflow_kw["overflow"] = visible
    return ft.Text(
        shown,
        size=12,
        color="#B9CEC3" if raw else "#8AA797",
        selectable=True,
        no_wrap=False,
        **overflow_kw,
    )


def option7_row(
    label: str,
    control: ft.Control,
    *,
    align: ft.CrossAxisAlignment = ft.CrossAxisAlignment.CENTER,
    changed: bool = False,
) -> ft.Control:
    row = ft.Row(
        spacing=12,
        vertical_alignment=align,
        controls=[
            ft.Container(
                width=_LABEL_WIDTH,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=ft.Text(
                    _fit_label(label),
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=config.COLOR_TEXT,
                    width=_LABEL_WIDTH,
                    no_wrap=False,
                    max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ),
            ft.Container(expand=True, content=control),
        ],
    )
    if not changed:
        return row
    return ft.Container(
        bgcolor=_CHANGED_FILL,
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=8, vertical=6),
        border=ft.Border(left=ft.BorderSide(3, _CHANGED_BORDER)),
        content=row,
    )


def field_kwargs(*, changed: bool = False) -> dict:
    return {
        "filled": True,
        "fill_color": _CHANGED_FILL if changed else config.COLOR_BG,
        "color": config.COLOR_TEXT,
        "cursor_color": config.COLOR_ACCENT,
        "text_size": _FIELD_SIZE,
        **_borderless(),
    }


def form_section(title: str, controls: list[ft.Control], *, expand: int | bool = 1) -> ft.Control:
    return ft.Container(
        expand=expand,
        bgcolor=config.COLOR_BG,
        border_radius=10,
        padding=16,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Column(
            expand=True,
            spacing=10,
            controls=[
                ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=config.COLOR_ACCENT),
                ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=10,
                    controls=controls,
                ),
            ],
        ),
    )


def _root_folder_label() -> str:
    raw = (config.PUBLISH_FOLDER_URL or "").rstrip("/")
    leaf = raw.split("/")[-1] if raw else ""
    leaf = leaf.split("?")[0].strip() or "raiz"
    return f"Raiz ({leaf})"


def build_publish_form(
    catalog: CatalogData,
    form: PublishFormState,
    *,
    on_select_app: Callable[[str], None],
    on_save: Callable[[], None],
    on_cancel: Callable[[], None],
    on_pick: Callable[[str], None],
    on_field: Callable[[str, str], None],
    on_reopen: Callable[[], None],
    on_refresh_folders: Callable[[], None] | None = None,
) -> ft.Control:
    setor_options = [ft.DropdownOption(key=GERAL_KEY, text="(nenhum)")]
    for setor in catalog.setores:
        setor_options.append(ft.DropdownOption(key=setor.id, text=setor.nome))

    sub_options = [ft.DropdownOption(key=GERAL_KEY, text="(nenhum)")]
    setor = catalog.setor_by_id(form.setor_id)
    if setor is not None:
        for sub in setor.sub_setores:
            sub_options.append(ft.DropdownOption(key=sub.id, text=sub.nome))

    gerencia_options = [
        ft.DropdownOption(
            key=GERAL_KEY,
            text="(Geral)",
            content=ft.Text(
                "(Geral)",
                size=_FIELD_SIZE,
                italic=True,
                color=config.COLOR_ACCENT,
                weight=ft.FontWeight.W_600,
            ),
        )
    ]
    for g in catalog.gerencias:
        gerencia_options.append(
            ft.DropdownOption(
                key=g.id,
                text=g.nome,
                content=ft.Text(g.nome, size=_FIELD_SIZE, color=config.COLOR_TEXT),
            )
        )

    tipo_value = form.tipo if form.tipo in {"exe", "xlsx", "xlsm"} else "exe"
    app_value = form.editing_id or NEW_APP_KEY
    app_options = [ft.DropdownOption(key=NEW_APP_KEY, text="Novo Aplicativo")]
    known_ids = {NEW_APP_KEY}
    for app in catalog.apps:
        app_options.append(ft.DropdownOption(key=app.id, text=app.nome))
        known_ids.add(app.id)
    if app_value not in known_ids:
        app_value = NEW_APP_KEY

    def _tf(label: str, key: str, value: str, *, multiline: bool = False) -> ft.Control:
        changed = form.is_changed(key)
        return option7_row(
            label,
            ft.TextField(
                value=value,
                multiline=multiline,
                min_lines=3 if multiline else 1,
                max_lines=6 if multiline else 1,
                on_change=lambda e, k=key: on_field(k, e.control.value or ""),
                **field_kwargs(changed=changed),
            ),
            align=ft.CrossAxisAlignment.START if multiline else ft.CrossAxisAlignment.CENTER,
            changed=changed,
        )

    def _dd(label: str, key: str, value: str, options: list, *, default: str = "") -> ft.Control:
        changed = form.is_changed(key)
        return option7_row(
            label,
            ft.Dropdown(
                value=value,
                options=options,
                filled=True,
                fill_color=_CHANGED_FILL if changed else config.COLOR_BG,
                color=config.COLOR_TEXT,
                text_size=_FIELD_SIZE,
                **_borderless(),
                on_select=lambda e, k=key, d=default: on_field(k, e.control.value or d),
            ),
            changed=changed,
        )

    def _file_block(
        label: str,
        key: str,
        path: str,
        current_url: str,
        *,
        preview: bool,
        extra: list[ft.Control] | None = None,
    ) -> ft.Control:
        picked = Path(path).name if (path or "").strip() else ""
        changed = form.is_changed(key)
        detail: list[ft.Control] = [
            _full_link(current_url, "nenhum link compartilhado ainda"),
        ]
        if extra:
            detail.extend(extra)
        detail.append(
            ft.OutlinedButton(
                content="Escolher arquivo",
                icon=ft.Icons.FOLDER_OPEN,
                disabled=form.busy,
                on_click=lambda e, k=key: on_pick(k),
            )
        )
        if picked:
            detail.append(
                ft.Text(
                    f"Arquivo local a enviar: {picked}",
                    size=12,
                    color=config.COLOR_ACCENT,
                    weight=ft.FontWeight.W_600,
                )
            )
        body: list[ft.Control] = [ft.Column(spacing=6, tight=True, expand=True, controls=detail)]
        if preview:
            body.append(_image_preview(current_url))
        return option7_row(
            label,
            ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=body,
            ),
            align=ft.CrossAxisAlignment.START,
            changed=changed,
        )

    folder_options = []
    if form.editing_id and form.current_download:
        folder_options.append(ft.DropdownOption(key=KEEP_FOLDER, text="Manter pasta atual"))
    folder_options.append(ft.DropdownOption(key=ROOT_FOLDER, text=_root_folder_label()))
    for name in form.folders:
        folder_options.append(ft.DropdownOption(key=name, text=name))
    folder_options.append(ft.DropdownOption(key=NEW_FOLDER, text="Criar nova pasta..."))
    folder_keys = {o.key for o in folder_options}
    folder_value = form.folder_choice or (KEEP_FOLDER if form.editing_id and form.current_download else ROOT_FOLDER)
    if folder_value not in folder_keys:
        folder_value = ROOT_FOLDER if ROOT_FOLDER in folder_keys else next(iter(folder_keys), ROOT_FOLDER)

    folder_extra: list[ft.Control] = [
        ft.Dropdown(
            value=folder_value,
            options=folder_options,
            filled=True,
            fill_color=_CHANGED_FILL if form.is_changed("folder_choice") else config.COLOR_BG,
            color=config.COLOR_TEXT,
            text_size=_FIELD_SIZE,
            **_borderless(),
            on_select=lambda e: on_field("folder_choice", e.control.value or ROOT_FOLDER),
        )
    ]
    if folder_value == NEW_FOLDER:
        folder_extra.append(
            ft.TextField(
                value=form.new_folder_name,
                hint_text="Nome da pasta nova",
                on_change=lambda e: on_field("new_folder_name", e.control.value or ""),
                **field_kwargs(changed=form.is_changed("new_folder_name")),
            )
        )
    if form.folders_busy:
        folder_extra.append(ft.Text("Listando pastas no SharePoint...", size=11, color="#8AA797"))
    elif form.folders_error:
        folder_extra.append(ft.Text(form.folders_error, size=11, color=config.COLOR_ACCENT))
    if on_refresh_folders is not None:
        folder_extra.append(
            ft.TextButton(
                content="Atualizar pastas",
                disabled=form.folders_busy or form.busy,
                on_click=lambda e: on_refresh_folders(),
            )
        )

    heading = "Novo aplicativo" if not form.editing_id else f"Editar: {form.nome or form.editing_id}"
    upper = form_section(
        "Selecionar ou adicionar",
        [
            option7_row(
                "Aplicativo",
                ft.Dropdown(
                    value=app_value,
                    options=app_options,
                    filled=True,
                    fill_color=config.COLOR_BG,
                    color=config.COLOR_TEXT,
                    text_size=_FIELD_SIZE,
                    **_borderless(),
                    on_select=lambda e: on_select_app(e.control.value or NEW_APP_KEY),
                ),
            ),
            ft.Text(
                "Novo Aplicativo limpa o formulario. Escolher um app carrega para edicao.",
                size=12,
                color="#8AA797",
            ),
        ],
    )
    lower = form_section(
        "Editar",
        [
            ft.Text(heading, size=16, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
            _tf("Nome", "nome", form.nome),
            _tf("Descricao", "descricao", form.descricao, multiline=True),
            _tf("Versao", "versao", form.versao),
            _dd(
                "Tipo",
                "tipo",
                tipo_value,
                [
                    ft.DropdownOption(key="exe", text="exe"),
                    ft.DropdownOption(key="xlsx", text="xlsx"),
                    ft.DropdownOption(key="xlsm", text="xlsm"),
                ],
                default="exe",
            ),
            _dd("Gerencia", "gerencia_id", form.gerencia_id or GERAL_KEY, gerencia_options),
            _dd("Setor", "setor_id", form.setor_id or GERAL_KEY, setor_options),
            _dd("Sub-setor", "sub_setor_id", form.sub_setor_id or GERAL_KEY, sub_options),
            _file_block(
                "Arquivo",
                "app",
                form.app_path,
                form.current_download,
                preview=False,
                extra=folder_extra,
            ),
            _file_block("Capa", "capa", form.capa_path, form.current_capa, preview=True),
            _file_block("Icone", "icone", form.icone_path, form.current_icone, preview=True),
            _tf("upload_url", "upload_url", form.upload_url),
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
                        content="Salvar no catalogo",
                        icon=ft.Icons.SAVE,
                        disabled=form.busy,
                        on_click=lambda e: on_save(),
                    ),
                    ft.TextButton(content="Limpar", disabled=form.busy, on_click=lambda e: on_cancel()),
                    ft.TextButton(
                        content="Reabrir catalogo",
                        visible=form.conflict,
                        on_click=lambda e: on_reopen(),
                    ),
                ],
            ),
        ],
    )
    return ft.Column(expand=True, spacing=12, controls=[upper, lower])
