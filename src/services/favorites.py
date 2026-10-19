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

    def move_visible(self, src: str, dst: str, visible: list[str]) -> bool:
        """Move um app visivel para a posicao de outro, na mesma secao.

        Menos de dois itens visiveis, ou um id de fora da secao, nao grava.
        Favoritos que nao estao na lista visivel ficam no lugar.
        """
        new_visible = move_before(visible, src, dst)
        if new_visible is None:
            return False
        updated = apply_visible_order(self._ids, new_visible)
        if updated == self._ids:
            return False
        self._ids = updated
        self._save()
        return True


def move_before(items: list[str], src: str, dst: str) -> list[str] | None:
    """Coloca src na posicao de dst. Sem dois itens distintos, devolve None."""
    if len(items) < 2:
        return None
    src_key = (src or "").strip()
    dst_key = (dst or "").strip()
    if not src_key or not dst_key or src_key == dst_key:
        return None
    if src_key not in items or dst_key not in items:
        return None
    moved = [item for item in items if item != src_key]
    moved.insert(moved.index(dst_key), src_key)
    if moved == list(items):
        return None
    return moved


def apply_visible_order(full: list[str], new_visible: list[str]) -> list[str]:
    """Troca a ordem dos itens visiveis e preserva o restante nas mesmas vagas."""
    wanted = list(new_visible)
    wanted_set = set(wanted)
    present = [item for item in full if item in wanted_set]
    if len(present) != len(wanted) or set(present) != wanted_set:
        return list(full)
    seq = iter(wanted)
    return [next(seq) if item in wanted_set else item for item in full]
