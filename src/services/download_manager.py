"""Download de aplicativos a partir de links SharePoint (PnP + PowerShell)."""
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
            return self._browser_fallback(app, f"Falha ao chamar o SharePoint Manager: {exc}")

        if result.ok and result.path and result.path.exists():
            self.storage.set_installed(app.id, result.path, app.versao)
            return DownloadResult(
                DownloadOutcome.SUCCESS,
                local_path=result.path,
                message=result.message or "Download concluido.",
            )

        return self._browser_fallback(
            app,
            result.message or "Nao foi possivel baixar via SharePoint/PnP.",
        )

    # ------------------------------------------------------------------
    def _guess_filename(self, app: AppInfo) -> str:
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
                f"{reason}\n\nAbrimos o link no navegador. "
                "Tente novamente pelo botao de download apos autenticar."
            ),
        )
