"""Tela de detalhe de um aplicativo: imagem, descricao e acoes."""
from __future__ import annotations

from pathlib import Path

import flet as ft

import config
from models import AppInfo, InstallStatus
from services.download_manager import DownloadManager, DownloadOutcome
from services.storage import Storage
from ui.components import app_badge, app_icon, media_src
from ui.progress_util import bar_value

# Texto curto da faixa fixa. O detalhe longo do download nao entra na tela.
_BUSY_CAPTION = {
    "download": "Baixando. Pode aguardar.",
    "update": "Atualizando. Pode aguardar.",
    "uninstall": "Desinstalando. Pode aguardar.",
}
# Texto escuro sobre COLOR_ACCENT, para o botao Abrindo continuar legivel.
_OPENING_TEXT = "#142018"
_UPDATE_LABEL = "Atualizar versao"


def _primary_action_style() -> ft.ButtonStyle:
    """Mesmo preenchimento do Executar em repouso: fundo primario e texto branco."""
    return ft.ButtonStyle(bgcolor=config.COLOR_PRIMARY, color="white")


class AppDetailView:
    def __init__(
        self,
        page: ft.Page,
        app: AppInfo,
        storage: Storage,
        manager: DownloadManager,
        on_uninstalled=None,
        *,
        is_favorite: bool = False,
        on_toggle_favorite=None,
        on_run=None,
        on_update_app=None,
        on_uninstall=None,
        on_tutorial=None,
        on_feedback=None,
        feedback_enabled: bool = False,
        on_status=None,
        this_app_running: bool = False,
        work_busy: bool = False,
        work_progress: float | None = None,
        work_message: str = "",
        opening: bool = False,
    ) -> None:
        self.page = page
        self.app = app
        self.storage = storage
        self.manager = manager
        self.on_uninstalled = on_uninstalled
        self.is_favorite = is_favorite
        self.on_toggle_favorite = on_toggle_favorite
        self.on_run = on_run
        self.on_update_app = on_update_app
        self.on_uninstall = on_uninstall
        self.on_tutorial = on_tutorial
        self.on_feedback = on_feedback
        self.feedback_enabled = feedback_enabled
        self.on_status = on_status
        self.this_app_running = this_app_running
        self.work_busy = work_busy
        self.work_progress = work_progress
        self.work_message = work_message
        self.opening = opening
        self.work_action = self._infer_work_action()

        self.progress = ft.ProgressBar(
            value=bar_value(work_progress) if work_busy else 0,
            visible=work_busy,
            color=config.COLOR_ACCENT,
            bgcolor="#0A0F0C",
        )
        self.progress_caption = ft.Text(
            self._busy_caption() if work_busy else "",
            size=13,
            color="#B9CEC3",
        )
        # Faixa fixa: logo acima dos botoes de acao, fora da coluna que rola.
        self.progress_strip = ft.Container(
            visible=work_busy,
            bgcolor=config.COLOR_SURFACE,
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            content=ft.Column(
                spacing=8,
                tight=True,
                controls=[self.progress_caption, self.progress],
            ),
        )
        self.status_text = ft.Text(
            "" if work_busy or opening else (work_message or ""),
            size=13,
            color="#B9CEC3",
        )
        self.local_info = ft.Text("", size=12, color="#8AA797")

        self.action_button = ft.FilledButton(on_click=self._on_action)
        self.feedback_button = ft.OutlinedButton(
            "Feedback",
            icon=ft.Icons.CHAT_BUBBLE_OUTLINE,
            on_click=self._on_feedback,
        )
        self.tutorial_button = ft.OutlinedButton(
            "Tutorial",
            icon=ft.Icons.MENU_BOOK,
            on_click=self._on_tutorial,
        )
        self.update_button = ft.FilledButton(
            _UPDATE_LABEL,
            icon=ft.Icons.SYSTEM_UPDATE,
            visible=False,
            style=_primary_action_style(),
            on_click=self._on_update,
        )
        self.uninstall_button = ft.OutlinedButton(
            "Desinstalar",
            icon=ft.Icons.DELETE_OUTLINE,
            visible=False,
            on_click=self._on_uninstall,
        )
        self.favorite_button = ft.IconButton(
            icon=ft.Icons.STAR if is_favorite else ft.Icons.STAR_BORDER,
            icon_color=config.COLOR_ACCENT if is_favorite else "#8AA797",
            icon_size=28,
            tooltip="Remover dos favoritos" if is_favorite else "Adicionar aos favoritos",
            on_click=self._on_toggle_favorite,
        )
        self._refresh_action_buttons()

    def build(self) -> ft.Control:
        img_src = _image_src(self.app.imagem).strip()
        fallback = ft.Column(
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[app_badge(56), ft.Text("Sem imagem", size=13, color="#8AA797")],
        )
        image_content = (
            ft.Image(
                src=img_src,
                fit=ft.BoxFit.COVER,
                width=520,
                height=300,
                border_radius=12,
                error_content=fallback,
            )
            if img_src
            else fallback
        )
        image = ft.Container(
            width=520,
            height=300,
            border_radius=12,
            bgcolor=config.COLOR_SURFACE,
            alignment=ft.Alignment.CENTER,
            content=image_content,
        )

        header = ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
            controls=[
                app_icon(self.app, size=36, color=config.COLOR_ACCENT),
                ft.Column(
                    spacing=2,
                    expand=True,
                    controls=[
                        ft.Text(
                            self.app.nome,
                            size=26,
                            weight=ft.FontWeight.BOLD,
                            color=config.COLOR_TEXT,
                        ),
                        ft.Text(
                            f"Tipo: {self.app.tipo.value.upper()}  -  Versao no catalogo: {self.app.versao}",
                            size=13,
                            color="#8AA797",
                        ),
                    ],
                ),
                self.favorite_button,
            ],
        )
        action_controls: list[ft.Control] = [
            self.update_button,
            self.action_button,
            self.feedback_button,
            self.tutorial_button,
            self.uninstall_button,
        ]
        actions = ft.Row(
            spacing=12,
            wrap=True,
            controls=action_controls,
        )
        self.actions = actions
        body = ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=20,
            controls=[
                header,
                image,
                ft.Container(
                    padding=ft.Padding.only(top=4),
                    content=ft.Text(
                        "Descricao",
                        size=16,
                        weight=ft.FontWeight.BOLD,
                        color=config.COLOR_TEXT,
                    ),
                ),
                ft.Text(self.app.descricao or "Sem descricao.", size=15, color="#D6E5DC"),
                ft.Divider(color="#22332B"),
            ],
        )
        # Nome, imagem e descricao rolam. A faixa fica colada nos botoes.
        self.action_dock = ft.Column(
            spacing=12,
            controls=[
                self.progress_strip,
                actions,
                self.local_info,
                self.status_text,
            ],
        )
        return ft.Column(
            expand=True,
            spacing=16,
            controls=[body, self.action_dock],
        )

    def _on_feedback(self, _e) -> None:
        if self.on_feedback and self.feedback_enabled and not self.work_busy:
            self.on_feedback(self.app)

    def _on_tutorial(self, _e) -> None:
        if (
            self.on_tutorial
            and self.app.has_tutorial
            and self._current_status() == InstallStatus.INSTALLED
        ):
            self.on_tutorial(self.app)

    def _on_toggle_favorite(self, _e) -> None:
        if self.on_toggle_favorite:
            self.on_toggle_favorite(self.app.id)

    def _current_status(self) -> InstallStatus:
        return self.storage.get_state(self.app.id).status

    def _has_version_update(self, state) -> bool:
        return str(state.versao or "") != str(self.app.versao or "")

    def _infer_work_action(self) -> str:
        if not self.work_busy:
            return ""
        msg = (self.work_message or "").casefold()
        if "desinstal" in msg:
            return "uninstall"
        if self.storage.get_state(self.app.id).status == InstallStatus.INSTALLED:
            return "update"
        return "download"

    def _busy_caption(self) -> str:
        return _BUSY_CAPTION.get(self.work_action, _BUSY_CAPTION["download"])

    def _sync_progress_strip(self) -> None:
        busy = bool(self.work_busy)
        self.progress_strip.visible = busy
        self.progress.visible = busy
        if not busy:
            return
        self.progress.value = bar_value(self.work_progress)
        self.progress_caption.value = self._busy_caption()

    def _refresh_action_buttons(self) -> None:
        state = self.storage.get_state(self.app.id)
        installed = state.status == InstallStatus.INSTALLED
        this = self.this_app_running
        opening = bool(self.opening) and installed and not self.work_busy
        if installed:
            self.action_button.icon = ft.Icons.PLAY_ARROW
            if opening:
                self.action_button.content = "Abrindo..."
                self.action_button.disabled = False
                self.action_button.style = ft.ButtonStyle(
                    bgcolor=config.COLOR_ACCENT,
                    color=_OPENING_TEXT,
                )
            else:
                self.action_button.content = "Executar"
                self.action_button.disabled = self.work_busy or this
                self.action_button.style = _primary_action_style()
            needs_update = self._has_version_update(state)
            self.update_button.visible = needs_update
            # Abrindo... pinta so o Executar. Atualizar fica no visual normal
            # e so desativa quando um download, atualizacao ou desinstalacao corre.
            self.update_button.content = _UPDATE_LABEL
            self.update_button.style = _primary_action_style()
            self.update_button.disabled = self.work_busy
            self.uninstall_button.visible = True
            self.uninstall_button.disabled = True if opening else (self.work_busy or this)
            local_name = Path(state.local_path).name if state.local_path else "?"
            installed_ver = state.versao or "?"
            catalog_ver = self.app.versao
            if needs_update:
                self.local_info.value = (
                    f"Instalado: {local_name} (v{installed_ver})  |  Catalogo: v{catalog_ver}  —  nova versao disponivel."
                )
                self.local_info.color = config.COLOR_ACCENT
            else:
                self.local_info.value = f"Arquivo local: {local_name} (v{installed_ver})"
                self.local_info.color = "#8AA797"
        else:
            self.action_button.content = "Baixar / Instalar"
            self.action_button.icon = ft.Icons.DOWNLOAD
            self.action_button.disabled = self.work_busy
            self.action_button.style = _primary_action_style()
            self.update_button.visible = False
            self.update_button.content = _UPDATE_LABEL
            self.update_button.style = _primary_action_style()
            self.update_button.disabled = self.work_busy
            self.uninstall_button.visible = False
            self.local_info.value = ""
        self.feedback_button.visible = self.feedback_enabled
        self.feedback_button.disabled = self.work_busy or self.opening
        self.tutorial_button.visible = installed and self.app.has_tutorial
        self.tutorial_button.disabled = self.work_busy or self.opening
        if self.work_busy or self.opening:
            self.status_text.value = ""
        elif this:
            if installed and self._has_version_update(state):
                self.status_text.value = (
                    "Em execucao. Atualizar versao encerra o processo, instala e reabre."
                )
            else:
                self.status_text.value = f"{self.app.nome} ja esta em execucao."
        elif self.work_message:
            self.status_text.value = self.work_message
        self._sync_progress_strip()

    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass

    def _on_action(self, e: ft.ControlEvent) -> None:
        if self.work_busy or self.opening:
            return
        if self._current_status() == InstallStatus.INSTALLED:
            if self.this_app_running:
                return
            self._execute()
        else:
            self._start_download()

    def _on_update(self, e: ft.ControlEvent) -> None:
        if self.work_busy:
            return
        if self.on_update_app:
            self.on_update_app(self.app)
            return
        self.opening = False
        self._refresh_action_buttons()
        self._start_download()

    def _on_uninstall(self, e: ft.ControlEvent) -> None:
        if self.work_busy or self.opening or self.this_app_running:
            return
        if self.on_uninstall:
            self.on_uninstall(self.app)
            return
        self._uninstall_local()

    def _uninstall_local(self) -> None:
        self.work_action = "uninstall"
        self._set_busy(True)
        self._apply_progress(-1.0, "Desinstalando...")
        try:
            self.storage.uninstall(self.app.id)
            msg = "Desinstalação concluída."
        except Exception as exc:
            msg = f"Erro ao desinstalar: {exc}"
        self.progress.visible = False
        self.progress_strip.visible = False
        self.status_text.value = msg
        self.work_message = msg
        self.work_action = ""
        self._set_busy(False)
        self._refresh_action_buttons()
        if self.on_status:
            self.on_status(self.app.id, msg)
        if self.on_uninstalled:
            self.on_uninstalled(self.app.id)
        self._safe_update()

    def _execute(self) -> None:
        if self.opening:
            return
        self.opening = True
        self.status_text.value = ""
        self._refresh_action_buttons()
        self._safe_update()
        if self.on_run:
            self.on_run(self.app)
            return
        self.opening = False
        self._refresh_action_buttons()
        self.status_text.value = "Nao foi possivel iniciar o aplicativo."
        self._safe_update()

    def _set_busy(self, busy: bool) -> None:
        self.work_busy = busy
        if busy and not self.work_action:
            self.work_action = self._infer_work_action()
        installed = self._current_status() == InstallStatus.INSTALLED
        self.action_button.disabled = busy or (installed and self.this_app_running)
        self.feedback_button.disabled = busy or self.opening
        self.tutorial_button.disabled = busy or self.opening
        self.update_button.disabled = busy
        self.uninstall_button.disabled = busy or self.opening or self.this_app_running
        if busy:
            self.status_text.value = ""
        self._sync_progress_strip()

    def _apply_progress(self, pct: float | None, msg: str) -> None:
        self.work_progress = pct
        self.work_message = msg
        self.work_busy = True
        if not self.work_action:
            self.work_action = self._infer_work_action()
        self.status_text.value = ""
        self._sync_progress_strip()
        self._safe_update()

    def _start_download(self) -> None:
        installed = self._current_status() == InstallStatus.INSTALLED
        self.work_action = "update" if installed else "download"
        self._set_busy(True)
        self._apply_progress(
            -1.0,
            "Iniciando download via SharePoint... Pode abrir uma janela de login (WebLogin).",
        )
        self.page.run_thread(self._download_worker)

    def _download_worker(self) -> None:
        def on_progress(pct: float, msg: str) -> None:
            self._apply_progress(pct, msg)

        result = self.manager.download(self.app, progress=on_progress)
        if result.outcome == DownloadOutcome.SUCCESS:
            msg = result.message or "Download concluido."
        else:
            msg = result.message or "Erro no download."
        self.progress.visible = False
        self.progress_strip.visible = False
        self.status_text.value = msg
        self.work_message = msg
        self.work_action = ""
        self._set_busy(False)
        self._refresh_action_buttons()
        if self.on_status:
            self.on_status(self.app.id, msg)
        self._safe_update()


def _image_src(imagem: str) -> str:
    return media_src(imagem)
