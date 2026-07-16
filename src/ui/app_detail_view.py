"""Tela de detalhe de um aplicativo: imagem, descricao e acoes."""
from __future__ import annotations

from pathlib import Path

import flet as ft

import config
from models import AppInfo, InstallStatus
from services.download_manager import DownloadManager, DownloadOutcome
from services.runner import RunError, run_file
from services.sharepoint_manager import enviar_para_sharepoint
from services.storage import Storage
from ui.components import app_badge


def _image_src(imagem: str) -> str:
    """Aceita caminho de assets, caminho absoluto do cache ou URL residual."""
    imagem = (imagem or "").replace("\\", "/")
    if not imagem:
        return ""
    # Caminhos absolutos do cache local (Windows / POSIX)
    if Path(imagem).is_absolute() or (len(imagem) > 2 and imagem[1] == ":"):
        return imagem
    if imagem.startswith("assets/"):
        return imagem[len("assets/"):]
    return imagem


class AppDetailView:
    def __init__(
        self,
        page: ft.Page,
        app: AppInfo,
        storage: Storage,
        manager: DownloadManager,
        on_uninstalled=None,
    ) -> None:
        self.page = page
        self.app = app
        self.storage = storage
        self.manager = manager
        self.on_uninstalled = on_uninstalled

        self.progress = ft.ProgressBar(value=0, visible=False, color=config.COLOR_ACCENT, bgcolor="#0A0F0C")
        self.status_text = ft.Text("", size=13, color="#B9CEC3")
        self.local_info = ft.Text("", size=12, color="#8AA797")

        self.action_button = ft.FilledButton(on_click=self._on_action)
        self.update_button = ft.OutlinedButton(
            "Baixar novamente",
            icon=ft.Icons.REFRESH,
            visible=False,
            on_click=self._on_redownload,
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

        self._refresh_action_buttons()

    # ------------------------------------------------------------------
    def build(self) -> ft.Control:
        img_src = _image_src(self.app.imagem)
        image = ft.Container(
            width=520,
            height=300,
            border_radius=12,
            bgcolor=config.COLOR_SURFACE,
            alignment=ft.Alignment.CENTER,
            content=ft.Image(
                src=img_src,
                fit=ft.BoxFit.COVER,
                width=520,
                height=300,
                border_radius=12,
                error_content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        app_badge(56),
                        ft.Text("Sem imagem", size=13, color="#8AA797"),
                    ],
                ),
            ),
        )

        header = ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=12,
            controls=[
                ft.Icon(
                    ft.Icons.TABLE_CHART if self.app.tipo.is_spreadsheet else ft.Icons.APPS,
                    color=config.COLOR_ACCENT,
                    size=32,
                ),
                ft.Column(
                    spacing=2,
                    controls=[
                        ft.Text(self.app.nome, size=26, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                        ft.Text(
                            f"Tipo: {self.app.tipo.value.upper()}  -  Versao no catalogo: {self.app.versao}",
                            size=13,
                            color="#8AA797",
                        ),
                    ],
                ),
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
                    content=ft.Text("Descricao", size=16, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                ),
                ft.Text(self.app.descricao or "Sem descricao.", size=15, color="#D6E5DC"),
                ft.Divider(color="#22332B"),
                actions,
                self.local_info,
                self.progress,
                self.status_text,
            ],
        )

    # ------------------------------------------------------------------
    def _current_status(self) -> InstallStatus:
        return self.storage.get_state(self.app.id).status

    def _refresh_action_buttons(self) -> None:
        state = self.storage.get_state(self.app.id)
        installed = state.status == InstallStatus.INSTALLED

        if installed:
            self.action_button.content = "Executar"
            self.action_button.icon = ft.Icons.PLAY_ARROW
            self.action_button.disabled = False
            self.action_button.style = ft.ButtonStyle(bgcolor=config.COLOR_PRIMARY, color="white")

            self.update_button.visible = True
            self.upload_button.visible = bool(self.app.upload_url)
            self.uninstall_button.visible = True

            local_name = Path(state.local_path).name if state.local_path else "?"
            installed_ver = state.versao or "?"
            catalog_ver = self.app.versao
            if installed_ver != catalog_ver:
                self.local_info.value = (
                    f"Instalado: {local_name} (v{installed_ver})  |  "
                    f"Catalogo: v{catalog_ver}  —  ha uma versao diferente no catalogo. "
                    f"Use 'Atualizar versao'."
                )
                self.local_info.color = config.COLOR_ACCENT
                self.update_button.content = "Atualizar versao"
            else:
                self.local_info.value = f"Arquivo local: {local_name} (v{installed_ver})"
                self.local_info.color = "#8AA797"
                self.update_button.content = "Baixar novamente"
        else:
            self.action_button.content = "Baixar / Instalar"
            self.action_button.icon = ft.Icons.DOWNLOAD
            self.action_button.disabled = False
            self.action_button.style = ft.ButtonStyle(bgcolor=config.COLOR_PRIMARY, color="white")

            self.update_button.visible = False
            self.upload_button.visible = False
            self.uninstall_button.visible = False
            self.local_info.value = ""

    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _on_action(self, e: ft.ControlEvent) -> None:
        status = self._current_status()
        if status == InstallStatus.INSTALLED:
            self._execute()
        else:
            self._start_download()

    def _on_redownload(self, e: ft.ControlEvent) -> None:
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
        state = self.storage.get_state(self.app.id)
        if not state.local_path:
            self.status_text.value = "Arquivo nao encontrado. Baixe novamente."
            self._refresh_action_buttons()
            self._safe_update()
            return
        try:
            run_file(state.local_path)
            self.status_text.value = f"Abrindo {self.app.nome}..."
        except RunError as exc:
            self.status_text.value = str(exc)
        self._safe_update()

    def _set_busy(self, busy: bool) -> None:
        self.action_button.disabled = busy
        self.update_button.disabled = busy
        self.upload_button.disabled = busy
        self.uninstall_button.disabled = busy

    def _start_download(self) -> None:
        self._set_busy(True)
        self.progress.visible = True
        self.progress.value = None
        self.status_text.value = (
            "Iniciando download via SharePoint... "
            "Pode abrir uma janela de login (WebLogin)."
        )
        self._safe_update()
        self.page.run_thread(self._download_worker)

    def _on_upload(self, e: ft.ControlEvent) -> None:
        if not self.app.upload_url:
            self.status_text.value = "Este app nao tem upload_url no catalogo."
            self._safe_update()
            return
        state = self.storage.get_state(self.app.id)
        if not state.local_path or not Path(state.local_path).exists():
            self.status_text.value = "Nao ha arquivo local para enviar. Baixe novamente primeiro."
            self._safe_update()
            return
        self._set_busy(True)
        self.progress.visible = True
        self.progress.value = None
        self.status_text.value = (
            "Enviando para SharePoint... Pode abrir uma janela de login (WebLogin)."
        )
        self._safe_update()
        self.page.run_thread(self._upload_worker, state.local_path)

    def _upload_worker(self, local_path: str) -> None:
        def on_progress(pct: float, msg: str) -> None:
            self.progress.value = pct if pct > 0 else None
            self.status_text.value = msg
            self._safe_update()

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
            self.progress.value = pct if pct > 0 else None
            self.status_text.value = msg
            self._safe_update()

        result = self.manager.download(self.app, progress=on_progress)

        if result.outcome == DownloadOutcome.SUCCESS:
            self.progress.value = 1.0
            self.status_text.value = result.message
            self.progress.visible = False
        else:
            self.progress.visible = False
            self.status_text.value = result.message or f"Erro: {result.message}"

        self._set_busy(False)
        self._refresh_action_buttons()
        self._safe_update()
