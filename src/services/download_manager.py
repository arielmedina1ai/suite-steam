"""Download de aplicativos a partir de links SharePoint (PnP + PowerShell)."""
from __future__ import annotations

import os
import webbrowser
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

import config
from models import AppInfo
from services.sharepoint_manager import baixar_do_sharepoint, parsear_link_sharepoint
from services.storage import Storage
from services.tutorial import download_tutorial_assets
from services.win_exe import INVALID_EXE_MESSAGE, is_windows_pe

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
        destino = pasta / nome
        # .exe vai para um nome temporario: HTML ou arquivo cortado nao substitui o exe instalado.
        exe = destino.suffix.lower() == ".exe"
        nome_baixado = f".{nome}.baixando" if exe else nome

        report(0.0, "Iniciando download via SharePoint (PnP)...")
        try:
            result = baixar_do_sharepoint(
                link=app.download_url,
                pasta_destino=pasta,
                nome_arquivo=nome_baixado,
                progress=report,
            )
        except Exception as exc:
            if exe:
                self._discard_download(pasta / nome_baixado, destino)
            return self._browser_fallback(app, f"Falha ao chamar o SharePoint Manager: {exc}")

        if result.ok and result.path and result.path.exists():
            path = result.path
            if exe:
                if not is_windows_pe(path):
                    self._discard_download(path, destino)
                    return DownloadResult(DownloadOutcome.ERROR, message=INVALID_EXE_MESSAGE)
                if path.resolve() != destino.resolve():
                    try:
                        os.replace(path, destino)
                    except OSError:
                        self._discard_download(path, destino)
                        return DownloadResult(
                            DownloadOutcome.ERROR,
                            message="Nao foi possivel salvar o executavel. Baixe de novo.",
                        )
                    path = destino
            self.storage.set_installed(app.id, path, app.versao)
            message = (result.message or "Download concluido.").strip()
            try:
                note, errors = download_tutorial_assets(app, progress=report)
            except Exception as exc:
                note, errors = "", [f"Tutorial nao foi salvo. {exc}"]
            parts = [message]
            if note:
                parts.append(note)
            parts.extend(errors)
            return DownloadResult(
                DownloadOutcome.SUCCESS,
                local_path=path,
                message="\n".join(part for part in parts if part),
            )

        if exe:
            self._discard_download(result.path or (pasta / nome_baixado), destino)
        return self._browser_fallback(
            app,
            result.message or "Nao foi possivel baixar via SharePoint/PnP.",
        )

    # ------------------------------------------------------------------
    def _discard_download(self, path: Path, destino: Path) -> None:
        """Apaga o arquivo baixado se ele nao for o exe valido ja instalado."""
        try:
            if not path.is_file():
                return
            if path.resolve() == destino.resolve() and is_windows_pe(path):
                return
            path.unlink()
        except OSError:
            pass

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
