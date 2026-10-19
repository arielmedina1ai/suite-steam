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

FAVORITE_GROUP_TITLE = "Favoritos"


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


def favorite_link_group(groups: list[LinkGroup], urls: list[str]) -> LinkGroup | None:
    """Grupo local Favoritos, na ordem em que as urls foram favoritadas.

    Url que nao esta num links.json valido fica de fora. A mesma url em
    dois grupos entra uma vez, com o titulo da primeira ocorrencia.
    Sem nenhum item visivel, devolve None.
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
    if not picked:
        return None
    return LinkGroup(titulo=FAVORITE_GROUP_TITLE, links=picked)


def groups_with_favorites(groups: list[LinkGroup], urls: list[str]) -> list[LinkGroup]:
    """Favoritos acima dos grupos do arquivo. A lista original nao muda."""
    favorite = favorite_link_group(groups, urls)
    if favorite is None:
        return list(groups)
    return [favorite, *list(groups)]
