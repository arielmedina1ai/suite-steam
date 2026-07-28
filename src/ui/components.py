"""Componentes reutilizaveis da UI (sidebar, itens de app)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

import config
from models import AppInfo, CatalogData, GerenciaInfo, SuiteUpdateInfo, setores_visiveis


def media_src(path: str) -> str:
    """Caminho absoluto do cache ou relativo a assets/ (ex.: branding/logo.png)."""
    path = (path or "").replace("\\", "/")
    if not path:
        return ""
    if Path(path).is_absolute() or (len(path) > 2 and path[1] == ":"):
        return path
    return path


def app_badge(size: int = 40) -> ft.Control:
    """Logo da Suite (assets/branding/logo.png) ou fallback texto SP."""
    if config.BRANDING_LOGO.exists():
        return ft.Container(
            width=size,
            height=size,
            border_radius=size // 4,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Image(
                src="branding/logo.png",
                width=size,
                height=size,
                fit=ft.BoxFit.COVER,
                error_content=_badge_fallback(size),
            ),
        )
    return _badge_fallback(size)


def _badge_fallback(size: int) -> ft.Control:
    return ft.Container(
        width=size,
        height=size,
        border_radius=size // 4,
        bgcolor=config.COLOR_PRIMARY,
        alignment=ft.Alignment.CENTER,
        content=ft.Text("SP", size=max(size // 2, 10), weight=ft.FontWeight.BOLD, color=config.COLOR_ACCENT),
    )


def _default_app_icon(app: AppInfo, size: int, color: str) -> ft.Control:
    return ft.Icon(
        ft.Icons.TABLE_CHART if app.tipo.is_spreadsheet else ft.Icons.APPS,
        color=color,
        size=size,
    )


def app_icon(app: AppInfo, size: int = 24, color: str | None = None) -> ft.Control:
    """Icone do app (campo ``icone`` do catalogo) ou fallback por tipo."""
    tint = color or config.COLOR_ACCENT
    src = media_src(app.icone)
    if not src:
        return _default_app_icon(app, size, tint)

    return ft.Container(
        width=size,
        height=size,
        border_radius=max(size // 5, 4),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Image(
            src=src,
            width=size,
            height=size,
            fit=ft.BoxFit.COVER,
            error_content=_default_app_icon(app, size, tint),
        ),
    )


def _nav_item(
    *,
    label: str,
    icon: ft.Icons,
    selected: bool,
    on_click: Callable[[], None],
) -> ft.Control:
    return ft.Container(
        on_click=lambda e: on_click(),
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        bgcolor=config.COLOR_PRIMARY if selected else None,
        ink=True,
        content=ft.Row(
            spacing=10,
            controls=[
                ft.Icon(
                    icon,
                    size=20,
                    color=config.COLOR_ACCENT if selected else config.COLOR_TEXT,
                ),
                ft.Text(
                    label,
                    color=config.COLOR_TEXT,
                    size=14,
                    weight=ft.FontWeight.W_600 if selected else ft.FontWeight.NORMAL,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    expand=True,
                ),
            ],
        ),
    )


_NONE_GERENCIA = "__todas__"  # valor interno do seletor = sem filtro


def build_sidebar(
    catalog: CatalogData,
    *,
    gerencias: list[GerenciaInfo] | None = None,
    home_selected: bool,
    favorites_selected: bool,
    selected_setor_id: str | None,
    selected_gerencia_id: str,
    show_favorites: bool,
    suite_update: SuiteUpdateInfo | None,
    update_available: bool,
    update_busy: bool,
    update_message: str,
    on_home: Callable[[], None],
    on_favorites: Callable[[], None],
    on_select_setor: Callable[[str], None],
    on_select_gerencia: Callable[[str], None],
    on_download_update: Callable[[], None],
) -> ft.Control:
    setores = setores_visiveis(catalog)
    gerencia_list = gerencias if gerencias is not None else catalog.gerencias
    items: list[ft.Control] = [
        ft.Container(
            padding=ft.Padding.only(left=8, top=8, bottom=16),
            content=ft.Row(
                spacing=10,
                controls=[
                    app_badge(40),
                    ft.Column(
                        spacing=0,
                        controls=[
                            ft.Text(config.APP_NAME, weight=ft.FontWeight.BOLD, size=16, color=config.COLOR_TEXT),
                            ft.Text(f"v{config.APP_VERSION}", size=11, color="#8AA797"),
                        ],
                    ),
                ],
            ),
        ),
        _nav_item(
            label="Inicio",
            icon=ft.Icons.HOME,
            selected=home_selected,
            on_click=on_home,
        ),
    ]

    if show_favorites:
        items.append(
            _nav_item(
                label="Favoritos",
                icon=ft.Icons.STAR,
                selected=favorites_selected,
                on_click=on_favorites,
            )
        )

    # Filtro por gerencia (acima dos setores)
    if gerencia_list:
        gerencia_options = [
            ft.DropdownOption(key=_NONE_GERENCIA, text="Todas"),
        ]
        for g in gerencia_list:
            gerencia_options.append(ft.DropdownOption(key=g.id, text=g.nome))

        current_gid = selected_gerencia_id.strip() if selected_gerencia_id else _NONE_GERENCIA
        valid_keys = {o.key for o in gerencia_options}
        if current_gid not in valid_keys:
            current_gid = _NONE_GERENCIA

        def _on_gerencia_select(e) -> None:
            raw = (e.control.value or _NONE_GERENCIA).strip()
            on_select_gerencia("" if raw == _NONE_GERENCIA else raw)

        items.append(
            ft.Container(
                padding=ft.Padding.only(left=4, top=16, bottom=4, right=4),
                content=ft.Column(
                    spacing=6,
                    controls=[
                        ft.Text("GERENCIA", size=11, color="#8AA797", weight=ft.FontWeight.BOLD),
                        ft.Dropdown(
                            value=current_gid,
                            options=gerencia_options,
                            dense=True,
                            filled=True,
                            fill_color=config.COLOR_BG,
                            border_color="#22332B",
                            color=config.COLOR_TEXT,
                            text_size=13,
                            width=228,
                            on_select=_on_gerencia_select,
                        ),
                    ],
                ),
            )
        )

    items.append(
        ft.Container(
            padding=ft.Padding.only(left=12, top=12 if gerencia_list else 16, bottom=6),
            content=ft.Text("SETORES", size=11, color="#8AA797", weight=ft.FontWeight.BOLD),
        )
    )

    if setores:
        for setor in setores:
            items.append(
                _nav_item(
                    label=setor.nome,
                    icon=ft.Icons.FOLDER_OUTLINED,
                    selected=(
                        not home_selected
                        and not favorites_selected
                        and selected_setor_id == setor.id
                    ),
                    on_click=lambda s=setor.id: on_select_setor(s),
                )
            )
    else:
        items.append(
            ft.Container(
                padding=12,
                content=ft.Text(
                    "Nenhum setor com apps visiveis.",
                    size=12,
                    color="#8AA797",
                ),
            )
        )

    # Espaco flexivel + update da Suite
    items.append(ft.Container(expand=True))

    if update_available and suite_update is not None:
        items.append(
            ft.Container(
                margin=ft.Margin.only(top=8),
                padding=12,
                border_radius=10,
                bgcolor=config.COLOR_PRIMARY_DARK,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Text("Atualizacao disponivel", size=12, weight=ft.FontWeight.BOLD, color=config.COLOR_ACCENT),
                        ft.Text(
                            f"Suite v{suite_update.versao}",
                            size=12,
                            color="#B9CEC3",
                        ),
                        ft.FilledButton(
                            "Baixar atualizacao" if not update_busy else "Baixando...",
                            icon=ft.Icons.DOWNLOAD,
                            disabled=update_busy,
                            on_click=lambda e: on_download_update(),
                        ),
                        ft.Text(update_message, size=11, color="#8AA797") if update_message else ft.Container(),
                    ],
                ),
            )
        )

    return ft.Container(
        width=260,
        bgcolor=config.COLOR_SURFACE,
        padding=12,
        content=ft.Column(controls=items, spacing=4, scroll=ft.ScrollMode.AUTO, expand=True),
    )
