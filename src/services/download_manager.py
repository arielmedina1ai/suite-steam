"""Download de aplicativos a partir de links SharePoint.

Estrategia principal (validada no ambiente Petrobras):
1. PowerShell + PnP (``sharepoint_manager.baixar_do_sharepoint``) com WebLogin.

Fallback:
2. Abre o link no navegador e permite apontar o arquivo baixado manualmente.
"""
from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

import config
from models import AppInfo
from services.sharepoint_manager import baixar_do_sharepoint, parsear_link_sharepoint
from services.storage import Storage

ProgressCb = Callable[[float, str], None]


class DownloadOutcome(str, Enum):
    SUCCESS = "success"
    NEEDS_BROWSER = "needs_browser"
    ERROR = "error"


@dataclass
class DownloadResult:
    outcome: DownloadOutcome
    local_path: Path | None = None
    message: str = ""


class DownloadManager:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    # ------------------------------------------------------------------
    def download(self, app: AppInfo, progress: ProgressCb | None = None) -> DownloadResult:
        if not app.download_url:
            return DownloadResult(DownloadOutcome.ERROR, message="App sem download_url definido.")

        def report(pct: float, msg: str) -> None:
            if progress:
                progress(pct, msg)

        if not config.SHAREPOINT_ENABLED:
            return self._browser_fallback(
                app,
                "Download SharePoint/PnP desabilitado em settings.json (sharepoint.enabled=false).",
            )

        pasta = self.storage.app_dir(app.id)
        nome = self._guess_filename(app)

        report(0.0, "Iniciando download via SharePoint (PnP)...")
        try:
            result = baixar_do_sharepoint(
                link=app.download_url,
                pasta_destino=pasta,
                nome_arquivo=nome,
                progress=report,
            )
        except Exception as exc:
            return self._browser_fallback(
                app, f"Falha ao chamar o SharePoint Manager: {exc}"
            )

        if result.ok and result.path and result.path.exists():
            self.storage.set_installed(app.id, result.path, app.versao)
            return DownloadResult(
                DownloadOutcome.SUCCESS,
                local_path=result.path,
                message=result.message or "Download concluido.",
            )

        # PnP falhou (auth cancelada, link invalido, modulo ausente, etc.)
        return self._browser_fallback(
            app,
            result.message or "Nao foi possivel baixar via SharePoint/PnP.",
        )

    # ------------------------------------------------------------------
    def _guess_filename(self, app: AppInfo) -> str:
        """Tenta obter o nome do arquivo pelo link; senao usa id + extensao do tipo."""
        try:
            info = parsear_link_sharepoint(app.download_url)
            nome = info.get("nome_arquivo")
            if nome:
                return nome
        except ValueError:
            pass
        return f"{app.id}{app.tipo.file_extension}"

    def _browser_fallback(self, app: AppInfo, reason: str) -> DownloadResult:
        try:
            webbrowser.open(app.download_url)
        except Exception:
            pass
        return DownloadResult(
            DownloadOutcome.NEEDS_BROWSER,
            message=(
                f"{reason}\n\nAbrimos o link no navegador. Apos baixar o arquivo, use "
                "'Localizar arquivo baixado' / 'Trocar arquivo' para aponta-lo na Suite."
            ),
        )

    # ------------------------------------------------------------------
    def register_manual_file(self, app: AppInfo, source: Path) -> DownloadResult:
        """Registra um arquivo baixado manualmente (fallback do navegador)."""
        source = Path(source)
        if not source.exists():
            return DownloadResult(DownloadOutcome.ERROR, message="Arquivo nao encontrado.")
        target = self.storage.app_dir(app.id) / source.name
        try:
            if source.resolve() != target.resolve():
                target.write_bytes(source.read_bytes())
        except Exception as exc:
            return DownloadResult(DownloadOutcome.ERROR, message=f"Falha ao copiar: {exc}")
        self.storage.set_installed(app.id, target, app.versao)
        return DownloadResult(DownloadOutcome.SUCCESS, local_path=target, message="Arquivo registrado.")
