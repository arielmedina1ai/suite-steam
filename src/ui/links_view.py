"""Pagina Links: grupos do links.json e um botao por item."""
from __future__ import annotations

from typing import Any

import flet as ft

import config
from models import LinkGroup, LinkItem
from services.url_launch import open_https_url

_EMPTY = "Nenhum link."


def _link_button(item: LinkItem, page: Any) -> ft.Control:
    """O botao inteiro mostra titulo e descricao e guarda a url do item.

    O clique abre so https, pelo mesmo caminho da dica.
    """
    url = item.url
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

    def _click(e=None, target: str = url) -> None:
        stored = target
        control = getattr(e, "control", None)
        data = getattr(control, "data", None) if control is not None else None
        if isinstance(data, str) and data.strip():
            stored = data.strip()
        try:
            open_https_url(page, stored)
        except Exception:
            return

    return ft.Button(
        content=ft.Column(spacing=4, tight=True, controls=lines),
        data=url,
        bgcolor=config.COLOR_SURFACE,
        elevation=0,
        style=ft.ButtonStyle(
            bgcolor=config.COLOR_SURFACE,
            elevation=0,
            alignment=ft.Alignment.CENTER_LEFT,
            padding=ft.Padding.symmetric(horizontal=12, vertical=12),
            shape=ft.RoundedRectangleBorder(radius=12),
        ),
        on_click=_click,
    )


def build_links_view(groups: list[LinkGroup], page: Any) -> ft.Control:
    """Grupos na ordem do JSON. Arquivo valido sem itens: uma linha curta."""
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
            block.append(_link_button(item, page))
        sections.append(
            ft.Column(
                spacing=8,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=block,
            )
        )
    return ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=20, controls=sections)
