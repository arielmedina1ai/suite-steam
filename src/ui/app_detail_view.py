"""Tela de detalhe de um aplicativo: imagem, descricao e acoes."""
from __future__ import annotations

from pathlib import Path

import flet as ft

import config
from models import AppInfo, InstallStatus
from services.download_manager import DownloadManager, DownloadOutcome
from services.sharepoint_manager import enviar_para_sharepoint
from services.storage import Storage
from ui.components import app_badge, app_icon, media_src
from ui.progress_util import bar_value, label as progress_label


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
        catalog_locked: bool = False,
        running_app_name: str = "",
        on_run=None,
        work_busy: bool = False,
        work_progress: float | None = None,
        work_message: str = "",
    ) -> None:
        self.page = page
        self.app = app
        self.storage = storage
        self.manager = manager
        self.on_uninstalled = on_uninstalled
        self.is_favorite = is_favorite
        self.on_toggle_favorite = on_toggle_favorite
        self.catalog_locked = catalog_locked
        self.running_app_name = running_app_name
        self.on_run = on_run
        self.work_busy = work_busy
        self.work_progress = work_progress
        self.work_message = work_message

        self.progress = ft.ProgressBar(
            value=bar_value(work_progress) if work_busy else 0,
            visible=work_busy,
            color=config.COLOR_ACCENT,
            bgcolor="#0A0F0C",
        )
        self.status_text = ft.Text(
            progress_label(work_progress, work_message) if work_busy or work_message else "",
            size=13,
            color="#B9CEC3",
        )
        self.local_info = ft.Text("", size=12, color="#8AA797")

        self.action_button = ft.FilledButton(on_click=self._on_action)
        self.update_button = ft.OutlinedButton(
            "Atualizar versao",
            icon=ft.Icons.SYSTEM_UPDATE,
            visible=False,
            on_click=self._on_update,
        )
        self.upload_button = ft.OutlinedButton(
            "Enviar para SharePoint",
            icon=ft.Icons.CLOUD_UPLOAD,
            visible=False,
            on_click=self._on_upload,
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
        actions = ft.Row(
            spacing=12,
            wrap=True,
            controls=[
                self.action_button,
                self.update_button,
                self.upload_button,
                self.uninstall_button,
            ],
        )
        return ft.Column(
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
                actions,
                self.local_info,
                self.progress,
                self.status_text,
            ],
        )

    def _on_toggle_favorite(self, _e) -> None:
        if self.on_toggle_favorite:
            self.on_toggle_favorite(self.app.id)

    def _current_status(self) -> InstallStatus:
        return self.storage.get_state(self.app.id).status

    def _has_version_update(self, state) -> bool:
        return str(state.versao or "") != str(self.app.versao or "")

    def _refresh_action_buttons(self) -> None:
        state = self.storage.get_state(self.app.id)
        installed = state.status == InstallStatus.INSTALLED
        locked = self.catalog_locked or self.work_busy
        if installed:
            self.action_button.content = "Executar"
            self.action_button.icon = ft.Icons.PLAY_ARROW
            self.action_button.disabled = locked
            self.action_button.style = ft.ButtonStyle(bgcolor=config.COLOR_PRIMARY, color="white")
            needs_update = self._has_version_update(state)
            self.update_button.visible = needs_update
            self.update_button.disabled = locked
            self.upload_button.visible = bool(self.app.upload_url)
            self.upload_button.disabled = self.work_busy
            self.uninstall_button.visible = True
            self.uninstall_button.disabled = self.work_busy
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
            self.action_button.disabled = locked
            self.action_button.style = ft.ButtonStyle(bgcolor=config.COLOR_PRIMARY, color="white")
            self.update_button.visible = False
            self.upload_button.visible = False
            self.uninstall_button.visible = False
            self.local_info.value = ""
        if self.catalog_locked and not self.work_busy:
            who = self.running_app_name or "outro aplicativo"
            self.status_text.value = f"Aguarde: {who} em execucao. So um app por vez."
        elif self.work_message and not self.work_busy:
            self.status_text.value = self.work_message

    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass

    def _on_action(self, e: ft.ControlEvent) -> None:
        if self.catalog_locked or self.work_busy:
            return
        if self._current_status() == InstallStatus.INSTALLED:
            self._execute()
        else:
            self._start_download()

    def _on_update(self, e: ft.ControlEvent) -> None:
        if self.catalog_locked or self.work_busy:
            return
        self._start_download()

    def _on_uninstall(self, e: ft.ControlEvent) -> None:
        try:
            self.storage.uninstall(self.app.id)
            self.status_text.value = f"{self.app.nome} desinstalado."
        except Exception as exc:
            self.status_text.value = f"Erro ao desinstalar: {exc}"
        self._refresh_action_buttons()
        self._safe_update()
        if self.on_uninstalled:
            self.on_uninstalled(self.app.id)

    def _execute(self) -> None:
        if self.on_run:
            self.on_run(self.app)
            return
        self.status_text.value = "Nao foi possivel iniciar o aplicativo."
        self._safe_update()

    def _set_busy(self, busy: bool) -> None:
        self.work_busy = busy
        self.action_button.disabled = busy or self.catalog_locked
        self.update_button.disabled = busy or self.catalog_locked
        self.upload_button.disabled = busy
        self.uninstall_button.disabled = busy

    def _apply_progress(self, pct: float | None, msg: str) -> None:
        self.progress.visible = True
        self.progress.value = bar_value(pct)
        self.status_text.value = progress_label(pct, msg)
        self._safe_update()

    def _start_download(self) -> None:
        self._set_busy(True)
        self._apply_progress(
            -1.0,
            "Iniciando download via SharePoint... Pode abrir uma janela de login (WebLogin).",
        )
        self.page.run_thread(self._download_worker)

    def _on_upload(self, e: ft.ControlEvent) -> None:
        if not self.app.upload_url:
            self.status_text.value = "Este app nao tem upload_url no catalogo."
            self._safe_update()
            return
        state = self.storage.get_state(self.app.id)
        if not state.local_path or not Path(state.local_path).exists():
            self.status_text.value = "Nao ha arquivo local para enviar. Baixe / Instale primeiro."
            self._safe_update()
            return
        self._set_busy(True)
        self._apply_progress(
            -1.0,
            "Enviando para SharePoint... Pode abrir uma janela de login (WebLogin).",
        )
        self.page.run_thread(lambda: self._upload_worker(state.local_path))

    def _upload_worker(self, local_path: str) -> None:
        def on_progress(pct: float, msg: str) -> None:
            self._apply_progress(pct, msg)

        result = enviar_para_sharepoint(
            arquivo_local=local_path,
            link_pasta=self.app.upload_url,
            progress=on_progress,
        )
        self.progress.visible = False
        self.status_text.value = result.message if result.ok else f"Erro no upload: {result.message}"
        self._set_busy(False)
        self._refresh_action_buttons()
        self._safe_update()

    def _download_worker(self) -> None:
        def on_progress(pct: float, msg: str) -> None:
            self._apply_progress(pct, msg)

        result = self.manager.download(self.app, progress=on_progress)
        if result.outcome == DownloadOutcome.SUCCESS:
            self._apply_progress(1.0, result.message)
            self.progress.visible = False
            self.status_text.value = result.message
        else:
            self.progress.visible = False
            self.status_text.value = result.message or "Erro no download."
        self._set_busy(False)
        self._refresh_action_buttons()
        self._safe_update()


def _image_src(imagem: str) -> str:
    return media_src(imagem)
