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

    def move_to_index(self, src: str, index: int, visible: list[str]) -> bool:
        """Grava o item visivel no indice da secao. Fora da secao, nao grava.

        Menos de dois itens visiveis nao muda o arquivo. Itens ocultos ficam
        nas mesmas vagas.
        """
        new_visible = order_after_drop(visible, src, index)
        if new_visible is None:
            return False
        updated = apply_visible_order(self._ids, new_visible)
        if updated == self._ids:
            return False
        self._ids = updated
        self._save()
        return True


HOLD_SECONDS = 0.5


def insertion_index(
    pointer: float,
    *,
    count: int,
    origin: float = 0.0,
    size: float,
    spacing: float = 0.0,
) -> int:
    """Indice 0..count-1 do vao mais proximo do ponteiro.

    Fora da secao, cai no extremo mais perto. Com menos de dois itens, fica em 0.
    """
    if count <= 1:
        return 0
    stride = float(size) + float(spacing)
    if stride <= 0:
        return 0
    raw = (float(pointer) - float(origin) - float(size) / 2.0) / stride
    index = int(round(raw))
    if index < 0:
        return 0
    if index > count - 1:
        return count - 1
    return index


def card_hit_index(
    x: float,
    y: float,
    *,
    count: int,
    columns: int,
    card_w: float,
    card_h: float,
    spacing_x: float,
    spacing_y: float,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> int | None:
    """Indice se o ponto esta dentro de um cartao. Vao e fim de linha: None."""
    if count <= 0:
        return None
    columns = max(1, int(columns))
    local_x = float(x) - float(origin_x)
    local_y = float(y) - float(origin_y)
    if local_x < 0 or local_y < 0:
        return None
    stride_x = float(card_w) + float(spacing_x)
    stride_y = float(card_h) + float(spacing_y)
    if stride_x <= 0 or stride_y <= 0:
        return None
    col = int(local_x // stride_x)
    row = int(local_y // stride_y)
    if col < 0 or col >= columns:
        return None
    inside_x = local_x - col * stride_x
    inside_y = local_y - row * stride_y
    if inside_x >= float(card_w) or inside_y >= float(card_h):
        return None
    index = row * columns + col
    if index < 0 or index >= int(count):
        return None
    return index


def grid_insertion_index(
    x: float,
    y: float,
    *,
    count: int,
    columns: int,
    card_w: float,
    card_h: float,
    spacing_x: float,
    spacing_y: float,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> int:
    """Indice de leitura numa grade. O ponteiro fora da grade usa o canto mais perto."""
    if count <= 0:
        return 0
    columns = max(1, int(columns))
    rows = max(1, (int(count) + columns - 1) // columns)
    col = insertion_index(x, count=columns, origin=origin_x, size=card_w, spacing=spacing_x)
    row = insertion_index(y, count=rows, origin=origin_y, size=card_h, spacing=spacing_y)
    return max(0, min(int(count) - 1, row * columns + col))


def order_after_drop(keys: list[str], src: str, index: int) -> list[str] | None:
    """Lista da secao com src no indice. Sem dois itens, ou src de fora, None."""
    if len(keys) < 2:
        return None
    src_key = (src or "").strip()
    if src_key not in keys:
        return None
    rest = [item for item in keys if item != src_key]
    slot = max(0, min(int(index), len(rest)))
    rest.insert(slot, src_key)
    if rest == list(keys):
        return None
    return rest


def layout_slots(keys: list[str], dragging: str | None, index: int | None) -> list[tuple[str, str]]:
    """Sequencia da secao: cartoes e, no arraste, um vao no indice de queda."""
    if not dragging or dragging not in keys or index is None:
        return [("card", key) for key in keys]
    rest = [key for key in keys if key != dragging]
    slot = max(0, min(int(index), len(rest)))
    rows = [("card", key) for key in rest]
    rows.insert(slot, ("gap", dragging))
    return rows


def apply_visible_order(full: list[str], new_visible: list[str]) -> list[str]:
    """Troca a ordem dos itens visiveis e preserva o restante nas mesmas vagas."""
    wanted = list(new_visible)
    wanted_set = set(wanted)
    present = [item for item in full if item in wanted_set]
    if len(present) != len(wanted) or set(present) != wanted_set:
        return list(full)
    seq = iter(wanted)
    return [next(seq) if item in wanted_set else item for item in full]
