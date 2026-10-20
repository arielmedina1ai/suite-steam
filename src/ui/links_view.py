"""Pagina Links: grupos do links.json e um botao por item."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import flet as ft

import config
from models import LinkGroup, LinkItem
from services.url_launch import open_https_url

_EMPTY = "Nenhum link."


def link_face(item: LinkItem) -> ft.Control:
    """Titulo em negrito e descricao. Sem clique."""
    lines: list[ft.Control] = [
        ft.Text(
            item.titulo,
            size=16,
            weight=ft.FontWeight.BOLD,
            color=config.COLOR_TEXT,
        )
    ]
    if item.descricao:
        lines.append(ft.Text(item.descricao, size=13, color="#B9CEC3"))
    return ft.Column(spacing=4, tight=True, controls=lines)


def link_card(
    item: LinkItem,
    page: Any,
    *,
    is_favorite: bool,
    on_toggle_favorite: Callable[[str], None] | None,
) -> ft.Control:
    """Cartao do link: a estrela alterna o favorito; o resto abre o https.

    A url fica no botao. A estrela e irma do botao, no mesmo fundo, para o
    clique dela nao abrir o navegador.
    """
    url = item.url

    def _open(e=None, target: str = url) -> None:
        stored = target
        control = getattr(e, "control", None)
        data = getattr(control, "data", None) if control is not None else None
        if isinstance(data, str) and data.strip():
            stored = data.strip()
        try:
            open_https_url(page, stored)
        except Exception:
            return

    def _toggle(e=None, target: str = url) -> None:
        if not callable(on_toggle_favorite):
            return
        try:
            on_toggle_favorite(target)
        except Exception:
            return

    opener = ft.Button(
        content=link_face(item),
        data=url,
        expand=True,
        bgcolor=config.COLOR_SURFACE,
        elevation=0,
        style=ft.ButtonStyle(
            bgcolor=config.COLOR_SURFACE,
            elevation=0,
            alignment=ft.Alignment.CENTER_LEFT,
            padding=ft.Padding.symmetric(horizontal=12, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=12),
        ),
        on_click=_open,
    )
    star = ft.IconButton(
        icon=ft.Icons.STAR if is_favorite else ft.Icons.STAR_BORDER,
        icon_color=config.COLOR_ACCENT if is_favorite else "#8AA797",
        icon_size=22,
        tooltip="Remover dos favoritos" if is_favorite else "Adicionar aos favoritos",
        on_click=_toggle,
    )
    return ft.Container(
        bgcolor=config.COLOR_SURFACE,
        border_radius=12,
        padding=ft.Padding.only(right=4),
        content=ft.Row(
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[opener, star],
        ),
    )


def build_links_view(
    groups: list[LinkGroup],
    page: Any,
    *,
    favorite_urls: list[str] | None = None,
    on_toggle_favorite: Callable[[str], None] | None = None,
) -> ft.Control:
    """So os grupos do links.json, na ordem do arquivo.

    Arquivo valido sem itens: uma linha curta. A estrela nao cria grupo.
    """
    urls = list(favorite_urls or [])
    favorite_keys = {(url or "").strip() for url in urls if (url or "").strip()}
    sections: list[ft.Control] = [
        ft.Text("Links", size=26, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
    ]
    if not groups:
        sections.append(ft.Text(_EMPTY, size=14, color="#8AA797"))
        return ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=16, controls=sections)

    for group in groups:
        block: list[ft.Control] = [
            ft.Text(group.titulo, size=18, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
        ]
        for item in group.links:
            block.append(
                link_card(
                    item,
                    page,
                    is_favorite=(item.url or "").strip() in favorite_keys,
                    on_toggle_favorite=on_toggle_favorite,
                )
            )
        sections.append(
            ft.Column(
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=block,
            )
        )
    return ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=20, controls=sections)
