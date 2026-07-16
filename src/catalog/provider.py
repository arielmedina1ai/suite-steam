"""Provedores de catalogo de aplicativos.

Fonte principal: catalog.json no SharePoint (PnP), baixado a cada abertura.
Fallback: ultimo cache em %LOCALAPPDATA%/SuitePetrobras/catalog/.
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
from services.sharepoint_manager import baixar_do_sharepoint, parsear_link_sharepoint

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


def _is_sharepoint_url(value: str) -> bool:
    v = (value or "").strip().lower()
    return v.startswith("http://") or v.startswith("https://")


def _image_filename(app: AppInfo) -> str:
    """Nome do arquivo de imagem no cache local."""
    raw = (app.imagem or "").strip()
    if _is_sharepoint_url(raw):
        try:
            info = parsear_link_sharepoint(raw)
            nome = info.get("nome_arquivo")
            if nome:
                return nome
        except ValueError:
            pass
        # fallback pela URL
        name = unquote(Path(urlparse(raw).path).name)
        if name:
            return name
    # caminho relativo tipo assets/images/foo.png
    name = Path(raw.replace("\\", "/")).name
    if name:
        return name
    return f"{app.id}.png"


def _load_cached_catalog() -> list[AppInfo]:
    path = config.CATALOG_CACHE_FILE
    if not path.exists():
        return []
    try:
        apps = _parse_catalog(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    # reaponta imagens para o cache local se existirem
    for app in apps:
        local_img = config.CATALOG_IMAGES_DIR / _image_filename(app)
        if local_img.exists():
            app.imagem = str(local_img)
    return apps


class LocalCatalogProvider(CatalogProvider):
    """Le um JSON local (usado como fallback de desenvolvimento)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.DATA_DIR / "catalog.example.json")

    def load(self) -> list[AppInfo]:
        if not self.path.exists():
            return []
        return _parse_catalog(self.path.read_text(encoding="utf-8"))


class SharePointCatalogProvider(CatalogProvider):
    """Baixa catalog.json + imagens via PnP e mantem cache local."""

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
            # ultimo recurso: exemplo do repo
            apps = LocalCatalogProvider().load()
            return CatalogSyncResult(
                apps=apps,
                message=(
                    "Configure catalog.remote_url no settings.json com o link "
                    "SharePoint do catalog.json."
                ),
                from_cache=False,
                ok=False,
            )

        config.CATALOG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        config.CATALOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

        report(0.05, "Baixando catalog.json do SharePoint...")
        result = baixar_do_sharepoint(
            link=self.url,
            pasta_destino=config.CATALOG_CACHE_DIR,
            nome_arquivo="catalog.json",
            progress=lambda p, m: report(0.05 + p * 0.4, m),
        )

        if not result.ok or not result.path or not result.path.exists():
            cached = _load_cached_catalog()
            if cached:
                return CatalogSyncResult(
                    apps=cached,
                    message=f"Falha ao sincronizar catalogo ({result.message}). Usando cache.",
                    from_cache=True,
                    ok=False,
                )
            return CatalogSyncResult(
                apps=[],
                message=f"Falha ao sincronizar catalogo: {result.message}",
                from_cache=False,
                ok=False,
            )

        try:
            apps = _parse_catalog(result.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            cached = _load_cached_catalog()
            return CatalogSyncResult(
                apps=cached,
                message=f"Catalogo invalido: {exc}",
                from_cache=bool(cached),
                ok=False,
            )

        total = max(len(apps), 1)
        for idx, app in enumerate(apps):
            if not _is_sharepoint_url(app.imagem):
                # caminho local relativo: tenta no cache de imagens se existir
                local_img = config.CATALOG_IMAGES_DIR / _image_filename(app)
                if local_img.exists():
                    app.imagem = str(local_img)
                continue

            report(0.5 + 0.5 * (idx / total), f"Baixando imagem: {app.nome}...")
            nome_img = _image_filename(app)
            img_result = baixar_do_sharepoint(
                link=app.imagem,
                pasta_destino=config.CATALOG_IMAGES_DIR,
                nome_arquivo=nome_img,
            )
            if img_result.ok and img_result.path and img_result.path.exists():
                app.imagem = str(img_result.path)
            else:
                # mantem URL; UI mostra placeholder se falhar
                pass

        report(1.0, "Catalogo sincronizado.")
        return CatalogSyncResult(
            apps=apps,
            message=f"Catalogo sincronizado ({len(apps)} aplicativo(s)).",
            from_cache=False,
            ok=True,
        )


def get_default_provider() -> CatalogProvider:
    """Retorna o provedor SharePoint (com cache) quando houver remote_url."""
    if config.REMOTE_CATALOG_URL:
        return SharePointCatalogProvider(config.REMOTE_CATALOG_URL)
    return SharePointCatalogProvider(None)
