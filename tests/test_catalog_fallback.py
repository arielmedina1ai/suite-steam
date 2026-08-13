"""Fallback de catalogo apos falha de sincronizacao SharePoint."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from catalog.provider import (  # noqa: E402
    SharePointCatalogProvider,
    offline_fallback_catalog,
)
from models import CatalogData  # noqa: E402
from services.sharepoint_manager import SharePointResult  # noqa: E402


def test_sync_fallback_cache(tmp_path, monkeypatch):
    import config

    cache_file = tmp_path / "catalog.json"
    cache_file.write_text(
        json.dumps(
            {
                "suite": {"versao": "1.0.0", "download_url": ""},
                "gerencias": [],
                "setores": [],
                "apps": [{"id": "app1", "nome": "App 1", "setor": "s1"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CATALOG_CACHE_FILE", cache_file)
    monkeypatch.setattr(config, "CATALOG_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "CATALOG_IMAGES_DIR", tmp_path / "images")

    fail = SharePointResult(
        ok=False, message="Falha PnP", stdout="", stderr="DEP_ERROR: MODULE_NOT_LOADED"
    )
    with patch("catalog.provider.baixar_do_sharepoint", return_value=fail):
        result = SharePointCatalogProvider("https://example.sharepoint.com/x").sync()

    assert not result.ok
    assert result.from_cache
    assert not result.needs_access_request
    assert any(app.id == "app1" for app in result.catalog.apps)


def test_sync_fallback_local_example(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "CATALOG_CACHE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(config, "CATALOG_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "CATALOG_IMAGES_DIR", tmp_path / "images")
    example = tmp_path / "catalog.example.json"
    example.write_text(
        json.dumps(
            {
                "suite": {"versao": "0.0.1", "download_url": ""},
                "gerencias": [],
                "setores": [],
                "apps": [{"id": "local", "nome": "Local", "setor": "s1"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CATALOG_EXAMPLE_FILE", example)

    fail = SharePointResult(ok=False, message="Sem rede", stdout="", stderr="")
    with patch("catalog.provider.baixar_do_sharepoint", return_value=fail):
        result = SharePointCatalogProvider("https://example.sharepoint.com/x").sync()

    assert not result.ok
    assert not result.from_cache
    assert not result.needs_access_request
    assert "exemplo" in result.message.lower()
    assert any(app.id == "local" for app in result.catalog.apps)


def test_sync_access_denied_marca_pedido_de_acesso(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "CATALOG_CACHE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(config, "CATALOG_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "CATALOG_IMAGES_DIR", tmp_path / "images")
    example = tmp_path / "catalog.example.json"
    example.write_text(
        json.dumps(
            {
                "suite": {"versao": "0.0.1", "download_url": ""},
                "gerencias": [],
                "setores": [],
                "apps": [{"id": "local", "nome": "Local", "setor": "s1"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CATALOG_EXAMPLE_FILE", example)

    fail = SharePointResult(
        ok=False,
        message="Sem permissao",
        stdout="",
        stderr="Access is denied. (Exception from HRESULT: 0x80070005 (E_ACCESSDENIED))",
    )
    with patch("catalog.provider.baixar_do_sharepoint", return_value=fail):
        result = SharePointCatalogProvider("https://example.sharepoint.com/x").sync()

    assert not result.ok
    assert result.needs_access_request


def test_sync_invalid_json_fallback_example(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "CATALOG_CACHE_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(config, "CATALOG_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "CATALOG_IMAGES_DIR", tmp_path / "images")
    example = tmp_path / "catalog.example.json"
    example.write_text(
        json.dumps(
            {
                "suite": {"versao": "0.0.1", "download_url": ""},
                "gerencias": [],
                "setores": [],
                "apps": [{"id": "local", "nome": "Local", "setor": "s1"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CATALOG_EXAMPLE_FILE", example)

    bad = tmp_path / "catalog.json"
    bad.write_text("<html>not json</html>", encoding="utf-8")
    ok_download = SharePointResult(ok=True, path=bad, message="ok")
    with patch("catalog.provider.baixar_do_sharepoint", return_value=ok_download):
        result = SharePointCatalogProvider("https://example.sharepoint.com/x").sync()

    assert not result.ok
    assert not result.from_cache
    assert "exemplo" in result.message.lower()
    assert any(app.id == "local" for app in result.catalog.apps)


def test_offline_fallback_catalog(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "CATALOG_CACHE_FILE", tmp_path / "missing.json")
    example = tmp_path / "catalog.example.json"
    example.write_text(
        json.dumps(
            {
                "suite": {"versao": "0.0.1", "download_url": ""},
                "gerencias": [],
                "setores": [],
                "apps": [{"id": "local", "nome": "Local", "setor": "s1"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CATALOG_EXAMPLE_FILE", example)
    result = offline_fallback_catalog(reason="teste")
    assert not result.ok
    assert "exemplo" in result.message.lower()
    assert any(app.id == "local" for app in result.catalog.apps)


def test_catalog_init_nao_executa_reparo():
    """Import de catalog nao deve disparar RuntimeError/reparo."""
    import importlib

    import catalog

    importlib.reload(catalog)
    assert hasattr(catalog, "SharePointCatalogProvider")
    assert CatalogData is not None
