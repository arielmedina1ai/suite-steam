"""Provedores de catalogo de aplicativos.

Fonte oficial: catalog.json no SharePoint (settings.json > catalog.remote_url).
Cache local: %LOCALAPPDATA%/SuitePetrobras/catalog/

Imagens: baixadas sob demanda e reutilizadas via images_manifest.json.
So baixam de novo se a URL ou imagem_versao mudarem (ou se o arquivo local sumir).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
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


def _is_http_url(value: str) -> bool:
    v = (value or "").strip().lower()
    return v.startswith("http://") or v.startswith("https://")


def _image_filename(app: AppInfo) -> str:
    raw = (app.imagem or "").strip()
    if _is_http_url(raw):
        try:
            info = parsear_link_sharepoint(raw)
            if info.get("tipo") == "unique_id":
                return f"{app.id}.img"
            nome = info.get("nome_arquivo")
            if nome:
                return nome
        except ValueError:
            pass
        name = unquote(Path(urlparse(raw).path).name)
        if name.lower() in ("download.aspx", "download"):
            return f"{app.id}.img"
        if name and "." in name:
            return name.split("?")[0]
        if name:
            return name
    name = Path(raw.replace("\\", "/")).name
    if name:
        return name
    return f"{app.id}.img"


def _load_images_manifest() -> dict[str, Any]:
    path = config.CATALOG_IMAGES_MANIFEST
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_images_manifest(manifest: dict[str, Any]) -> None:
    config.CATALOG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    config.CATALOG_IMAGES_MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _image_cache_hit(app: AppInfo, manifest: dict[str, Any]) -> Path | None:
    """Retorna caminho local se a imagem em cache ainda e valida."""
    entry = manifest.get(app.id)
    if not isinstance(entry, dict):
        return None
    local = Path(str(entry.get("path", "")))
    if not local.exists():
        return None
    if str(entry.get("url", "")) != (app.imagem or "").strip():
        return None
    if str(entry.get("imagem_versao", "")) != str(app.imagem_versao):
        return None
    return local


def _sync_images(apps: list[AppInfo], progress: ProgressCb | None = None) -> int:
    """Baixa apenas imagens novas/alteradas. Retorna quantas foram baixadas."""

    def report(pct: float, msg: str) -> None:
        if progress:
            progress(pct, msg)

    config.CATALOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _load_images_manifest()
    downloaded = 0
    http_apps = [a for a in apps if _is_http_url(a.imagem)]
    total = max(len(http_apps), 1)
    done = 0

    for app in apps:
        remote_url = (app.imagem or "").strip()
        if not _is_http_url(remote_url):
            local_img = config.CATALOG_IMAGES_DIR / _image_filename(app)
            if local_img.exists():
                app.imagem = str(local_img)
            continue

        entry = manifest.get(app.id)
        if isinstance(entry, dict):
            local = Path(str(entry.get("path", "")))
            if (
                local.exists()
                and str(entry.get("url", "")) == remote_url
                and str(entry.get("imagem_versao", "")) == str(app.imagem_versao)
            ):
                app.imagem = str(local)
                done += 1
                continue

        report(0.55 + 0.4 * (done / total), f"Baixando imagem: {app.nome}...")
        nome_img = _image_filename(app)
        img_result = baixar_do_sharepoint(
            link=remote_url,
            pasta_destino=config.CATALOG_IMAGES_DIR,
            nome_arquivo=nome_img,
        )
        if img_result.ok and img_result.path and img_result.path.exists():
            app.imagem = str(img_result.path)
            manifest[app.id] = {
                "url": remote_url,
                "imagem_versao": str(app.imagem_versao),
                "path": str(img_result.path),
            }
            downloaded += 1
        done += 1

    _save_images_manifest(manifest)
    return downloaded


def _load_cached_catalog() -> list[AppInfo]:
    path = config.CATALOG_CACHE_FILE
    if not path.exists():
        return []
    try:
        apps = _parse_catalog(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    manifest = _load_images_manifest()
    for app in apps:
        cached = _image_cache_hit(app, manifest)
        if cached is not None:
            app.imagem = str(cached)
        else:
            local_img = config.CATALOG_IMAGES_DIR / _image_filename(app)
            if local_img.exists():
                app.imagem = str(local_img)
    return apps


class LocalCatalogProvider(CatalogProvider):
    """Le o modelo publico catalog.example.json (somente se nao houver remote/cache)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.CATALOG_EXAMPLE_FILE

    def load(self) -> list[AppInfo]:
        if not self.path.exists():
            return []
        return _parse_catalog(self.path.read_text(encoding="utf-8"))


class SharePointCatalogProvider(CatalogProvider):
    """Baixa catalog.json via PnP; imagens so quando mudam (manifest local)."""

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
                    "SharePoint do catalog.json. O arquivo catalog.example.json "
                    "na raiz e apenas um modelo — nao e a fonte em producao."
                ),
                from_cache=False,
                ok=False,
            )

        config.CATALOG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        config.CATALOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

        report(0.05, "Baixando catalog.json via SharePoint (WebLogin)...")
        result = baixar_do_sharepoint(
            link=self.url,
            pasta_destino=config.CATALOG_CACHE_DIR,
            nome_arquivo="catalog.json",
            progress=lambda p, m: report(0.05 + p * 0.45, m),
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
            text = result.path.read_text(encoding="utf-8")
            if text.lstrip().startswith("<"):
                raise json.JSONDecodeError("Conteudo parece HTML, nao JSON.", text, 0)
            apps = _parse_catalog(text)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            cached = _load_cached_catalog()
            return CatalogSyncResult(
                apps=cached,
                message=f"Catalogo invalido: {exc}",
                from_cache=bool(cached),
                ok=False,
            )

        report(0.55, "Verificando imagens em cache...")
        _sync_images(apps, progress=report)
        report(1.0, "Catalogo sincronizado.")

        return CatalogSyncResult(
            apps=apps,
            message="",
            from_cache=False,
            ok=True,
        )


def get_default_provider() -> CatalogProvider:
    if config.REMOTE_CATALOG_URL:
        return SharePointCatalogProvider(config.REMOTE_CATALOG_URL)
    return SharePointCatalogProvider(None)
