"""Tela inicial, favoritos e listagens por setor."""
from __future__ import annotations

from typing import Any, Callable

import flet as ft

import config
from models import AppInfo, Dica, GerenciaInfo, LinkItem, SetorInfo, group_apps_by_sub_setor
from services.tips import tip_text_pieces
from ui.components import app_badge, app_icon
from ui.favorite_hold import HoldSection
from ui.links_view import link_face

_HERO_ASPECT = 2220 / 1140
_HERO_DISPLAY_WIDTH = 240
_CARD_WIDTH = 260
_CARD_HEIGHT = 230
_TIP_LINE_SIZE = 13


def _hero_banner() -> ft.Control:
    if config.BRANDING_HERO.exists():
        width = _HERO_DISPLAY_WIDTH
        height = int(width / _HERO_ASPECT)
        return ft.Container(width=width, height=height, border_radius=10, clip_behavior=ft.ClipBehavior.HARD_EDGE, content=ft.Image(src="branding/hero.png", width=width, height=height, fit=ft.BoxFit.COVER, error_content=app_badge(48)))
    return app_badge(48)


def _star_button(app_id: str, is_fav: bool, on_toggle: Callable[[str], None]) -> ft.Control:
    return ft.IconButton(icon=ft.Icons.STAR if is_fav else ft.Icons.STAR_BORDER, icon_color=config.COLOR_ACCENT if is_fav else "#8AA797", icon_size=22, tooltip="Remover dos favoritos" if is_fav else "Adicionar aos favoritos", on_click=lambda e, aid=app_id: on_toggle(aid))


def _tutorial_badge() -> ft.Control:
    return ft.Container(
        bgcolor=config.COLOR_PRIMARY_DARK,
        border_radius=6,
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        content=ft.Text("Tutorial", size=11, color=config.COLOR_ACCENT),
    )


def _app_card(app: AppInfo, on_select: Callable[[str], None], *, is_favorite: bool, on_toggle_favorite: Callable[[str], None], installed: bool, opens: bool = True) -> ft.Control:
    meta: list[ft.Control] = [
        ft.Container(
            bgcolor=config.COLOR_PRIMARY_DARK,
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            content=ft.Text(app.tipo.value.upper(), size=11, color=config.COLOR_ACCENT),
        ),
        ft.Text(f"v{app.versao}", size=12, color="#8AA797"),
    ]
    if installed and app.has_tutorial:
        meta.append(_tutorial_badge())
    body = ft.Container(
        ink=True,
        expand=True,
        on_click=(lambda e, aid=app.id: on_select(aid)) if opens else None,
        content=ft.Column(
            spacing=8,
            expand=True,
            controls=[
                ft.Text(app.nome, size=16, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(app.descricao, size=13, color="#B9CEC3", max_lines=3, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ft.Row(controls=meta, spacing=8),
            ],
        ),
    )
    return ft.Container(width=_CARD_WIDTH, height=_CARD_HEIGHT, border_radius=12, bgcolor=config.COLOR_SURFACE, padding=12, clip_behavior=ft.ClipBehavior.HARD_EDGE, content=ft.Column(spacing=4, controls=[ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START, controls=[app_icon(app, size=36, color=config.COLOR_ACCENT), _star_button(app.id, is_favorite, on_toggle_favorite)]), body]))


def _apps_grid(apps: list[AppInfo], on_select: Callable[[str], None], *, title: str, empty_message: str, favorite_ids: set[str], on_toggle_favorite: Callable[[str], None], installed_ids: set[str]) -> ft.Control:
    if not apps:
        return ft.Column(spacing=12, controls=[ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT), ft.Text(empty_message, size=14, color="#8AA797")])
    cards = [_app_card(app, on_select, is_favorite=app.id in favorite_ids, on_toggle_favorite=on_toggle_favorite, installed=app.id in installed_ids) for app in apps]
    return ft.Column(spacing=12, controls=[ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT), ft.Row(controls=cards, wrap=True, spacing=16, run_spacing=16)])


