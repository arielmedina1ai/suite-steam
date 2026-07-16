"""Provedores de catalogo de aplicativos.

Fonte principal: catalog.json via link de download direto (HTTP).
Imagens do catalogo tambem preferem download direto.
Fallback: ultimo cache em %LOCALAPPDATA%/SuitePetrobras/catalog/.

Os apps em si (exe/xlsx/xlsm) continuam sendo baixados via PnP/PowerShell.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

import config
from models import AppInfo

ProgressCb = Callable[[float, str], None]


class CatalogProvider(ABC):
    @abstractmethod
    def load(self) -> list[AppInfo]:
        raise NotImplementedError


@dataclass
class CatalogSyncResult:
    apps: list[AppInfo]
    message: str = ""
    from_cache: bool = False
    ok: bool = True


def _parse_catalog(raw: str) -> list[AppInfo]:
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("apps", [])
    apps: list[AppInfo] = []
    for item in data:
        try:
            apps.append(AppInfo.from_dict(item))
        except (KeyError, TypeError):
            continue
    return apps


def _is_http_url(value: str) -> bool:
    v = (value or "").strip().lower()
    return v.startswith("http://") or v.startswith("https://")


def _image_filename(app: AppInfo) -> str:
    raw = (app.imagem or "").strip()
    if _is_http_url(raw):
        name = unquote(Path(urlparse(raw).path).name)
        # download.aspx?UniqueId=... -> usa id do app como nome
        if name.lower() in ("download.aspx", "download"):
            return f"{app.id}.png"
        if name and "." in name:
            return name.split("?")[0]
        if name:
            return name
    name = Path(raw.replace("\\", "/")).name
    if name:
        return name
    return f"{app.id}.png"


def _download_direct(url: str, destino: Path) -> tuple[bool, str]:
    """Baixa um arquivo pelo link exatamente como informado (ex.: download.aspx?UniqueId=...)."""
    try:
        import requests
    except ImportError:
        return False, "Biblioteca 'requests' nao instalada."

    destino.parent.mkdir(parents=True, exist_ok=True)

    try:
        with requests.get(
            url,
            stream=True,
            allow_redirects=True,
            timeout=60,
            headers={"User-Agent": "SuitePetrobras/1.0"},
        ) as resp:
            if resp.status_code in (401, 403):
                return False, f"Acesso negado (HTTP {resp.status_code}). Link exige autenticacao."
            if resp.status_code >= 400:
                return False, f"Falha no download (HTTP {resp.status_code})."

            content_type = (resp.headers.get("Content-Type") or "").lower()
            # SharePoint devolve HTML de login quando o link nao e realmente direto
            if "text/html" in content_type or "application/xhtml" in content_type:
                return False, (
                    "O servidor retornou HTML (provavel pagina de login). "
                    "Use um link de download direto do arquivo."
                )

            with open(destino, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        fh.write(chunk)
    except Exception as exc:
        return False, f"Erro no download direto: {exc}"

    if not destino.exists() or destino.stat().st_size == 0:
        return False, "Arquivo vazio ou nao encontrado apos o download."
    return True, "OK"


def _load_cached_catalog() -> list[AppInfo]:
    path = config.CATALOG_CACHE_FILE
    if not path.exists():
        return []
    try:
        apps = _parse_catalog(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    for app in apps:
        local_img = config.CATALOG_IMAGES_DIR / _image_filename(app)
        if local_img.exists():
            app.imagem = str(local_img)
    return apps


class LocalCatalogProvider(CatalogProvider):
    """Le um JSON local (fallback de desenvolvimento)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.DATA_DIR / "catalog.example.json")

    def load(self) -> list[AppInfo]:
        if not self.path.exists():
            return []
        return _parse_catalog(self.path.read_text(encoding="utf-8"))


class SharePointCatalogProvider(CatalogProvider):
    """Baixa catalog.json (e imagens) por link de download direto e mantem cache."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or config.REMOTE_CATALOG_URL

    def load(self) -> list[AppInfo]:
        return self.sync().apps

    def sync(self, progress: ProgressCb | None = None) -> CatalogSyncResult:
        def report(pct: float, msg: str) -> None:
            if progress:
                progress(pct, msg)

        if not self.url:
            cached = _load_cached_catalog()
            if cached:
                return CatalogSyncResult(
                    apps=cached,
                    message="catalog.remote_url nao configurado. Usando cache local.",
                    from_cache=True,
                    ok=False,
                )
            apps = LocalCatalogProvider().load()
            return CatalogSyncResult(
                apps=apps,
                message=(
                    "Configure catalog.remote_url no settings.json com o link "
                    "de download direto do catalog.json no SharePoint."
                ),
                from_cache=False,
                ok=False,
            )

        config.CATALOG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        config.CATALOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

        report(0.1, "Baixando catalog.json (download direto)...")
        dest = config.CATALOG_CACHE_FILE
        ok, detail = _download_direct(self.url, dest)

        if not ok:
            cached = _load_cached_catalog()
            if cached:
                return CatalogSyncResult(
                    apps=cached,
                    message=f"Falha ao sincronizar catalogo ({detail}). Usando cache.",
                    from_cache=True,
                    ok=False,
                )
            return CatalogSyncResult(
                apps=[],
                message=f"Falha ao sincronizar catalogo: {detail}",
                from_cache=False,
                ok=False,
            )

        try:
            # valida que o conteudo e JSON (nao HTML salvo com nome .json)
            text = dest.read_text(encoding="utf-8")
            if text.lstrip().startswith("<"):
                raise json.JSONDecodeError("Conteudo parece HTML, nao JSON.", text, 0)
            apps = _parse_catalog(text)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            cached = _load_cached_catalog()
            # remove arquivo invalido para nao poluir o cache
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
            return CatalogSyncResult(
                apps=cached,
                message=(
                    f"Arquivo baixado nao e um catalog.json valido ({exc}). "
                    "Confira se o link e de download direto."
                ),
                from_cache=bool(cached),
                ok=False,
            )

        total = max(len(apps), 1)
        for idx, app in enumerate(apps):
            if not _is_http_url(app.imagem):
                local_img = config.CATALOG_IMAGES_DIR / _image_filename(app)
                if local_img.exists():
                    app.imagem = str(local_img)
                continue

            report(0.4 + 0.6 * (idx / total), f"Baixando imagem: {app.nome}...")
            nome_img = _image_filename(app)
            img_path = config.CATALOG_IMAGES_DIR / nome_img
            img_ok, _ = _download_direct(app.imagem, img_path)
            if img_ok:
                app.imagem = str(img_path)

        report(1.0, "Catalogo sincronizado.")
        return CatalogSyncResult(
            apps=apps,
            message=f"Catalogo sincronizado ({len(apps)} aplicativo(s)).",
            from_cache=False,
            ok=True,
        )


def get_default_provider() -> CatalogProvider:
    if config.REMOTE_CATALOG_URL:
        return SharePointCatalogProvider(config.REMOTE_CATALOG_URL)
    return SharePointCatalogProvider(None)
