"""Componentes reutilizaveis da UI (sidebar, itens de app)."""
from __future__ import annotations

from typing import Callable

import flet as ft

import config
from models import AppInfo


def app_badge(size: int = 40) -> ft.Control:
    """Emblema/logo simples da Suite (nao depende de asset externo)."""
    return ft.Container(
        width=size,
        height=size,
        border_radius=size // 4,
        bgcolor=config.COLOR_PRIMARY,
        alignment=ft.Alignment.CENTER,
        content=ft.Text("SP", size=size // 2, weight=ft.FontWeight.BOLD, color=config.COLOR_ACCENT),
    )


def _sidebar_item(
    app: AppInfo,
    selected: bool,
    on_click: Callable[[str], None],
) -> ft.Control:
    return ft.Container(
        on_click=lambda e, aid=app.id: on_click(aid),
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        bgcolor=config.COLOR_PRIMARY if selected else None,
        ink=True,
        content=ft.Row(
            spacing=10,
            controls=[
                ft.Icon(
                    ft.Icons.TABLE_CHART if app.tipo.value == "xlsx" else ft.Icons.APPS,
                    color=config.COLOR_ACCENT if selected else config.COLOR_TEXT,
                    size=20,
                ),
                ft.Text(
                    app.nome,
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
    selected_id: str | None,
    on_home: Callable[[], None],
    on_select: Callable[[str], None],
) -> ft.Control:
    home_selected = selected_id is None
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
        ft.Container(
            on_click=lambda e: on_home(),
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            bgcolor=config.COLOR_PRIMARY if home_selected else None,
            ink=True,
            content=ft.Row(
                spacing=10,
                controls=[
                    ft.Icon(ft.Icons.HOME, size=20, color=config.COLOR_ACCENT if home_selected else config.COLOR_TEXT),
                    ft.Text("Inicio", size=14, color=config.COLOR_TEXT,
                            weight=ft.FontWeight.W_600 if home_selected else ft.FontWeight.NORMAL),
                ],
            ),
        ),
        ft.Container(
            padding=ft.Padding.only(left=12, top=16, bottom=6),
            content=ft.Text("APLICATIVOS", size=11, color="#8AA797", weight=ft.FontWeight.BOLD),
        ),
    ]

    if apps:
        items.extend(
            _sidebar_item(app, app.id == selected_id, on_select) for app in apps
        )
    else:
        items.append(
            ft.Container(
                padding=12,
                content=ft.Text("Nenhum app no catalogo.", size=12, color="#8AA797"),
            )
        )

    return ft.Container(
        width=260,
        bgcolor=config.COLOR_SURFACE,
        padding=12,
        content=ft.Column(controls=items, spacing=4, scroll=ft.ScrollMode.AUTO, expand=True),
    )
