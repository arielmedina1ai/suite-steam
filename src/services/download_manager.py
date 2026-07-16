"""Download de aplicativos a partir de um link (inicialmente SharePoint).

Duas estrategias, para permitir testar na pratica o que funciona no ambiente:

1. Download direto via ``requests`` (stream, seguindo redirects).
2. Fallback: quando a resposta parece ser uma pagina de login/autenticacao (SharePoint
   costuma responder com HTML nesses casos) ou o status e 401/403, abre o link no
   navegador padrao para o usuario baixar manualmente e depois apontar o arquivo.
"""
from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

from models import AppInfo
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


# tipos de conteudo que indicam pagina web (login) em vez de arquivo binario
_HTML_HINTS = ("text/html", "application/xhtml")


def _guess_extension(app: AppInfo) -> str:
    return app.tipo.file_extension


def _filename_from_url(url: str, fallback: str) -> str:
    path = urlparse(url).path
    name = unquote(Path(path).name)
    return name or fallback


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

        try:
            import requests
        except ImportError:
            return DownloadResult(
                DownloadOutcome.ERROR,
                message="Biblioteca 'requests' nao instalada.",
            )

        report(0.0, "Conectando...")
        try:
            with requests.get(
                app.download_url,
                stream=True,
                allow_redirects=True,
                timeout=30,
                headers={"User-Agent": "SuitePetrobras/1.0"},
            ) as resp:
                # autenticacao/permissao negada -> fallback navegador
                if resp.status_code in (401, 403):
                    return self._browser_fallback(
                        app, f"Acesso negado (HTTP {resp.status_code})."
                    )
                if resp.status_code >= 400:
                    return DownloadResult(
                        DownloadOutcome.ERROR,
                        message=f"Falha no download (HTTP {resp.status_code}).",
                    )

                content_type = resp.headers.get("Content-Type", "").lower()
                if any(hint in content_type for hint in _HTML_HINTS):
                    # SharePoint devolveu uma pagina (provavelmente login)
                    return self._browser_fallback(
                        app,
                        "O servidor retornou uma pagina web (provavel login). "
                        "Faca o download pelo navegador.",
                    )

                ext = _guess_extension(app)
                default_name = f"{app.id}{ext}"
                filename = _filename_from_url(resp.url, default_name)
                if not Path(filename).suffix:
                    filename += ext
                target = self.storage.app_dir(app.id) / filename

                total = int(resp.headers.get("Content-Length", 0) or 0)
                downloaded = 0
                report(0.02, "Baixando...")
                with open(target, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(downloaded / total, 0.99)
                            report(pct, f"Baixando... {int(pct * 100)}%")
                        else:
                            report(0.5, "Baixando...")

            report(1.0, "Concluido")
            self.storage.set_installed(app.id, target, app.versao)
            return DownloadResult(DownloadOutcome.SUCCESS, local_path=target, message="Download concluido.")

        except Exception as exc:  # rede, timeout, SSL corporativo, etc.
            return self._browser_fallback(app, f"Nao foi possivel baixar automaticamente: {exc}")

    # ------------------------------------------------------------------
    def _browser_fallback(self, app: AppInfo, reason: str) -> DownloadResult:
        try:
            webbrowser.open(app.download_url)
        except Exception:
            pass
        return DownloadResult(
            DownloadOutcome.NEEDS_BROWSER,
            message=(
                f"{reason}\n\nAbrimos o link no navegador. Apos baixar o arquivo, use "
                "'Localizar arquivo baixado' para aponta-lo na Suite."
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
