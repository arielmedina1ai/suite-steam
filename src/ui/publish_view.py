"""Tela Publicar: dropdown de app, formulario sempre visivel e galeria de estilos."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import flet as ft

import config
from models import CatalogData
from services.catalog_publish import PublishFormState
from ui.progress_util import bar_value, label as progress_label

NEW_APP_KEY = "__new__"

_SAMPLE_LABEL = "Nome do aplicativo"
_SAMPLE_VALUE = "Relatorio de Producao"
_SAMPLE_DD_KEYS = ("setor-1", "setor-2", "producao")
_SAMPLE_DD_TEXTS = ("Setor 1", "Setor 2", "Producao")

_OUTLINE = getattr(getattr(ft, "InputBorder", None), "OUTLINE", None)
_UNDERLINE = getattr(getattr(ft, "InputBorder", None), "UNDERLINE", None)
_NONE = getattr(getattr(ft, "InputBorder", None), "NONE", None)


def _none_to_empty(value: str | None) -> str:
    raw = (value or "").strip()
    return "" if raw in {"", "_none_"} else raw


def _kw_border(kind: object) -> dict:
    return {"border": kind} if kind is not None else {}


def _sample_dd_options() -> list:
    return [
        ft.DropdownOption(key=k, text=t)
        for k, t in zip(_SAMPLE_DD_KEYS, _SAMPLE_DD_TEXTS, strict=True)
    ]


def _image_preview(src: str, *, size: int = 72) -> ft.Control:
    empty = ft.Container(
        width=size,
        height=size,
        border_radius=8,
        bgcolor=config.COLOR_BG,
        alignment=ft.Alignment.CENTER,
        content=ft.Text("sem imagem", size=10, color="#8AA797", text_align=ft.TextAlign.CENTER),
    )
    if not (src or "").strip():
        return empty
    return ft.Container(
        width=size,
        height=size,
        border_radius=8,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        bgcolor=config.COLOR_BG,
        content=ft.Image(
            src=src,
            width=size,
            height=size,
            fit=ft.BoxFit.COVER,
            error_content=empty,
        ),
    )


def _short(path_or_url: str, fallback: str) -> str:
    raw = (path_or_url or "").strip()
    if not raw:
        return fallback
    if len(raw) > 90:
        return raw[:40] + "…" + raw[-40:]
    return raw


def build_publish_view(
    catalog: CatalogData,
    form: PublishFormState,
    *,
    on_select_app: Callable[[str], None],
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
    app_value = form.editing_id or NEW_APP_KEY
    app_options = [ft.DropdownOption(key=NEW_APP_KEY, text="Novo Aplicativo")]
    known_ids = {NEW_APP_KEY}
    for app in catalog.apps:
        app_options.append(ft.DropdownOption(key=app.id, text=app.nome))
        known_ids.add(app.id)
    if app_value not in known_ids:
        app_value = NEW_APP_KEY

    def _tf(label: str, key: str, value: str, *, multiline: bool = False) -> ft.Control:
        return ft.Column(
            spacing=4,
            tight=True,
            controls=[
                ft.Text(label, size=12, color="#8AA797"),
                ft.TextField(
                    value=value,
                    hint_text=label,
                    multiline=multiline,
                    min_lines=3 if multiline else 1,
                    max_lines=6 if multiline else 1,
                    filled=False,
                    border_color="#22332B",
                    color=config.COLOR_TEXT,
                    **_kw_border(_OUTLINE),
                    on_change=lambda e, k=key: on_field(k, e.control.value or ""),
                ),
            ],
        )

    def _dd(label: str, key: str, value: str, options: list, *, default: str = "") -> ft.Control:
        return ft.Column(
            spacing=4,
            tight=True,
            controls=[
                ft.Text(label, size=12, color="#8AA797"),
                ft.Dropdown(
                    value=value,
                    options=options,
                    filled=False,
                    border_color="#22332B",
                    color=config.COLOR_TEXT,
                    **_kw_border(_OUTLINE),
                    on_select=lambda e, k=key, d=default: on_field(k, e.control.value or d),
                ),
            ],
        )

    def _file_block(
        label: str,
        key: str,
        path: str,
        current_url: str,
        *,
        preview: bool,
    ) -> ft.Control:
        chosen = Path(path).name if path else ""
        current_txt = _short(current_url, "nenhuma URL atual")
        chosen_txt = _short(path, "nenhum arquivo escolhido")
        src = path.strip() if path.strip() else (current_url or "").strip()
        lines = [
            ft.Text(label, size=12, color="#8AA797"),
            ft.Text(f"Atual: {current_txt}", size=12, color="#B9CEC3"),
            ft.Text(f"Arquivo: {chosen_txt}", size=12, color="#B9CEC3"),
            ft.OutlinedButton(
                content="Escolher arquivo",
                icon=ft.Icons.FOLDER_OPEN,
                disabled=form.busy,
                on_click=lambda e, k=key: on_pick(k),
            ),
        ]
        if chosen:
            lines.insert(3, ft.Text(f"Selecionado: {chosen}", size=12, color=config.COLOR_ACCENT))
        body: list[ft.Control] = [ft.Column(spacing=4, tight=True, expand=True, controls=lines)]
        if preview:
            body.append(_image_preview(src))
        return ft.Container(
            bgcolor=config.COLOR_BG,
            border_radius=8,
            padding=12,
            content=ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=body,
            ),
        )

    heading = "Novo aplicativo" if not form.editing_id else f"Editar: {form.nome or form.editing_id}"

    form_controls: list[ft.Control] = [
        ft.Dropdown(
            label="Aplicativo",
            value=app_value,
            options=app_options,
            filled=True,
            fill_color=config.COLOR_BG,
            border_color="#22332B",
            color=config.COLOR_TEXT,
            on_select=lambda e: on_select_app(e.control.value or NEW_APP_KEY),
        ),
        ft.Text(heading, size=18, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
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
        _dd("Gerencia", "gerencia_id", form.gerencia_id or "_none_", gerencia_options),
        _dd("Setor", "setor_id", form.setor_id or "_none_", setor_options),
        _dd("Sub-setor", "sub_setor_id", form.sub_setor_id or "_none_", sub_options),
        _file_block("Arquivo do app", "app", form.app_path, form.current_download, preview=False),
        _file_block("Capa", "capa", form.capa_path, form.current_capa, preview=True),
        _file_block("Icone", "icone", form.icone_path, form.current_icone, preview=True),
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
            ft.Container(
                bgcolor=config.COLOR_SURFACE,
                border_radius=10,
                padding=20,
                content=ft.Column(spacing=12, tight=True, controls=form_controls),
            ),
            _style_gallery(),
        ],
    )


def _style_gallery() -> ft.Control:
    options = [
        ("Opção 1", "Rotulo acima, campo com contorno.", _option_1()),
        ("Opção 2", "Sem rotulo: so placeholder dentro do campo.", _option_2()),
        ("Opção 3", "Rotulo a esquerda, campo a direita, uma linha.", _option_3()),
        ("Opção 4", "Rotulo flutuante no contorno (Material outlined).", _option_4()),
        ("Opção 5", "Campo preenchido, rotulo pequeno no topo interno.", _option_5()),
        ("Opção 6", "So sublinhado, rotulo pequeno acima.", _option_6()),
        ("Opção 7", "Rotulo em negrito a esquerda, campo sem borda.", _option_7()),
        ("Opção 8", "Pilula: rotulo a esquerda, valor a direita.", _option_8()),
        ("Opção 9", "Rotulo minusculo no canto do contorno, valor centralizado.", _option_9()),
        ("Opção 10", "Cartao: titulo grande fora, campo e lista so com placeholder.", _option_10()),
    ]
    cards: list[ft.Control] = [
        ft.Text("Estilos de campo", size=18, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT),
        ft.Text(
            "Amostras com o mesmo conteudo para escolher um numero. "
            "Nao alteram o formulario de publicacao.",
            size=13,
            color="#8AA797",
        ),
    ]
    for title, hint, body in options:
        cards.append(
            ft.Container(
                bgcolor=config.COLOR_SURFACE,
                border_radius=10,
                padding=16,
                content=ft.Column(
                    spacing=10,
                    tight=True,
                    controls=[
                        ft.Text(title, size=16, weight=ft.FontWeight.BOLD, color=config.COLOR_ACCENT),
                        ft.Text(hint, size=12, color="#8AA797"),
                        body,
                    ],
                ),
            )
        )
    return ft.Column(spacing=12, tight=True, controls=cards)


def _sample_field(**kwargs) -> ft.TextField:
    defaults = {
        "value": _SAMPLE_VALUE,
        "color": config.COLOR_TEXT,
        "border_color": "#22332B",
        "cursor_color": config.COLOR_ACCENT,
    }
    defaults.update(kwargs)
    return ft.TextField(**defaults)


def _sample_dropdown(**kwargs) -> ft.Dropdown:
    defaults = {
        "value": _SAMPLE_DD_KEYS[0],
        "options": _sample_dd_options(),
        "color": config.COLOR_TEXT,
        "border_color": "#22332B",
    }
    defaults.update(kwargs)
    return ft.Dropdown(**defaults)


def _option_1() -> ft.Control:
    """Label above, outlined field."""
    return ft.Column(
        spacing=10,
        tight=True,
        controls=[
            ft.Column(
                spacing=4,
                tight=True,
                controls=[
                    ft.Text(_SAMPLE_LABEL, size=12, color="#8AA797"),
                    _sample_field(hint_text=_SAMPLE_LABEL, **_kw_border(_OUTLINE)),
                ],
            ),
            ft.Column(
                spacing=4,
                tight=True,
                controls=[
                    ft.Text(_SAMPLE_LABEL, size=12, color="#8AA797"),
                    _sample_dropdown(**_kw_border(_OUTLINE)),
                ],
            ),
        ],
    )


def _option_2() -> ft.Control:
    """No label, placeholder only."""
    return ft.Column(
        spacing=10,
        tight=True,
        controls=[
            _sample_field(hint_text=_SAMPLE_LABEL, **_kw_border(_OUTLINE)),
            _sample_dropdown(hint_text=_SAMPLE_LABEL, **_kw_border(_OUTLINE)),
        ],
    )


def _option_3() -> ft.Control:
    """Label left, field right, one row."""
    def row(control: ft.Control) -> ft.Control:
        return ft.Row(
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Container(width=160, content=ft.Text(_SAMPLE_LABEL, size=13, color=config.COLOR_TEXT)),
                ft.Container(expand=True, content=control),
            ],
        )

    return ft.Column(
        spacing=8,
        tight=True,
        controls=[
            row(_sample_field(**_kw_border(_OUTLINE))),
            row(_sample_dropdown(**_kw_border(_OUTLINE))),
        ],
    )


def _option_4() -> ft.Control:
    """Floating label on the outline (Material outlined)."""
    return ft.Column(
        spacing=10,
        tight=True,
        controls=[
            _sample_field(label=_SAMPLE_LABEL, filled=False, **_kw_border(_OUTLINE)),
            _sample_dropdown(label=_SAMPLE_LABEL, filled=False, **_kw_border(_OUTLINE)),
        ],
    )


def _option_5() -> ft.Control:
    """Filled field, small label inside at the top."""
    return ft.Column(
        spacing=10,
        tight=True,
        controls=[
            _sample_field(
                label=_SAMPLE_LABEL,
                filled=True,
                fill_color="#1C2A24",
                **_kw_border(_NONE) if _NONE is not None else _kw_border(_OUTLINE),
            ),
            _sample_dropdown(
                label=_SAMPLE_LABEL,
                filled=True,
                fill_color="#1C2A24",
                **_kw_border(_NONE) if _NONE is not None else _kw_border(_OUTLINE),
            ),
        ],
    )


def _option_6() -> ft.Control:
    """Underline only, small label above."""
    return ft.Column(
        spacing=10,
        tight=True,
        controls=[
            ft.Column(
                spacing=2,
                tight=True,
                controls=[
                    ft.Text(_SAMPLE_LABEL, size=11, color="#8AA797"),
                    _sample_field(**_kw_border(_UNDERLINE)),
                ],
            ),
            ft.Column(
                spacing=2,
                tight=True,
                controls=[
                    ft.Text(_SAMPLE_LABEL, size=11, color="#8AA797"),
                    _sample_dropdown(**_kw_border(_UNDERLINE)),
                ],
            ),
        ],
    )


def _option_7() -> ft.Control:
    """Bold label on the left, borderless field."""
    def row(control: ft.Control) -> ft.Control:
        return ft.Row(
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Container(
                    width=170,
                    content=ft.Text(_SAMPLE_LABEL, size=14, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                ),
                ft.Container(expand=True, content=control),
            ],
        )

    borderless = _kw_border(_NONE)
    return ft.Column(
        spacing=4,
        tight=True,
        controls=[
            row(_sample_field(filled=True, fill_color=config.COLOR_BG, **borderless)),
            row(_sample_dropdown(filled=True, fill_color=config.COLOR_BG, **borderless)),
        ],
    )


def _option_8() -> ft.Control:
    """Pill: label inside on the left, value on the right."""
    def pill(value_control: ft.Control) -> ft.Control:
        return ft.Container(
            bgcolor="#1C2A24",
            border_radius=28,
            padding=ft.Padding.symmetric(horizontal=16, vertical=6),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(_SAMPLE_LABEL, size=12, color="#8AA797"),
                    ft.Container(expand=True, content=value_control),
                ],
            ),
        )

    borderless = _kw_border(_NONE)
    return ft.Column(
        spacing=10,
        tight=True,
        controls=[
            pill(
                _sample_field(
                    text_align=ft.TextAlign.RIGHT,
                    filled=False,
                    **borderless,
                )
            ),
            pill(_sample_dropdown(filled=False, **borderless)),
        ],
    )


def _option_9() -> ft.Control:
    """Tiny label on the top-left corner of the border, value centered."""
    def notched(inner: ft.Control) -> ft.Control:
        return ft.Stack(
            height=64,
            controls=[
                ft.Container(
                    margin=ft.Margin.only(top=8),
                    border=ft.Border(
                        left=ft.BorderSide(1, config.COLOR_ACCENT),
                        top=ft.BorderSide(1, config.COLOR_ACCENT),
                        right=ft.BorderSide(1, config.COLOR_ACCENT),
                        bottom=ft.BorderSide(1, config.COLOR_ACCENT),
                    ),
                    border_radius=8,
                    alignment=ft.Alignment.CENTER,
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    content=inner,
                ),
                ft.Container(
                    left=12,
                    top=0,
                    bgcolor=config.COLOR_SURFACE,
                    padding=ft.Padding.symmetric(horizontal=6, vertical=0),
                    content=ft.Text(_SAMPLE_LABEL, size=10, color=config.COLOR_ACCENT),
                ),
            ],
        )

    borderless = _kw_border(_NONE)
    return ft.Column(
        spacing=14,
        tight=True,
        controls=[
            notched(
                _sample_field(
                    text_align=ft.TextAlign.CENTER,
                    filled=False,
                    **borderless,
                )
            ),
            notched(_sample_dropdown(filled=False, **borderless)),
        ],
    )


def _option_10() -> ft.Control:
    """Card: big title outside, field and dropdown with placeholder only."""
    return ft.Container(
        bgcolor=config.COLOR_BG,
        border_radius=12,
        padding=20,
        content=ft.Column(
            spacing=14,
            tight=True,
            controls=[
                ft.Text(_SAMPLE_LABEL, size=22, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                _sample_field(
                    hint_text=_SAMPLE_VALUE,
                    **_kw_border(_OUTLINE),
                ),
                _sample_dropdown(
                    hint_text=_SAMPLE_DD_TEXTS[0],
                    **_kw_border(_OUTLINE),
                ),
            ],
        ),
    )
