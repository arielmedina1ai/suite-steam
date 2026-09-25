"""Componentes reutilizaveis da UI (sidebar, itens de app)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

import config
from models import AppInfo, CatalogData, GerenciaInfo, SuiteUpdateInfo, setores_visiveis
from ui.progress_util import bar_value, label as progress_label

# Largura fixa da sidebar e area util (descontando padding 12+12)
_SIDEBAR_WIDTH = 260
_SIDEBAR_INNER = _SIDEBAR_WIDTH - 24  # 236


def media_src(path: str) -> str:
    """Caminho absoluto do cache ou relativo a assets/ (ex.: branding/logo.png)."""
    path = (path or "").replace("\\", "/")
    if not path:
        return ""
    if Path(path).is_absolute() or (len(path) > 2 and path[1] == ":"):
        return path
    return path


def app_badge(size: int = 40) -> ft.Control:
    """Logo do SuiteApps (assets/branding/logo.png) ou fallback texto SP."""
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
    """Item de menu: nome completo com quebra de linha (sem reticencias)."""
    return ft.Container(
        on_click=lambda e: on_click(),
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        bgcolor=config.COLOR_PRIMARY if selected else None,
        ink=True,
        width=_SIDEBAR_INNER,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Row(
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Container(
                    padding=ft.Padding.only(top=2),
                    content=ft.Icon(
                        icon,
                        size=20,
                        color=config.COLOR_ACCENT if selected else config.COLOR_TEXT,
                    ),
                ),
                ft.Text(
                    label,
                    color=config.COLOR_TEXT,
                    size=14,
                    weight=ft.FontWeight.W_600 if selected else ft.FontWeight.NORMAL,
                    expand=True,
                    width=_SIDEBAR_INNER - 54,
                ),
            ],
        ),
    )


_NONE_GERENCIA = "__todas__"  # valor interno do seletor = sem filtro


def _update_banner(
    *,
    suite_update: SuiteUpdateInfo,
    update_busy: bool,
    update_message: str,
    update_progress: float | None,
    update_done: bool,
    update_failed: bool,
    on_download_update: Callable[[], None],
) -> ft.Control:
    # Sidebar 260 - padding 12*2 = 236 (mesma faixa dos itens de menu)
    _W = _SIDEBAR_INNER
    if update_done:
        title = "Atualizacao aplicada"
    elif update_busy:
        title = "Atualizando..."
    elif update_failed:
        title = "Falha na atualizacao"
    else:
        title = "Atualizacao disponivel"
    controls: list[ft.Control] = [
        ft.Text(
            title,
            size=12,
            weight=ft.FontWeight.BOLD,
            color=config.COLOR_ACCENT,
            width=_W - 24,
        ),
        ft.Text(
            f"{config.APP_NAME} v{suite_update.versao}",
            size=12,
            color="#B9CEC3",
            width=_W - 24,
        ),
    ]
    if update_busy:
        controls.append(
            ft.ProgressBar(
                value=bar_value(update_progress),
                color=config.COLOR_ACCENT,
                bgcolor="#0A0F0C",
                width=_W - 24,
            )
        )
    if not update_done and (update_failed or not update_busy):
        controls.append(
            ft.FilledButton(
                "Baixar Atualizacao",
                icon=ft.Icons.DOWNLOAD,
                disabled=update_busy,
                on_click=lambda e: on_download_update(),
                width=_W - 24,
            )
        )
    msg = progress_label(update_progress, update_message) if update_busy else update_message
    if msg:
        controls.append(
            ft.Text(
                msg,
                size=11,
                color="#8AA797",
                width=_W - 24,
            )
        )
    return ft.Container(
        width=_W,
        margin=ft.Margin.only(bottom=8),
        padding=12,
        border_radius=10,
        bgcolor=config.COLOR_PRIMARY_DARK,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Column(spacing=8, tight=True, controls=controls),
    )


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
    update_progress: float | None,
    update_done: bool,
    update_failed: bool,
    on_home: Callable[[], None],
    on_favorites: Callable[[], None],
    on_select_setor: Callable[[str], None],
    on_select_gerencia: Callable[[str], None],
    on_download_update: Callable[[], None],
    on_check_updates: Callable[[], None],
    check_updates_busy: bool,
    start_with_windows: bool,
    on_toggle_startup: Callable[[bool], None],
    show_startup_toggle: bool,
    running_app_name: str = "",
    show_publish: bool = False,
    publish_selected: bool = False,
    on_publish: Callable[[], None] | None = None,
) -> ft.Control:
    home_selected = home_selected and not publish_selected
    favorites_selected = favorites_selected and not publish_selected
    setores = setores_visiveis(catalog)
    gerencia_list = gerencias if gerencias is not None else catalog.gerencias
    items: list[ft.Control] = [
        ft.Container(
            padding=ft.Padding.only(left=4, top=8, bottom=16, right=4),
            width=_SIDEBAR_INNER,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    app_badge(40),
                    ft.Column(
                        spacing=2,
                        expand=True,
                        tight=True,
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Text(
                                config.APP_NAME,
                                weight=ft.FontWeight.BOLD,
                                size=16,
                                color=config.COLOR_TEXT,
                                width=_SIDEBAR_INNER - 64,
                            ),
                            ft.Text(
                                f"v{config.APP_VERSION}",
                                size=11,
                                color="#8AA797",
                                width=_SIDEBAR_INNER - 64,
                            ),
                        ],
                    ),
                ],
            ),
        ),
    ]

    # Atualizacao do SuiteApps — logo acima de Inicio
    if update_available and suite_update is not None:
        items.append(
            _update_banner(
                suite_update=suite_update,
                update_busy=update_busy,
                update_message=update_message,
                update_progress=update_progress,
                update_done=update_done,
                update_failed=update_failed,
                on_download_update=on_download_update,
            )
        )

    items.append(
        _nav_item(
            label="Inicio",
            icon=ft.Icons.HOME,
            selected=home_selected,
            on_click=on_home,
        )
    )

    if show_favorites:
        items.append(
            _nav_item(
                label="Favoritos",
                icon=ft.Icons.STAR,
                selected=favorites_selected,
                on_click=on_favorites,
            )
        )

    if show_publish and on_publish is not None:
        items.append(
            _nav_item(
                label="Publicar",
                icon=ft.Icons.CLOUD_UPLOAD,
                selected=publish_selected,
                on_click=on_publish,
            )
        )

    # Filtro por gerencia (acima dos setores) — dropdown; nomes longos com reticencias
    if gerencia_list:
        geral_label = (catalog.gerencia_geral or "").strip() or "Geral"
        _opt_w = _SIDEBAR_INNER - 16

        def _gerencia_option(key: str, label: str) -> ft.DropdownOption:
            return ft.DropdownOption(
                key=key,
                text=label,
                tooltip=label,
                content=ft.Text(
                    label,
                    size=13,
                    color=config.COLOR_TEXT,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    width=_opt_w,
                ),
            )

        gerencia_options = [_gerencia_option(_NONE_GERENCIA, geral_label)]
        for g in gerencia_list:
            gerencia_options.append(_gerencia_option(g.id, g.nome))

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
                width=_SIDEBAR_INNER,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=ft.Column(
                    spacing=6,
                    tight=True,
                    controls=[
                        ft.Text(
                            "GERENCIA",
                            size=11,
                            color="#8AA797",
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Dropdown(
                            value=current_gid,
                            options=gerencia_options,
                            dense=True,
                            filled=True,
                            fill_color=config.COLOR_BG,
                            border_color="#22332B",
                            color=config.COLOR_TEXT,
                            text_size=13,
                            width=_SIDEBAR_INNER - 8,
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
                        and not publish_selected
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

    items.append(ft.Container(expand=True))

    if running_app_name:
        items.append(
            ft.Container(
                width=_SIDEBAR_INNER,
                padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                content=ft.Text(
                    f"Em execucao: {running_app_name}",
                    size=11,
                    color=config.COLOR_ACCENT,
                    width=_SIDEBAR_INNER - 16,
                ),
            )
        )

    items.append(
        ft.Container(
            width=_SIDEBAR_INNER,
            padding=ft.Padding.only(left=4, top=8, bottom=4, right=4),
            content=ft.Column(
                spacing=8,
                tight=True,
                controls=[
                    ft.FilledButton(
                        "Buscando..." if check_updates_busy else "Buscar atualizacoes",
                        icon=ft.Icons.REFRESH,
                        disabled=check_updates_busy,
                        on_click=lambda e: on_check_updates(),
                        width=_SIDEBAR_INNER - 8,
                    ),
                    ft.ProgressBar(
                        value=None,
                        visible=check_updates_busy,
                        color=config.COLOR_ACCENT,
                        bgcolor="#0A0F0C",
                        width=_SIDEBAR_INNER - 8,
                    ),
                ],
            ),
        )
    )
    if show_startup_toggle:
        items.append(
            ft.Container(
                width=_SIDEBAR_INNER,
                padding=ft.Padding.only(left=4, bottom=8, right=4),
                content=ft.Switch(
                    label="Iniciar com o Windows",
                    value=start_with_windows,
                    active_color=config.COLOR_ACCENT,
                    on_change=lambda e: on_toggle_startup(bool(e.control.value)),
                ),
            )
        )

    return ft.Container(
        width=_SIDEBAR_WIDTH,
        bgcolor=config.COLOR_SURFACE,
        padding=12,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Column(
            controls=items,
            spacing=4,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
    )
