"""Tela inicial, favoritos e listagens por setor."""
from __future__ import annotations

from typing import Callable

import flet as ft

import config
from models import (
    AppInfo,
    GerenciaInfo,
    SetorInfo,
    group_apps_by_sub_setor,
)
from ui.components import app_badge, app_icon


# Proporcao do banner da home: 2220 x 1140 (~1.95:1)
_HERO_ASPECT = 2220 / 1140
# Exibicao compacta (~240 px de largura → ~123 px de altura)
_HERO_DISPLAY_WIDTH = 240


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


def _star_button(
    app_id: str,
    is_fav: bool,
    on_toggle: Callable[[str], None],
) -> ft.Control:
    return ft.IconButton(
        icon=ft.Icons.STAR if is_fav else ft.Icons.STAR_BORDER,
        icon_color=config.COLOR_ACCENT if is_fav else "#8AA797",
        icon_size=22,
        tooltip="Remover dos favoritos" if is_fav else "Adicionar aos favoritos",
        on_click=lambda e, aid=app_id: on_toggle(aid),
    )


def _app_card(
    app: AppInfo,
    on_select: Callable[[str], None],
    *,
    is_favorite: bool,
    on_toggle_favorite: Callable[[str], None],
) -> ft.Control:
    body = ft.Container(
        ink=True,
        on_click=lambda e, aid=app.id: on_select(aid),
        content=ft.Column(
            spacing=8,
            controls=[
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
    return ft.Container(
        width=260,
        border_radius=12,
        bgcolor=config.COLOR_SURFACE,
        padding=12,
        content=ft.Column(
            spacing=4,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        app_icon(app, size=36, color=config.COLOR_ACCENT),
                        _star_button(app.id, is_favorite, on_toggle_favorite),
                    ],
                ),
                body,
            ],
        ),
    )


def _apps_grid(
    apps: list[AppInfo],
    on_select: Callable[[str], None],
    *,
    title: str,
    empty_message: str,
    favorite_ids: set[str],
    on_toggle_favorite: Callable[[str], None],
) -> ft.Control:
    if not apps:
        return ft.Column(
            spacing=12,
            controls=[
                ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                ft.Text(empty_message, size=14, color="#8AA797"),
            ],
        )
    cards = [
        _app_card(
            app,
            on_select,
            is_favorite=app.id in favorite_ids,
            on_toggle_favorite=on_toggle_favorite,
        )
        for app in apps
    ]
    return ft.Column(
        spacing=12,
        controls=[
            ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
            ft.Row(controls=cards, wrap=True, spacing=16, run_spacing=16),
        ],
    )


def build_home(
    apps: list[AppInfo],
    on_select: Callable[[str], None],
    *,
    gerencia: GerenciaInfo | None,
    favorite_ids: set[str],
    on_toggle_favorite: Callable[[str], None],
) -> ft.Control:
    title = gerencia.nome if gerencia else config.APP_NAME
    description = (
        gerencia.descricao
        if gerencia and gerencia.descricao
        else "Nenhuma descricao configurada para esta gerencia no catalogo."
    )

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
                        ft.Text(title, size=26, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Container(height=4),
                        ft.Text(description, size=14, color="#EAF3EE"),
                    ],
                ),
            ],
        ),
    )

    listing = _apps_grid(
        apps,
        on_select,
        title="Todos os aplicativos",
        empty_message="Nenhum aplicativo nesta gerencia.",
        favorite_ids=favorite_ids,
        on_toggle_favorite=on_toggle_favorite,
    )

    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=24,
        controls=[hero, listing],
    )


def build_favoritos_view(
    apps: list[AppInfo],
    on_select: Callable[[str], None],
    *,
    favorite_ids: set[str],
    on_toggle_favorite: Callable[[str], None],
) -> ft.Control:
    header = ft.Column(
        spacing=4,
        controls=[
            ft.Text("Favoritos", size=26, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
            ft.Text(
                f"{len(apps)} aplicativo(s) favorito(s)",
                size=13,
                color="#8AA797",
            ),
        ],
    )
    listing = _apps_grid(
        apps,
        on_select,
        title="Aplicativos",
        empty_message="Nenhum favorito. Clique na estrela de um app para adicionar.",
        favorite_ids=favorite_ids,
        on_toggle_favorite=on_toggle_favorite,
    )
    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=20,
        controls=[header, listing],
    )


def build_setor_view(
    setor: SetorInfo,
    apps: list[AppInfo],
    on_select: Callable[[str], None],
    *,
    favorite_ids: set[str],
    on_toggle_favorite: Callable[[str], None],
) -> ft.Control:
    header_controls: list[ft.Control] = [
        ft.Text(setor.nome, size=26, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
    ]
    if setor.descricao:
        header_controls.append(ft.Text(setor.descricao, size=14, color="#B9CEC3"))
    header_controls.append(
        ft.Text(
            f"{len(apps)} aplicativo(s) neste setor",
            size=13,
            color="#8AA797",
        )
    )

    sections: list[ft.Control] = [
        ft.Column(spacing=6, controls=header_controls),
    ]

    groups = group_apps_by_sub_setor(apps, setor)
    if not groups:
        sections.append(ft.Text("Nenhum aplicativo neste setor.", size=14, color="#8AA797"))
    else:
        for idx, (sub, chunk) in enumerate(groups):
            if idx > 0:
                sections.append(ft.Divider(height=28, color="#22332B"))
            if sub is None:
                sub_title = "Outros"
                sub_desc = ""
            else:
                sub_title = sub.nome
                sub_desc = sub.descricao
            block: list[ft.Control] = [
                ft.Text(sub_title, size=18, weight=ft.FontWeight.W_600, color=config.COLOR_ACCENT),
            ]
            if sub_desc:
                block.append(ft.Text(sub_desc, size=13, color="#8AA797"))
            cards = [
                _app_card(
                    app,
                    on_select,
                    is_favorite=app.id in favorite_ids,
                    on_toggle_favorite=on_toggle_favorite,
                )
                for app in chunk
            ]
            block.append(ft.Row(controls=cards, wrap=True, spacing=16, run_spacing=16))
            sections.append(ft.Column(spacing=8, controls=block))

    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=16,
        controls=sections,
    )
