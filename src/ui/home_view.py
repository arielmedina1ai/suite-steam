"""Tela inicial e listagens por setor."""
from __future__ import annotations

from typing import Callable

import flet as ft

import config
from models import AppInfo
from ui.components import app_badge, app_icon


# Proporcao do banner da home: 2220 x 1140 (~1.95:1)
_HERO_ASPECT = 2220 / 1140
# Exibicao compacta (~480 px de largura → ~247 px de altura)
_HERO_DISPLAY_WIDTH = 480


def _hero_banner() -> ft.Control:
    """Banner da home (hero.png) em tamanho compacto, ou fallback ao logo."""
    if config.BRANDING_HERO.exists():
        width = _HERO_DISPLAY_WIDTH
        height = int(width / _HERO_ASPECT)
        return ft.Container(
            width=width,
            height=height,
            border_radius=10,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Image(
                src="branding/hero.png",
                width=width,
                height=height,
                fit=ft.BoxFit.COVER,
                error_content=app_badge(48),
            ),
        )
    return app_badge(48)


def _app_card(app: AppInfo, on_select: Callable[[str], None]) -> ft.Control:
    return ft.Container(
        width=260,
        border_radius=12,
        bgcolor=config.COLOR_SURFACE,
        padding=16,
        on_click=lambda e, aid=app.id: on_select(aid),
        ink=True,
        content=ft.Column(
            spacing=8,
            controls=[
                app_icon(app, size=36, color=config.COLOR_ACCENT),
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
                            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                            content=ft.Text(app.tipo.value.upper(), size=11, color=config.COLOR_ACCENT),
                        ),
                        ft.Text(f"v{app.versao}", size=12, color="#8AA797"),
                    ],
                    spacing=8,
                ),
            ],
        ),
    )


def _apps_grid(
    apps: list[AppInfo],
    on_select: Callable[[str], None],
    *,
    title: str,
    empty_message: str,
) -> ft.Control:
    if not apps:
        return ft.Column(
            spacing=12,
            controls=[
                ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                ft.Text(empty_message, size=14, color="#8AA797"),
            ],
        )
    cards = [_app_card(app, on_select) for app in apps]
    return ft.Column(
        spacing=12,
        controls=[
            ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
            ft.Row(controls=cards, wrap=True, spacing=16, run_spacing=16),
        ],
    )


def build_home(apps: list[AppInfo], on_select: Callable[[str], None]) -> ft.Control:
    hero = ft.Container(
        border_radius=16,
        padding=20,
        gradient=ft.LinearGradient(
            begin=ft.Alignment.TOP_LEFT,
            end=ft.Alignment.BOTTOM_RIGHT,
            colors=[config.COLOR_PRIMARY_DARK, config.COLOR_PRIMARY],
        ),
        content=ft.Row(
            spacing=24,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                _hero_banner(),
                ft.Column(
                    spacing=6,
                    expand=True,
                    controls=[
                        ft.Text(
                            config.SECTOR_NAME,
                            size=26,
                            weight=ft.FontWeight.BOLD,
                            color="white",
                        ),
                        ft.Text(
                            config.SECTOR_TAGLINE,
                            size=15,
                            color=config.COLOR_ACCENT,
                            weight=ft.FontWeight.W_600,
                        ),
                        ft.Container(height=4),
                        ft.Text(config.SECTOR_DESCRIPTION, size=14, color="#EAF3EE"),
                    ],
                ),
            ],
        ),
    )

    listing = _apps_grid(
        apps,
        on_select,
        title="Todos os aplicativos",
        empty_message="Nenhum aplicativo no catalogo.",
    )

    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=24,
        controls=[hero, listing],
    )


def build_setor_view(
    setor: str,
    apps: list[AppInfo],
    on_select: Callable[[str], None],
) -> ft.Control:
    header = ft.Column(
        spacing=4,
        controls=[
            ft.Text(setor, size=26, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
            ft.Text(
                f"{len(apps)} aplicativo(s) neste setor",
                size=13,
                color="#8AA797",
            ),
        ],
    )
    listing = _apps_grid(
        apps,
        on_select,
        title="Aplicativos",
        empty_message="Nenhum aplicativo neste setor.",
    )
    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=20,
        controls=[header, listing],
    )
