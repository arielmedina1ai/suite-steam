"""Provedores de catalogo de aplicativos.

Fonte oficial: catalog.json no SharePoint (settings.json > catalog.remote_url).
Cache local: %LOCALAPPDATA%/<app.data_dir>/catalog/

Capas (`imagem`) e icones (`icone`): baixados sob demanda e reutilizados via
images_manifest.json. So rebaixam se URL ou *_versao mudarem.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

import config
from models import AppInfo, CatalogData, parse_catalog_dict
from services.sharepoint_manager import (
    SharePointBatchItem,
    baixar_do_sharepoint,
    baixar_varios_do_sharepoint,
    parsear_link_sharepoint,
)

ProgressCb = Callable[[float, str], None]

# Chaves no manifest / lote (evita colisao capa vs icone do mesmo app)
_KIND_IMAGEM = "imagem"
_KIND_ICONE = "icone"


class CatalogProvider(ABC):
    @abstractmethod
    def load(self) -> CatalogData:
        raise NotImplementedError


@dataclass
class CatalogSyncResult:
    catalog: CatalogData
    message: str = ""
    from_cache: bool = False
    ok: bool = True

    @property
    def apps(self) -> list[AppInfo]:
        return self.catalog.apps


def _parse_catalog(raw: str) -> CatalogData:
    data = json.loads(raw)
    return parse_catalog_dict(data)


def _is_http_url(value: str) -> bool:
    v = (value or "").strip().lower()
    return v.startswith("http://") or v.startswith("https://")


def _remote_filename(url: str, fallback: str) -> str:
    raw = (url or "").strip()
    if _is_http_url(raw):
        try:
            info = parsear_link_sharepoint(raw)
            if info.get("tipo") == "unique_id":
                return fallback
            nome = info.get("nome_arquivo")
            if nome:
                return nome
        except ValueError:
            pass
        name = unquote(Path(urlparse(raw).path).name)
        if name.lower() in ("download.aspx", "download"):
            return fallback
        if name and "." in name:
            return name.split("?")[0]
        if name:
            return name
    name = Path(raw.replace("\\", "/")).name
    if name:
        return name
    return fallback


def _image_filename(app: AppInfo) -> str:
    return _remote_filename(app.imagem, f"{app.id}.img")


def _icon_filename(app: AppInfo) -> str:
    return _remote_filename(app.icone, f"{app.id}.ico.img")


def _batch_key(app_id: str, kind: str) -> str:
    return f"{app_id}::{kind}"


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


def _media_cache_hit(
    app_id: str,
    remote_url: str,
    versao: str,
    manifest: dict[str, Any],
    *,
    url_key: str,
    versao_key: str,
    path_key: str,
) -> Path | None:
    entry = manifest.get(app_id)
    if not isinstance(entry, dict):
        return None
    local = Path(str(entry.get(path_key, "")))
    if not local.exists():
        return None
    if str(entry.get(url_key, "")) != remote_url.strip():
        return None
    if str(entry.get(versao_key, "")) != str(versao):
        return None
    return local


def _apply_local_or_cache(
    apps: list[AppInfo],
    manifest: dict[str, Any],
) -> None:
    """Reaponta imagem/icone para arquivos locais (cache) sem baixar."""
    for app in apps:
        # capa
        remote = (app.imagem or "").strip()
        if _is_http_url(remote):
            cached = _media_cache_hit(
                app.id,
                remote,
                app.imagem_versao,
                manifest,
                url_key="url",
                versao_key="imagem_versao",
                path_key="path",
            )
            if cached is not None:
                app.imagem = str(cached)
            else:
                local = config.CATALOG_IMAGES_DIR / _image_filename(app)
                if local.exists():
                    app.imagem = str(local)
        else:
            local = config.CATALOG_IMAGES_DIR / _image_filename(app)
            if local.exists():
                app.imagem = str(local)

        # icone
        remote_ico = (app.icone or "").strip()
        if _is_http_url(remote_ico):
            cached = _media_cache_hit(
                app.id,
                remote_ico,
                app.icone_versao,
                manifest,
                url_key="icone_url",
                versao_key="icone_versao",
                path_key="icone_path",
            )
            if cached is not None:
                app.icone = str(cached)
            else:
                local = config.CATALOG_IMAGES_DIR / _icon_filename(app)
                if local.exists():
                    app.icone = str(local)
        elif remote_ico:
            local = config.CATALOG_IMAGES_DIR / _icon_filename(app)
            if local.exists():
                app.icone = str(local)


def _sync_images(apps: list[AppInfo], progress: ProgressCb | None = None) -> int:
    """Baixa capas e icones novos/alterados em lote (1 WebLogin por site)."""

    def report(pct: float, msg: str) -> None:
        if progress:
            progress(pct, msg)

    config.CATALOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _load_images_manifest()
    downloaded = 0

    # pending: (batch_id, app, kind, remote_url, nome_arquivo)
    pending: list[tuple[str, AppInfo, str, str, str]] = []

    for app in apps:
        # --- capa ---
        remote_url = (app.imagem or "").strip()
        if _is_http_url(remote_url):
            cached = _media_cache_hit(
                app.id,
                remote_url,
                app.imagem_versao,
                manifest,
                url_key="url",
                versao_key="imagem_versao",
                path_key="path",
            )
            if cached is not None:
                app.imagem = str(cached)
            else:
                pending.append(
                    (
                        _batch_key(app.id, _KIND_IMAGEM),
                        app,
                        _KIND_IMAGEM,
                        remote_url,
                        _image_filename(app),
                    )
                )
        else:
            local_img = config.CATALOG_IMAGES_DIR / _image_filename(app)
            if local_img.exists():
                app.imagem = str(local_img)

        # --- icone ---
        remote_ico = (app.icone or "").strip()
        if _is_http_url(remote_ico):
            cached = _media_cache_hit(
                app.id,
                remote_ico,
                app.icone_versao,
                manifest,
                url_key="icone_url",
                versao_key="icone_versao",
                path_key="icone_path",
            )
            if cached is not None:
                app.icone = str(cached)
            else:
                pending.append(
                    (
                        _batch_key(app.id, _KIND_ICONE),
                        app,
                        _KIND_ICONE,
                        remote_ico,
                        _icon_filename(app),
                    )
                )
        elif remote_ico:
            local_ico = config.CATALOG_IMAGES_DIR / _icon_filename(app)
            if local_ico.exists():
                app.icone = str(local_ico)

    if not pending:
        _save_images_manifest(manifest)
        return 0

    report(
        0.55,
        f"Baixando {len(pending)} midia(s) em lote (capas/icones)...",
    )
    batch = baixar_varios_do_sharepoint(
        [
            SharePointBatchItem(id=bid, link=url, nome_arquivo=nome)
            for bid, _app, _kind, url, nome in pending
        ],
        pasta_destino=config.CATALOG_IMAGES_DIR,
        progress=lambda p, m: report(0.55 + p * 0.4, m),
    )

    by_key = {bid: (app, kind, url, nome) for bid, app, kind, url, nome in pending}

    def _store(app: AppInfo, kind: str, remote_url: str, local_path: Path) -> None:
        nonlocal downloaded
        entry = manifest.get(app.id)
        if not isinstance(entry, dict):
            entry = {}
            manifest[app.id] = entry
        if kind == _KIND_IMAGEM:
            app.imagem = str(local_path)
            entry["url"] = remote_url
            entry["imagem_versao"] = str(app.imagem_versao)
            entry["path"] = str(local_path)
        else:
            app.icone = str(local_path)
            entry["icone_url"] = remote_url
            entry["icone_versao"] = str(app.icone_versao)
            entry["icone_path"] = str(local_path)
        downloaded += 1

    for bid, local_path in batch.paths.items():
        meta = by_key.get(bid)
        if not meta:
            continue
        app, kind, remote_url, _nome = meta
        _store(app, kind, remote_url, local_path)

    failed = [bid for bid, *_rest in pending if bid not in batch.paths]
    for bid in failed:
        app, kind, remote_url, nome = by_key[bid]
        label = "icone" if kind == _KIND_ICONE else "imagem"
        report(0.95, f"Retry individual ({label}): {app.nome}...")
        result = baixar_do_sharepoint(
            link=remote_url,
            pasta_destino=config.CATALOG_IMAGES_DIR,
            nome_arquivo=nome,
        )
        if result.ok and result.path and result.path.exists():
            _store(app, kind, remote_url, result.path)

    _save_images_manifest(manifest)
    return downloaded


def _load_cached_catalog() -> CatalogData | None:
    path = config.CATALOG_CACHE_FILE
    if not path.exists():
        return None
    try:
        catalog = _parse_catalog(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    _apply_local_or_cache(catalog.apps, _load_images_manifest())
    return catalog


class LocalCatalogProvider(CatalogProvider):
    """Le o modelo publico catalog.example.json (somente se nao houver remote/cache)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.CATALOG_EXAMPLE_FILE

    def load(self) -> CatalogData:
        if not self.path.exists():
            return CatalogData()
        return _parse_catalog(self.path.read_text(encoding="utf-8"))