def _tip_link_click(url: str, on_open_url: Callable[[str], None] | None):
    """Mesmo caminho do tutorial: UrlLauncher awaited, sem estourar se falhar."""

    def _click(_e=None) -> None:
        if not callable(on_open_url):
            return
        try:
            on_open_url(url)
        except Exception:
            return

    return _click


def _tip_body(texto: str, on_open_url: Callable[[str], None] | None) -> ft.Control:
    pieces = tip_text_pieces(texto)
    if not any(url for _text, url in pieces):
        return ft.Text(texto or "", size=13, color=config.COLOR_TEXT)
    spans: list[ft.TextSpan] = []
    for visible, url in pieces:
        if not url:
            spans.append(ft.TextSpan(visible))
            continue
        spans.append(
            ft.TextSpan(
                visible,
                style=ft.TextStyle(
                    color=config.COLOR_ACCENT,
                    decoration=ft.TextDecoration.UNDERLINE,
                ),
                on_click=_tip_link_click(url, on_open_url),
            )
        )
    return ft.Text(spans=spans, size=13, color=config.COLOR_TEXT)


def _tip_heading(title: ft.Text) -> ft.Control:
    """Lampada, Dica!, seta e o titulo na mesma linha.

    Os icones acompanham o texto Dica!. O titulo guarda a fonte, a cor e o tamanho de antes.
    """
    size = _TIP_LINE_SIZE
    color = config.COLOR_ACCENT
    return ft.Row(
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Icon(ft.Icons.LIGHTBULB, size=size, color=color),
            ft.Text("Dica!", size=size, color=color),
            ft.Icon(ft.Icons.ARROW_FORWARD, size=size, color=color),
            title,
        ],
    )


def tip_balloon(dica: Dica, on_open_url: Callable[[str], None] | None = None) -> ft.Control:
    """Balao solto na base da home. So a tela inicial o coloca na pilha.

    O titulo e texto puro. No texto, https e link markdown abrem no navegador.
    Lampada, Dica!, seta e titulo ficam na mesma linha, acima do texto.
    """
    title = ft.Text(
        dica.titulo,
        size=14,
        weight=ft.FontWeight.BOLD,
        color=config.COLOR_ACCENT,
        expand=True,
    )
    column = ft.Column(
        spacing=4,
        tight=True,
        controls=[
            _tip_heading(title),
            _tip_body(dica.texto, on_open_url),
        ],
    )
    balloon = ft.Container(
        left=0,
        right=0,
        bottom=0,
        bgcolor=config.COLOR_SURFACE,
        border_radius=12,
        padding=ft.Padding.symmetric(horizontal=16, vertical=12),
        border=ft.Border.all(1, config.COLOR_ACCENT),
        content=column,
    )
    balloon._tip_title = title
    balloon._tip_column = column
    return balloon


def apply_tip(balloon: ft.Control, dica: Dica, on_open_url: Callable[[str], None] | None = None) -> None:
    """Troca titulo e texto no balao que ja esta na tela. Nao monta a janela de novo."""
    title = getattr(balloon, "_tip_title", None)
    column = getattr(balloon, "_tip_column", None)
    controls = getattr(column, "controls", None)
    if title is None or not isinstance(controls, list) or len(controls) < 2:
        raise RuntimeError("balao de dica incompleto")
    title.value = dica.titulo or ""
    column.controls = [controls[0], _tip_body(dica.texto, on_open_url)]


