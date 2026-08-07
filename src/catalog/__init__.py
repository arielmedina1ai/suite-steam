"""Provedores de catálogo com gate de dependências no startup."""
from __future__ import annotations

import logging
import sys

from dependency_check import ensure_dependencies

log = logging.getLogger(__name__)


def _validate_startup_dependencies() -> None:
    if sys.platform != "win32":
        return
    result = ensure_dependencies(auto_repair=True, timeout=120)
    if result.ok:
        log.info("Dependências do SharePoint validadas: %s", result.status)
        return
    message = str(result.details.get("message", "não foi possível validar as dependências."))
    log.error("Inicialização bloqueada: status=%s; motivo=%s", result.status, message)
    raise RuntimeError(
        "Não foi possível validar a dependência do SharePoint "
        f"(status: {result.status}). Consulte o log da aplicação."
    )


_validate_startup_dependencies()

from .provider import (  # noqa: E402
    CatalogProvider,
    LocalCatalogProvider,
    RemoteCatalogProvider,
    get_default_provider,
)

__all__ = [
    "CatalogProvider",
    "LocalCatalogProvider",
    "RemoteCatalogProvider",
    "get_default_provider",
]