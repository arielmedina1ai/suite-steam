"""Tela inicial: apresentacao do setor."""
from __future__ import annotations

from typing import Callable

import flet as ft

import config
from models import AppInfo
from ui.components import app_badge


def build_home(apps: list[AppInfo], on_select: Callable[[str], None]) -> ft.Control:
    hero = ft.Container(
        border_radius=16,
        padding=32,
        gradient=ft.LinearGradient(
            begin=ft.alignment.top_left,
            end=ft.alignment.bottom_right,
            colors=[config.COLOR_PRIMARY_DARK, config.COLOR_PRIMARY],
        ),
        content=ft.Column(
            spacing=10,
            controls=[
                app_badge(56),
                ft.Text(config.SECTOR_NAME, size=30, weight=ft.FontWeight.BOLD, color="white"),
                ft.Text(config.SECTOR_TAGLINE, size=16, color=config.COLOR_ACCENT, weight=ft.FontWeight.W_600),
                ft.Container(height=8),
                ft.Text(config.SECTOR_DESCRIPTION, size=15, color="#EAF3EE"),
            ],
        ),
    )

    cards: list[ft.Control] = []
    for app in apps:
        cards.append(
            ft.Container(
                width=260,
                border_radius=12,
                bgcolor=config.COLOR_SURFACE,
                padding=16,
                on_click=lambda e, aid=app.id: on_select(aid),
                ink=True,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Icon(
                            ft.Icons.TABLE_CHART if app.tipo.value == "xlsx" else ft.Icons.APPS,
                            color=config.COLOR_ACCENT,
                            size=28,
                        ),
                        ft.Text(app.nome, size=16, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                        ft.Text(
                            app.descricao,
                            size=13,
                            color="#B9CEC3",
                            max_lines=3,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.Container(height=4),
                        ft.Row(
                            controls=[
                                ft.Container(
                                    bgcolor=config.COLOR_PRIMARY_DARK,
                                    border_radius=6,
                                    padding=ft.padding.symmetric(horizontal=8, vertical=3),
                                    content=ft.Text(app.tipo.value.upper(), size=11, color=config.COLOR_ACCENT),
                                ),
                                ft.Text(f"v{app.versao}", size=12, color="#8AA797"),
                            ],
                            spacing=8,
                        ),
                    ],
                ),
            )
        )

    featured = ft.Column(
        spacing=12,
        controls=[
            ft.Text("Aplicativos em destaque", size=20, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
            ft.Row(controls=cards, wrap=True, spacing=16, run_spacing=16),
        ],
    )

    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=24,
        controls=[hero, featured],
    )