def build_home(apps: list[AppInfo], on_select: Callable[[str], None], *, gerencia: GerenciaInfo | None, favorite_ids: set[str], on_toggle_favorite: Callable[[str], None], installed_ids: set[str] | None = None, tip: Dica | None = None, on_open_url: Callable[[str], None] | None = None) -> ft.Control:
    hero = ft.Container(border_radius=16, padding=20, gradient=ft.LinearGradient(begin=ft.Alignment.TOP_LEFT, end=ft.Alignment.BOTTOM_RIGHT, colors=[config.COLOR_PRIMARY_DARK, config.COLOR_PRIMARY]), content=ft.Row(spacing=24, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[_hero_banner(), ft.Column(spacing=6, expand=True, controls=[ft.Text(config.SECTOR_NAME, size=26, weight=ft.FontWeight.BOLD, color="white"), ft.Text(config.SECTOR_TAGLINE, size=14, color=config.COLOR_ACCENT), ft.Container(height=4), ft.Text(config.SECTOR_DESCRIPTION, size=14, color="#EAF3EE")])]))
    sections: list[ft.Control] = [hero]
    if gerencia is not None:
        block: list[ft.Control] = [ft.Text(gerencia.nome, size=20, weight=ft.FontWeight.W_600, color=config.COLOR_TEXT)]
        if gerencia.descricao:
            block.append(ft.Text(gerencia.descricao, size=14, color="#B9CEC3"))
        sections.append(ft.Column(spacing=6, controls=block))
    installed = installed_ids or set()
    sections.append(_apps_grid(apps, on_select, title="Todos os aplicativos", empty_message="Nenhum aplicativo nesta gerencia." if gerencia is not None else "Nenhum aplicativo no catalogo.", favorite_ids=favorite_ids, on_toggle_favorite=on_toggle_favorite, installed_ids=installed))
    show_tip = tip is not None and bool((tip.titulo or "").strip() or (tip.texto or "").strip())
    if show_tip:
        sections.append(ft.Container(height=88))
    column = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=24, controls=sections)
    if not show_tip or tip is None:
        return column
    balloon = tip_balloon(tip, on_open_url)
    stack = ft.Stack(expand=True, controls=[column, balloon])
    stack._suite_tip = balloon
    return stack


_LINK_ROW_H = 84.0
_LINK_GAP = 8.0
_APP_GAP = 16.0


def _favorites_summary(app_count: int, link_count: int) -> str:
    """Frase sob o titulo. Nao escreve zero."""
    apps = int(app_count)
    links = int(link_count)
    if apps and links:
        return f"{apps} aplicativo(s) e {links} link(s) favorito(s)"
    if apps:
        return f"{apps} aplicativo(s) favorito(s)"
    if links:
        return f"{links} link(s) favorito(s)"
    return ""


def _same_hover(card: ft.Container) -> ft.Container:
    """Mesmo ink dos cartoes do Inicio e do botao da pagina Links.

    Sem on_click: o GestureDetector da secao continua vendo o segurar,
    e o mouse por cima chega no cartao.
    """
    card.ink = True
    card.on_hover = lambda _e: None
    return card


def _favorite_link_card(item: LinkItem, on_toggle_link: Callable[[str], None] | None) -> ft.Control:
    """Mesmo cartao da pagina Links, sem botao: o gesto da secao abre o https."""
    star = _star_button(item.url, True, on_toggle_link or (lambda _url: None))
    return _same_hover(ft.Container(
        height=_LINK_ROW_H,
        bgcolor=config.COLOR_SURFACE,
        border_radius=12,
        padding=ft.Padding.only(left=12, right=4, top=8, bottom=8),
        content=ft.Row(
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Container(expand=True, data=item.url, content=link_face(item)),
                star,
            ],
        ),
    ))


