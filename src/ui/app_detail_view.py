"""Tela de detalhe de um aplicativo: imagem, descricao e acoes."""
from __future__ import annotations

from pathlib import Path

import flet as ft

import config
from models import AppInfo, AppType, InstallStatus
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
        self.local_info = ft.Text("", size=12, color="#8AA797")

        self.action_button = ft.FilledButton(on_click=self._on_action)
        self.replace_button = ft.OutlinedButton(
            "Trocar arquivo",
            icon=ft.Icons.FOLDER_OPEN,
            visible=False,
            on_click=self._on_locate,
        )
        self.update_button = ft.OutlinedButton(
            "Baixar novamente",
            icon=ft.Icons.REFRESH,
            visible=False,
            on_click=self._on_redownload,
        )
        # Alias usado no fluxo de fallback do navegador (mesmo handler do Trocar arquivo)
        self.secondary_button = self.replace_button

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
            controls=[self.action_button, self.replace_button, self.update_button],
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

            self.replace_button.visible = True
            self.replace_button.content = "Trocar arquivo"
            self.update_button.visible = True

            local_name = Path(state.local_path).name if state.local_path else "?"
            installed_ver = state.versao or "?"
            catalog_ver = self.app.versao
            if installed_ver != catalog_ver:
                self.local_info.value = (
                    f"Instalado: {local_name} (v{installed_ver})  |  "
                    f"Catalogo: v{catalog_ver}  —  ha uma versao diferente no catalogo. "
                    f"Use 'Baixar novamente' ou 'Trocar arquivo'."
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

            # Botoes secundarios ficam ocultos ate o fallback do navegador ou apos instalar
            self.replace_button.visible = False
            self.update_button.visible = False
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

    def _execute(self) -> None:
        state = self.storage.get_state(self.app.id)
        if not state.local_path:
            self.status_text.value = "Arquivo nao encontrado. Baixe novamente ou troque o arquivo."
            self._refresh_action_buttons()
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
        self.replace_button.disabled = True
        self.update_button.disabled = True
        self.progress.visible = True
        self.progress.value = None  # indeterminado ate ter %
        self.status_text.value = "Iniciando download..."
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
            # Exibe o botao de apontar arquivo mesmo se ainda nao estiver instalado
            self.replace_button.visible = True
            self.replace_button.content = "Localizar arquivo baixado"
        else:
            self.progress.visible = False
            self.status_text.value = f"Erro: {result.message}"

        self.action_button.disabled = False
        self.replace_button.disabled = False
        self.update_button.disabled = False
        self._refresh_action_buttons()
        # Se o fallback do navegador pediu localizar, mantem o botao visivel
        if result.outcome == DownloadOutcome.NEEDS_BROWSER and self._current_status() != InstallStatus.INSTALLED:
            self.replace_button.visible = True
            self.replace_button.content = "Localizar arquivo baixado"
        self._safe_update()

    # ------------------------------------------------------------------
    async def _on_locate(self, e: ft.ControlEvent) -> None:
        # Planilhas: aceita xlsx e xlsm no seletor; exe usa a extensao do tipo.
        if self.app.tipo.is_spreadsheet:
            allowed = [AppType.XLSX.value, AppType.XLSM.value]
        else:
            allowed = [self.app.tipo.value]
        files = await self.file_picker.pick_files(
            dialog_title=f"Selecione o arquivo ({self.app.nome})",
            allow_multiple=False,
            allowed_extensions=allowed,
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
            self.status_text.value = "Arquivo registrado/atualizado com sucesso."
        else:
            self.status_text.value = f"Erro: {result.message}"
        self._refresh_action_buttons()
        self._safe_update()
