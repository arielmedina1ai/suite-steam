"""Tela de detalhe de um aplicativo: imagem, descricao e acoes."""
from __future__ import annotations

from pathlib import Path

import flet as ft

import config
from models import AppInfo, InstallStatus
from services.download_manager import DownloadManager, DownloadOutcome
from services.runner import RunError, run_file
from services.storage import Storage
from ui.components import app_badge


def _image_src(imagem: str) -> str:
    """Converte o caminho do catalogo para um src relativo ao assets_dir do Flet."""
    imagem = (imagem or "").replace("\\", "/")
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
        file_picker: ft.FilePicker,
    ) -> None:
        self.page = page
        self.app = app
        self.storage = storage
        self.manager = manager
        self.file_picker = file_picker

        self.progress = ft.ProgressBar(value=0, visible=False, color=config.COLOR_ACCENT, bgcolor="#0A0F0C")
        self.status_text = ft.Text("", size=13, color="#B9CEC3")
        self.action_button = ft.FilledButton(on_click=self._on_action)
        self.secondary_button = ft.OutlinedButton(
            "Localizar arquivo baixado",
            icon=ft.Icons.FOLDER_OPEN,
            visible=False,
            on_click=self._on_locate,
        )

        self._refresh_action_button()

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
                    ft.Icons.TABLE_CHART if self.app.tipo.value == "xlsx" else ft.Icons.APPS,
                    color=config.COLOR_ACCENT,
                    size=32,
                ),
                ft.Column(
                    spacing=2,
                    controls=[
                        ft.Text(self.app.nome, size=26, weight=ft.FontWeight.BOLD, color=config.COLOR_TEXT),
                        ft.Text(f"Tipo: {self.app.tipo.value.upper()}  -  Versao {self.app.versao}", size=13, color="#8AA797"),
                    ],
                ),
            ],
        )

        actions = ft.Row(spacing=12, controls=[self.action_button, self.secondary_button])

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
                self.progress,
                self.status_text,
            ],
        )

    # ------------------------------------------------------------------
    def _current_status(self) -> InstallStatus:
        return self.storage.get_state(self.app.id).status

    def _refresh_action_button(self) -> None:
        status = self._current_status()
        if status == InstallStatus.INSTALLED:
            self.action_button.text = "Executar"
            self.action_button.icon = ft.Icons.PLAY_ARROW
            self.action_button.disabled = False
            self.action_button.style = ft.ButtonStyle(bgcolor=config.COLOR_PRIMARY, color="white")
        else:
            self.action_button.text = "Baixar / Instalar"
            self.action_button.icon = ft.Icons.DOWNLOAD
            self.action_button.disabled = False
            self.action_button.style = ft.ButtonStyle(bgcolor=config.COLOR_PRIMARY, color="white")

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

    def _execute(self) -> None:
        state = self.storage.get_state(self.app.id)
        if not state.local_path:
            self.status_text.value = "Arquivo nao encontrado. Baixe novamente."
            self._refresh_action_button()
            self._safe_update()
            return
        try:
            run_file(state.local_path)
            self.status_text.value = f"Abrindo {self.app.nome}..."
        except RunError as exc:
            self.status_text.value = str(exc)
        self._safe_update()

    def _start_download(self) -> None:
        self.action_button.disabled = True
        self.progress.visible = True
        self.progress.value = None  # indeterminado ate ter %
        self.status_text.value = "Iniciando download..."
        self.secondary_button.visible = False
        self._safe_update()

        # roda o download bloqueante em uma thread gerenciada pelo Flet
        self.page.run_thread(self._download_worker)

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
        elif result.outcome == DownloadOutcome.NEEDS_BROWSER:
            self.progress.visible = False
            self.status_text.value = result.message
            self.secondary_button.visible = True
        else:
            self.progress.visible = False
            self.status_text.value = f"Erro: {result.message}"

        self.action_button.disabled = False
        self._refresh_action_button()
        self._safe_update()

    # ------------------------------------------------------------------
    async def _on_locate(self, e: ft.ControlEvent) -> None:
        ext = "xlsx" if self.app.tipo.value == "xlsx" else "exe"
        files = await self.file_picker.pick_files(
            dialog_title=f"Selecione o arquivo baixado ({self.app.nome})",
            allow_multiple=False,
            allowed_extensions=[ext],
        )
        if not files:
            return
        source_path = files[0].path
        if not source_path:
            self.status_text.value = "Nao foi possivel obter o caminho do arquivo."
            self._safe_update()
            return
        result = self.manager.register_manual_file(self.app, Path(source_path))
        if result.outcome == DownloadOutcome.SUCCESS:
            self.status_text.value = "Arquivo registrado com sucesso."
            self.secondary_button.visible = False
        else:
            self.status_text.value = f"Erro: {result.message}"
        self._refresh_action_button()
        self._safe_update()
