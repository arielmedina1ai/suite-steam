"""Componentes reutilizaveis da UI (sidebar, itens de app)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

import config
from models import AppInfo, setores_do_catalogo


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


def build_sidebar(
    apps: list[AppInfo],
    *,
    home_selected: bool,
    selected_setor: str | None,
    on_home: Callable[[], None],
    on_select_setor: Callable[[str], None],
) -> ft.Control:
    setores = setores_do_catalogo(apps)
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
        ft.Container(
            padding=ft.Padding.only(left=12, top=16, bottom=6),
            content=ft.Text("SETORES", size=11, color="#8AA797", weight=ft.FontWeight.BOLD),
        ),
    ]

    if setores:
        for nome in setores:
            items.append(
                _nav_item(
                    label=nome,
                    icon=ft.Icons.FOLDER_OUTLINED,
                    selected=(not home_selected and selected_setor == nome),
                    on_click=lambda s=nome: on_select_setor(s),
                )
            )
    else:
        items.append(
            ft.Container(
                padding=12,
                content=ft.Text(
                    "Nenhum setor no catalogo. Defina o campo \"setor\" nos apps.",
                    size=12,
                    color="#8AA797",
                ),
            )
        )

    return ft.Container(
        width=260,
        bgcolor=config.COLOR_SURFACE,
        padding=12,
        content=ft.Column(controls=items, spacing=4, scroll=ft.ScrollMode.AUTO, expand=True),
    )