def build_favoritos_view(
    apps: list[AppInfo],
    on_select: Callable[[str], None],
    *,
    favorite_ids: set[str],
    on_toggle_favorite: Callable[[str], None],
    installed_ids: set[str] | None = None,
    link_items: list[LinkItem] | None = None,
    page: Any = None,
    on_toggle_link: Callable[[str], None] | None = None,
    on_reorder_app: Callable[[str, int], None] | None = None,
    on_reorder_link: Callable[[str, int], None] | None = None,
) -> ft.Control:
    """Aplicativos favoritos na secao Aplicativos; links marcados abaixo, na secao Links.

    Secao vazia nao aparece. Segurar um cartao por mais de 0,5s ordena so essa secao.
    """
    links = list(link_items or [])
    installed = installed_ids or set()
    header_controls: list[ft.Control] = [
        ft.Text("Favoritos", size=26, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
    ]
    summary = _favorites_summary(len(apps), len(links))
    if summary:
        header_controls.append(ft.Text(summary, size=13, color="#8AA797"))
    sections: list[ft.Control] = [ft.Column(spacing=4, controls=header_controls)]
    hold_apps = None
    hold_links = None
    if apps:
        app_bridge = {"cancel": lambda: None}

        def _app_face(app_id: str) -> ft.Control:
            app = next(item for item in apps if item.id == app_id)

            def _star(_id: str = app_id) -> None:
                app_bridge["cancel"]()
                on_toggle_favorite(_id)

            return _same_hover(_app_card(
                app,
                on_select,
                is_favorite=app.id in favorite_ids,
                on_toggle_favorite=_star,
                installed=app.id in installed,
                opens=False,
            ))

        hold_apps = HoldSection(
            [app.id for app in apps],
            axis="grid",
            card_w=_CARD_WIDTH,
            card_h=_CARD_HEIGHT,
            spacing_x=_APP_GAP,
            spacing_y=_APP_GAP,
            columns=3,
            build_card=_app_face,
            on_open=on_select,
            on_drop=on_reorder_app or (lambda _key, _index: None),
            page=page,
        )
        app_bridge["cancel"] = hold_apps.cancel_press
        sections.append(
            ft.Column(
                spacing=12,
                controls=[
                    ft.Text("Aplicativos", size=20, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                    hold_apps.control(),
                ],
            )
        )
    if links:
        link_bridge = {"cancel": lambda: None}

        def _link_face(url: str) -> ft.Control:
            item = next(link for link in links if link.url == url)

            def _star(_id: str = url) -> None:
                link_bridge["cancel"]()
                if callable(on_toggle_link):
                    on_toggle_link(_id)

            return _favorite_link_card(item, _star)

        def _open_link(url: str) -> None:
            from services.url_launch import open_https_url

            open_https_url(page, url)

        hold_links = HoldSection(
            [item.url for item in links],
            axis="line",
            card_w=640,
            card_h=_LINK_ROW_H,
            spacing_x=0,
            spacing_y=_LINK_GAP,
            columns=1,
            build_card=_link_face,
            on_open=_open_link,
            on_drop=on_reorder_link or (lambda _key, _index: None),
            page=page,
        )
        link_bridge["cancel"] = hold_links.cancel_press
        sections.append(
            ft.Column(
                spacing=8,
                controls=[
                    ft.Text("Links", size=20, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                    hold_links.control(),
                ],
            )
        )
    column = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=20, controls=sections)
    column._hold_apps = hold_apps
    column._hold_links = hold_links
    return column


def build_setor_view(setor: SetorInfo, apps: list[AppInfo], on_select: Callable[[str], None], *, favorite_ids: set[str], on_toggle_favorite: Callable[[str], None], installed_ids: set[str] | None = None) -> ft.Control:
    header_controls: list[ft.Control] = [ft.Text(setor.nome, size=26, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT)]
    if setor.descricao:
        header_controls.append(ft.Text(setor.descricao, size=14, color="#B9CEC3"))
    header_controls.append(ft.Text(f"{len(apps)} aplicativo(s) neste setor", size=13, color="#8AA797"))
    sections: list[ft.Control] = [ft.Column(spacing=6, controls=header_controls)]
    groups = group_apps_by_sub_setor(apps, setor)
    if not groups:
        sections.append(ft.Text("Nenhum aplicativo neste setor.", size=14, color="#8AA797"))
    else:
        for idx, (sub, chunk) in enumerate(groups):
            if idx > 0:
                sections.append(ft.Divider(height=28, color="#22332B"))
            sub_title, sub_desc = ("Outros", "") if sub is None else (sub.nome, sub.descricao)
            block: list[ft.Control] = [ft.Text(sub_title, size=18, weight=ft.FontWeight.W_600, color=config.COLOR_ACCENT)]
            if sub_desc:
                block.append(ft.Text(sub_desc, size=13, color="#8AA797"))
            cards = [_app_card(app, on_select, is_favorite=app.id in favorite_ids, on_toggle_favorite=on_toggle_favorite, installed=app.id in (installed_ids or set())) for app in chunk]
            block.append(ft.Row(controls=cards, wrap=True, spacing=16, run_spacing=16))
            sections.append(ft.Column(spacing=8, controls=block))
    return ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=16, controls=sections)
