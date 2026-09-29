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
    catalog_http_url,
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
_INPUT_FILL = "#1A2621"
PUBLISH_SELECT_HEIGHT = 150


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
    raw = (src or "").strip()
    if not raw:
        return empty
    if raw.lower().startswith(("http://", "https://")):
        img_src = raw
    else:
        path = Path(raw)
        if not path.is_file():
            return empty
        img_src = str(path)
    return ft.Container(
        width=size,
        height=size,
        border_radius=8,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        bgcolor=config.COLOR_BG,
        content=ft.Image(
            src=img_src,
            width=size,
            height=size,
            fit=ft.BoxFit.COVER,
            error_content=empty,
        ),
    )


def _local_preview(*candidates: str) -> str:
    for raw in candidates:
        path = (raw or "").strip()
        if not path or path.lower().startswith(("http://", "https://")):
            continue
        if Path(path).is_file():
            return path
    return ""


def _remember_scroll(form, attr: str, value: float) -> None:
    setattr(form, attr, value)


def _scroll_pixels(e) -> float:
    for name in ("pixels", "scroll_offset"):
        value = getattr(e, name, None)
        if value is None:
            continue
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return 0.0


def _set_column_controls(column: ft.Column, controls: list[ft.Control]) -> None:
    current = getattr(column, "controls", None)
    if current is None:
        column.controls = list(controls)
        return
    try:
        current.clear()
        current.extend(controls)
    except Exception:
        column.controls = list(controls)


def bind_form_section(
    holder: ft.Container,
    title: str,
    controls: list[ft.Control],
    *,
    on_scroll_offset: Callable[[float], None] | None = None,
    expand: bool | int = True,
    height: int | None = None,
    footer: list[ft.Control] | None = None,
    preserve_inner: bool = False,
) -> None:
    """Reuse the same scroll Column so Flet keeps offset (no scroll_to)."""

    def _on_scroll(e) -> None:
        if on_scroll_offset is None:
            return
        on_scroll_offset(_scroll_pixels(e))

    if height is not None:
        holder.height = height
        holder.expand = False
    else:
        holder.height = None
        holder.expand = expand

    inner = getattr(holder, "_suite_scroll", None)
    title_ctrl = getattr(holder, "_suite_title", None)
    footer_col = getattr(holder, "_suite_footer", None)
    if inner is None or title_ctrl is None:
        holder.bgcolor = config.COLOR_BG
        holder.border_radius = 10
        holder.padding = 16
        holder.clip_behavior = ft.ClipBehavior.HARD_EDGE
        title_ctrl = ft.Text(title, size=14, weight=ft.FontWeight.BOLD, color=config.COLOR_ACCENT)
        inner_kwargs: dict = {
            "expand": True,
            "scroll": ft.ScrollMode.AUTO,
            "spacing": 10,
            "controls": controls,
            "on_scroll": _on_scroll,
        }
        try:
            inner = ft.Column(auto_scroll=False, **inner_kwargs)
        except TypeError:
            inner = ft.Column(**inner_kwargs)
        parts: list[ft.Control] = [title_ctrl, inner]
        if footer is not None:
            footer_col = ft.Column(spacing=8, tight=True, controls=list(footer))
            parts.append(footer_col)
        holder.content = ft.Column(
            expand=True,
            spacing=10,
            controls=parts,
        )
        holder._suite_scroll = inner
        holder._suite_title = title_ctrl
        holder._suite_footer = footer_col
        return
    title_ctrl.value = title
    inner.on_scroll = _on_scroll
    if footer is not None:
        if footer_col is None:
            footer_col = ft.Column(spacing=8, tight=True, controls=list(footer))
            holder._suite_footer = footer_col
            host = holder.content
            host_controls = getattr(host, "controls", None)
            if host_controls is None:
                holder.content = ft.Column(expand=True, spacing=10, controls=[title_ctrl, inner, footer_col])
            else:
                try:
                    host_controls.append(footer_col)
                except Exception:
                    holder.content = ft.Column(expand=True, spacing=10, controls=[title_ctrl, inner, footer_col])
        else:
            _set_column_controls(footer_col, footer)
    if not preserve_inner:
        _set_column_controls(inner, controls)