class SharePointCatalogProvider(CatalogProvider):
    """Baixa catalog.json via PnP; capas/icones so quando mudam (manifest local)."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or config.REMOTE_CATALOG_URL

    def load(self) -> CatalogData:
        return self.sync().catalog

    def sync(self, progress: ProgressCb | None = None) -> CatalogSyncResult:
        def report(pct: float, msg: str) -> None:
            if progress:
                progress(pct, msg)

        if not self.url:
            cached = _load_cached_catalog()
            if cached is not None and cached.apps:
                return CatalogSyncResult(
                    catalog=cached,
                    message="catalog.remote_url nao configurado. Usando cache local.",
                    from_cache=True,
                    ok=False,
                )
            catalog = LocalCatalogProvider().load()
            return CatalogSyncResult(
                catalog=catalog,
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
            if cached is not None:
                return CatalogSyncResult(
                    catalog=cached,
                    message=f"Falha ao sincronizar catalogo ({result.message}). Usando cache.",
                    from_cache=True,
                    ok=False,
                )
            catalog = LocalCatalogProvider().load()
            return CatalogSyncResult(
                catalog=catalog,
                message=(
                    f"Falha ao sincronizar catalogo ({result.message}). "
                    "Usando catalogo local de exemplo."
                ),
                from_cache=False,
                ok=False,
            )

        try:
            text = result.path.read_text(encoding="utf-8")
            if text.lstrip().startswith("<"):
                raise json.JSONDecodeError("Conteudo parece HTML, nao JSON.", text, 0)
            catalog = _parse_catalog(text)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            cached = _load_cached_catalog()
            if cached is not None:
                return CatalogSyncResult(
                    catalog=cached,
                    message=f"Catalogo invalido ({exc}). Usando cache.",
                    from_cache=True,
                    ok=False,
                )
            catalog = LocalCatalogProvider().load()
            return CatalogSyncResult(
                catalog=catalog,
                message=(
                    f"Catalogo invalido ({exc}). "
                    "Usando catalogo local de exemplo."
                ),
                from_cache=False,
                ok=False,
            )

        report(0.55, "Verificando capas e icones em cache...")
        _sync_images(catalog.apps, progress=report)
        report(1.0, "Catalogo sincronizado.")

        return CatalogSyncResult(
            catalog=catalog,
            message="",
            from_cache=False,
            ok=True,
        )


def offline_fallback_catalog(reason: str = "") -> CatalogSyncResult:
    """Cache local ou catalogo de exemplo — mantem a app aberta apos falha inesperada."""
    suffix = f" ({reason})" if reason else ""
    cached = _load_cached_catalog()
    if cached is not None:
        return CatalogSyncResult(
            catalog=cached,
            message=f"Usando cache local.{suffix}",
            from_cache=True,
            ok=False,
        )
    catalog = LocalCatalogProvider().load()
    return CatalogSyncResult(
        catalog=catalog,
        message=f"Usando catalogo local de exemplo.{suffix}",
        from_cache=False,
        ok=False,
    )
