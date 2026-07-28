"""Persistencia de favoritos do usuario."""
from __future__ import annotations

import json
from pathlib import Path

import config


class FavoritesStore:
    """Lista de app_id favoritos em ``favorites.json`` (LOCALAPPDATA)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.FAVORITES_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ids: list[str] = self._load()

    def _load(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(raw, dict):
            raw = raw.get("apps", [])
        if not isinstance(raw, list):
            return []
        seen: list[str] = []
        for item in raw:
            aid = str(item).strip()
            if aid and aid not in seen:
                seen.append(aid)
        return seen

    def _save(self) -> None:
        self.path.write_text(
            json.dumps({"apps": self._ids}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def list_ids(self) -> list[str]:
        return list(self._ids)

    def is_favorite(self, app_id: str) -> bool:
        return app_id in self._ids

    def toggle(self, app_id: str) -> bool:
        """Alterna favorito. Retorna True se passou a ser favorito."""
        aid = (app_id or "").strip()
        if not aid:
            return False
        if aid in self._ids:
            self._ids = [x for x in self._ids if x != aid]
            self._save()
            return False
        self._ids.append(aid)
        self._save()
        return True