def form_section(title: str, controls: list[ft.Control], *, expand: int | bool = 1) -> ft.Control:
    holder = ft.Container(expand=expand)
    bind_form_section(holder, title, controls)
    return holder


def option7_row(
    label: str,
    control: ft.Control,
    *,
    align: ft.CrossAxisAlignment = ft.CrossAxisAlignment.CENTER,
    changed: bool = False,
) -> ft.Container:
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
    return ft.Container(
        bgcolor=_CHANGED_FILL if changed else None,
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=8, vertical=6) if changed else 0,
        border=ft.Border(left=ft.BorderSide(3, _CHANGED_BORDER)) if changed else None,
        content=row,
    )


def apply_live_highlight(box: ft.Container, field: ft.Control, changed: bool) -> None:
    box.bgcolor = _CHANGED_FILL if changed else None
    box.padding = ft.Padding.symmetric(horizontal=8, vertical=6) if changed else 0
    box.border = ft.Border(left=ft.BorderSide(3, _CHANGED_BORDER)) if changed else None
    if hasattr(field, "fill_color"):
        field.fill_color = _CHANGED_FILL if changed else _INPUT_FILL
    try:
        box.update()
        field.update()
    except Exception:
        pass


def option7_text(
    label: str,
    value: str,
    *,
    changed: bool,
    on_commit: Callable[[str], None],
    is_changed: Callable[[], bool],
    multiline: bool = False,
    min_lines: int = 1,
    max_lines: int = 1,
    align: ft.CrossAxisAlignment | None = None,
) -> ft.Container:
    field = ft.TextField(
        value=value,
        multiline=multiline,
        min_lines=min_lines,
        max_lines=max_lines,
        **field_kwargs(changed=changed),
    )
    box = option7_row(
        label,
        field,
        changed=changed,
        align=align or (ft.CrossAxisAlignment.START if multiline else ft.CrossAxisAlignment.CENTER),
    )

    def _on_change(e) -> None:
        on_commit(e.control.value or "")
        apply_live_highlight(box, field, is_changed())

    field.on_change = _on_change
    return box


def notice_banner(text: str, *, success: bool = False, conflict: bool = False, busy: bool = False) -> ft.Control:
    raw = (text or "").strip()
    if busy or not raw:
        return ft.Container(visible=False)
    if conflict:
        return ft.Container(
            bgcolor="#3A2A1F",
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
            border=ft.Border(left=ft.BorderSide(3, _CHANGED_BORDER)),
            content=ft.Text(raw, size=13, weight=ft.FontWeight.W_600, color=config.COLOR_ACCENT),
        )
    return ft.Container(
        bgcolor=_CHANGED_FILL,
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=8, vertical=6),
        border=ft.Border(left=ft.BorderSide(3, _CHANGED_BORDER)),
        content=ft.Text(raw, size=13, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
    )


def field_kwargs(*, changed: bool = False) -> dict:
    return {
        "filled": True,
        "fill_color": _CHANGED_FILL if changed else _INPUT_FILL,
        "color": config.COLOR_TEXT,
        "cursor_color": config.COLOR_ACCENT,
        "text_size": _FIELD_SIZE,
        **_borderless(),
    }


def _root_folder_label() -> str:
    raw = (config.PUBLISH_FOLDER_URL or "").rstrip("/")
    leaf = raw.split("/")[-1] if raw else ""
    leaf = leaf.split("?")[0].strip() or "raiz"
    return f"Raiz ({leaf})"


