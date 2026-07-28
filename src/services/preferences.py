"""Preferencias locais do usuario (ex.: gerencia selecionada)."""
from __future__ import annotations

import json
from pathlib import Path

import config


class PreferencesStore:
    """Persiste preferencias em ``preferences.json`` (LOCALAPPDATA)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.USER_DATA_DIR / "preferences.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_gerencia_id(self) -> str:
        """Id da gerencia selecionada; string vazia = sem filtro."""
        return str(self._data.get("gerencia_id", "") or "").strip()

    def set_gerencia_id(self, gerencia_id: str | None) -> None:
        gid = (gerencia_id or "").strip()
        self._data["gerencia_id"] = gid
        self._save()
