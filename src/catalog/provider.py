"""Provedores de catalogo de aplicativos.

- ``LocalCatalogProvider``: le o catalogo de um arquivo JSON local (uso atual).
- ``RemoteCatalogProvider``: baixa o catalogo de uma URL (ex.: SharePoint) - preparado
  para o futuro, quando o acesso remoto estiver validado.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

import config
from models import AppInfo


class CatalogProvider(ABC):
    """Interface de um provedor de catalogo."""

    @abstractmethod
    def load(self) -> list[AppInfo]:
        """Retorna a lista de aplicativos do catalogo."""
        raise NotImplementedError


def _parse_catalog(raw: str) -> list[AppInfo]:
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("apps", [])
    apps: list[AppInfo] = []
    for item in data:
        try:
            apps.append(AppInfo.from_dict(item))
        except (KeyError, TypeError):
            # ignora entradas malformadas para nao quebrar a UI
            continue
    return apps


class LocalCatalogProvider(CatalogProvider):
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.CATALOG_FILE

    def load(self) -> list[AppInfo]:
        if not self.path.exists():
            return []
        return _parse_catalog(self.path.read_text(encoding="utf-8"))


class RemoteCatalogProvider(CatalogProvider):
    """Baixa um catalog.json de uma URL remota (ex.: SharePoint).

    Preparado para uso futuro. Em caso de falha (rede/autenticacao), pode cair no
    provedor local passado como ``fallback``.
    """

    def __init__(self, url: str, fallback: CatalogProvider | None = None) -> None:
        self.url = url
        self.fallback = fallback

    def load(self) -> list[AppInfo]:
        try:
            import requests

            resp = requests.get(self.url, timeout=20, allow_redirects=True)
            resp.raise_for_status()
            return _parse_catalog(resp.text)
        except Exception:
            if self.fallback is not None:
                return self.fallback.load()
            return []


def get_default_provider() -> CatalogProvider:
    """Retorna o provedor conforme a configuracao.

    Usa o remoto se ``config.REMOTE_CATALOG_URL`` estiver definido, com o local como
    fallback; caso contrario, usa apenas o local.
    """
    local = LocalCatalogProvider()
    if config.REMOTE_CATALOG_URL:
        return RemoteCatalogProvider(config.REMOTE_CATALOG_URL, fallback=local)
    return local
