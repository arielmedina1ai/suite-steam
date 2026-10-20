"""Favoritos de links deste usuario, neste computador.

O arquivo fica em ``%LOCALAPPDATA%/<data_dir>/link_favorites.json``,
ao lado de ``favorites.json``, e nao entra no links.json nem no SharePoint.
A ordem da lista e a ordem em que a pessoa favoritou.
"""
from __future__ import annotations

import json
from pathlib import Path

import config
from models import LinkGroup, LinkItem
from services.favorites import apply_visible_order, order_after_drop


class LinkFavoritesStore:
    """Lista de urls favoritas. Arquivo separado do favorito de aplicativo."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.LINK_FAVORITES_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._urls: list[str] = self._load()

    def _load(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(raw, dict):
            raw = raw.get("urls", [])
        if not isinstance(raw, list):
            return []
        seen: list[str] = []
        for item in raw:
            url = str(item).strip()
            if url and url not in seen:
                seen.append(url)
        return seen

    def _save(self) -> None:
        self.path.write_text(
            json.dumps({"urls": self._urls}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def list_urls(self) -> list[str]:
        return list(self._urls)

    def is_favorite(self, url: str) -> bool:
        return (url or "").strip() in self._urls

    def toggle(self, url: str) -> bool:
        """Alterna favorito. Retorna True se passou a ser favorito."""
        key = (url or "").strip()
        if not key:
            return False
        if key in self._urls:
            self._urls = [item for item in self._urls if item != key]
            self._save()
            return False
        self._urls.append(key)
        self._save()
        return True

    def move_to_index(self, src: str, index: int, visible: list[str]) -> bool:
        """Grava o link visivel no indice da secao. Fora da secao, nao grava.

        Url que ja nao esta no arquivo valido permanece no json local.
        """
        new_visible = order_after_drop(visible, src, index)
        if new_visible is None:
            return False
        updated = apply_visible_order(self._urls, new_visible)
        if updated == self._urls:
            return False
        self._urls = updated
        self._save()
        return True


def visible_favorite_links(groups: list[LinkGroup], urls: list[str]) -> list[LinkItem]:
    """Links marcados que ainda estao no arquivo, na ordem em que foram marcados.

    Url que nao esta num links.json valido fica de fora. A mesma url em
    dois grupos entra uma vez, com o titulo da primeira ocorrencia.
    """
    first: dict[str, LinkItem] = {}
    for group in groups:
        for item in group.links:
            key = (item.url or "").strip()
            if key and key not in first:
                first[key] = item
    picked: list[LinkItem] = []
    seen: set[str] = set()
    for raw in urls:
        key = (raw or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        item = first.get(key)
        if item is None:
            continue
        picked.append(item)
    return picked
