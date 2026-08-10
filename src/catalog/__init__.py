"""Provedores de catálogo."""
from .provider import (
    CatalogProvider,
    CatalogSyncResult,
    LocalCatalogProvider,
    SharePointCatalogProvider,
)

__all__ = [
    "CatalogProvider",
    "CatalogSyncResult",
    "LocalCatalogProvider",
    "SharePointCatalogProvider",
]