def bind_publish_form(
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
    on_delete_app: Callable[[], None] | None = None,
    select_holder: ft.Container,
    edit_holder: ft.Container,
) -> None:
    setor_options = [ft.DropdownOption(key=GERAL_KEY, text="(nenhum)")]
    for setor in catalog.setores:
        setor_options.append(ft.DropdownOption(key=setor.id, text=setor.nome))

    sub_options = [ft.DropdownOption(key=GERAL_KEY, text="(nenhum)")]
    setor = catalog.setor_by_id(form.setor_id)
    if setor is not None:
        for sub in setor.sub_setores:
            sub_options.append(ft.DropdownOption(key=sub.id, text=sub.nome))

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
        return option7_text(
            label,
            value,
            changed=form.is_changed(key),
            on_commit=lambda v, k=key: on_field(k, v),
            is_changed=lambda k=key: form.is_changed(k),
            multiline=multiline,
            min_lines=3 if multiline else 1,
            max_lines=6 if multiline else 1,
        )

    def _dd(label: str, key: str, value: str, options: list, *, default: str = "") -> ft.Control:
        changed = form.is_changed(key)
        return option7_row(
            label,
            ft.Dropdown(
                value=value,
                options=options,
                filled=True,
                fill_color=_CHANGED_FILL if changed else _INPUT_FILL,
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
        empty: str,
        extra: list[ft.Control] | None = None,
        url_key: str = "",
        preview_src: str = "",
    ) -> ft.Control:
        picked = Path(path).name if (path or "").strip() else ""
        catalog_url = catalog_http_url(current_url)
        url_changed = bool(url_key) and form.is_changed(url_key)
        changed = form.is_changed(key) or url_changed
        url_field = ft.TextField(
            value=catalog_url,
            hint_text=empty,
            multiline=True,
            min_lines=2,
            max_lines=8,
            text_size=12,
            filled=True,
            fill_color=_CHANGED_FILL if url_changed else _INPUT_FILL,
            color=config.COLOR_TEXT if catalog_url else "#8AA797",
            cursor_color=config.COLOR_ACCENT,
            **_borderless(),
        )
        if preview:
            preview_box = _image_preview(_local_preview(path, preview_src))
            link_row: ft.Control = ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    ft.Container(expand=True, content=url_field),
                    preview_box,
                ],
            )
        else:
            link_row = url_field
        detail: list[ft.Control] = [link_row]
        if extra:
            detail.extend(extra)
        detail.append(
            ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.OutlinedButton(
                        content="Escolher arquivo",
                        icon=ft.Icons.FOLDER_OPEN,
                        disabled=form.busy,
                        on_click=lambda e, k=key: on_pick(k),
                    )
                ],
            )
        )
        if picked:
            detail.append(
                ft.Text(
                    f"Arquivo local a enviar (nome original): {picked}",
                    size=12,
                    color=config.COLOR_ACCENT,
                    weight=ft.FontWeight.W_600,
                )
            )
        box = option7_row(
            label,
            ft.Column(spacing=6, tight=True, controls=detail),
            align=ft.CrossAxisAlignment.START,
            changed=changed,
        )
        if url_key:
            def _on_url(e, k=url_key, wrap=box, field=url_field) -> None:
                on_field(k, e.control.value or "")
                apply_live_highlight(wrap, field, form.is_changed(k) or form.is_changed(key))

            url_field.on_change = _on_url
        return box

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

    pasta_url_changed = form.is_changed("upload_url")
    pasta_changed = pasta_url_changed or form.is_changed("folder_choice") or form.is_changed("new_folder_name")
    pasta_field = ft.TextField(
        value=form.upload_url,
        hint_text="Cole o caminho SharePoint ou escolha uma pasta abaixo",
        multiline=True,
        min_lines=2,
        max_lines=6,
        text_size=12,
        filled=True,
        fill_color=_CHANGED_FILL if pasta_url_changed else _INPUT_FILL,
        color=config.COLOR_TEXT if (form.upload_url or "").strip() else "#8AA797",
        cursor_color=config.COLOR_ACCENT,
        **_borderless(),
    )
    pasta_detail: list[ft.Control] = [
        pasta_field,
        ft.Dropdown(
            value=folder_value,
            options=folder_options,
            filled=True,
            fill_color=_CHANGED_FILL if form.is_changed("folder_choice") else _INPUT_FILL,
            color=config.COLOR_TEXT,
            text_size=_FIELD_SIZE,
            **_borderless(),
            on_select=lambda e: on_field("folder_choice", e.control.value or ROOT_FOLDER),
        ),
    ]
    if folder_value == NEW_FOLDER:
        pasta_detail.append(
            ft.TextField(
                value=form.new_folder_name,
                hint_text="Nome da pasta nova",
                on_change=lambda e: on_field("new_folder_name", e.control.value or ""),
                **field_kwargs(changed=form.is_changed("new_folder_name")),
            )
        )
    if form.folders_busy:
        pasta_detail.append(ft.Text("Listando pastas no SharePoint...", size=11, color="#8AA797"))
    elif form.folders_error:
        pasta_detail.append(ft.Text(form.folders_error, size=11, color=config.COLOR_ACCENT))
    if on_refresh_folders is not None:
        pasta_detail.append(
            ft.TextButton(
                content="Atualizar pastas",
                disabled=form.folders_busy or form.busy,
                on_click=lambda e: on_refresh_folders(),
            )
        )
    pasta_box = option7_row(
        "Pasta Destino",
        ft.Column(spacing=6, tight=True, controls=pasta_detail),
        align=ft.CrossAxisAlignment.START,
        changed=pasta_changed,
    )

    def _on_pasta(e, wrap=pasta_box, field=pasta_field) -> None:
        on_field("upload_url", e.control.value or "")
        apply_live_highlight(
            wrap,
            field,
            form.is_changed("upload_url") or form.is_changed("folder_choice"),
        )

    pasta_field.on_change = _on_pasta

    heading = "Novo aplicativo" if not form.editing_id else f"Editar: {form.nome or form.editing_id}"
    done_text = form.notice if form.notice else ("" if form.busy else form.message)
    app_controls: list[ft.Control] = [
        ft.Container(
            expand=True,
            content=ft.Dropdown(
                value=app_value,
                options=app_options,
                filled=True,
                fill_color=_INPUT_FILL,
                color=config.COLOR_TEXT,
                text_size=_FIELD_SIZE,
                **_borderless(),
                on_select=lambda e: on_select_app(e.control.value or NEW_APP_KEY),
            ),
        )
    ]
    if form.editing_id and app_value != NEW_APP_KEY and on_delete_app is not None:
        app_controls.append(
            ft.OutlinedButton(
                content="Excluir",
                icon=ft.Icons.DELETE,
                disabled=form.busy,
                on_click=lambda e: on_delete_app(),
            )
        )
    bind_form_section(
        select_holder,
        "Selecionar ou adicionar",
        [
            option7_row(
                "Aplicativo",
                ft.Row(
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=app_controls,
                ),
            ),
            ft.Text(
                "Novo Aplicativo limpa o formulario. Escolher um app carrega para edicao.",
                size=12,
                color="#8AA797",
            ),
        ],
        on_scroll_offset=lambda v: _remember_scroll(form, "select_scroll", v),
        expand=False,
        height=PUBLISH_SELECT_HEIGHT,
    )
    bind_form_section(
        edit_holder,
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
            _dd("Setor", "setor_id", form.setor_id or GERAL_KEY, setor_options),
            _dd("Sub-setor", "sub_setor_id", form.sub_setor_id or GERAL_KEY, sub_options),
            pasta_box,
            _file_block(
                "Arquivo",
                "app",
                form.app_path,
                form.current_download,
                preview=False,
                empty="vazio no catalog.json (download_url)",
                url_key="current_download",
            ),
            _file_block(
                "Capa",
                "capa",
                form.capa_path,
                form.current_capa,
                preview=True,
                empty="vazio no catalog.json (imagem)",
                url_key="current_capa",
                preview_src=form.preview_capa,
            ),
            _file_block(
                "Icone",
                "icone",
                form.icone_path,
                form.current_icone,
                preview=True,
                empty="vazio no catalog.json (icone)",
                url_key="current_icone",
                preview_src=form.preview_icone,
            ),
        ],
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
