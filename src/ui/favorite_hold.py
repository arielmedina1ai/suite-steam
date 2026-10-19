"""Segurar o cartao e arrastar, sem o fantasma do Draggable.

O Flet 0.85 nao espera no Draggable nem abre um vao na secao.
O gesto fica no ponteiro: timer no pressionar, arraste depois.
O detector e pai do cartao e continua montado ate soltar.
O ink do titulo fica no filho, na frente do detector.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import flet as ft

import config
from services.favorites import HOLD_SECONDS, card_hit_index, grid_insertion_index, layout_slots

_GAP = "reorder-gap"
_FLOAT = "reorder-float"


class HoldSection:
    """Uma secao de favoritos. O arraste nao vaza para a outra secao."""

    def __init__(
        self,
        keys: list[str],
        *,
        axis: str,
        card_w: float,
        card_h: float,
        spacing_x: float,
        spacing_y: float,
        columns: int,
        build_card: Callable[[str], ft.Control],
        on_open: Callable[[str], None],
        on_drop: Callable[[str, int], None],
        page: Any = None,
    ) -> None:
        self.keys = list(keys)
        self.axis = axis
        self.card_w = float(card_w)
        self.card_h = float(card_h)
        self.spacing_x = float(spacing_x)
        self.spacing_y = float(spacing_y)
        self.columns = max(1, int(columns))
        self.build_card = build_card
        self.on_open = on_open
        self.on_drop = on_drop
        self.page = page
        self.key: str | None = None
        self.down_at: float | None = None
        self.armed = False
        self.index = 0
        self.x = 0.0
        self.y = 0.0
        self._gen = 0
        self._timer: threading.Timer | None = None
        self._settled = True
        self.flow = self._make_flow()
        self.floater = ft.Container(
            visible=False,
            data=_FLOAT,
            left=0,
            top=0,
            width=self.card_w,
            height=self.card_h,
            scale=1.04,
            ignore_interactions=True,
            border_radius=12,
            shadow=ft.BoxShadow(
                blur_radius=18,
                color="#66000000",
                offset=ft.Offset(0, 8),
            ),
        )
        self.cards: dict[str, ft.Container] = {key: self._make_card(key) for key in self.keys}
        self._anchor_x = 0.0
        self._anchor_y = 0.0
        self._global_x = 0.0
        self._global_y = 0.0
        self.flow.controls = [self.cards[key] for key in self.keys]
        # Copia so do vao. Remontar isto nao mexe no detector do arraste.
        self.visual = self._make_flow()
        self.visual_host = ft.Container(
            visible=False,
            ignore_interactions=True,
            left=0,
            right=0,
            top=0,
            content=self.visual,
        )
        self.stack = ft.Stack(
            controls=[self.flow, self.visual_host, self.floater],
            clip_behavior=ft.ClipBehavior.NONE,
        )
        self._show_idle()

    def _make_flow(self) -> ft.Control:
        if self.axis == "grid":
            return ft.Row(wrap=True, spacing=self.spacing_x, run_spacing=self.spacing_y)
        return ft.Column(
            spacing=self.spacing_y,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def control(self) -> ft.Control:
        """A secao nao e um detector. Cada cartao tem o seu, do tamanho dele."""
        return self.stack

    def _make_card(self, key: str) -> ft.Container:
        """Detector do tamanho do cartao, pai do desenho.

        O ink do titulo e filho desse detector, nao o contrario: assim o
        mouse chega no texto. O detector nao cobre a linha inteira.
        """
        face = self.build_card(key)
        detector = ft.GestureDetector(
            on_pan_down=lambda e, item=key: self._card_down(item, e),
            on_pan_update=lambda e, item=key: self._card_pan(item, e),
            on_pan_end=lambda e, item=key: self._card_up(item, e),
            on_pan_cancel=lambda e, item=key: self._card_pan_cancel(item),
            on_tap_down=lambda e, item=key: self._card_down(item, e),
            on_tap_up=lambda e, item=key: self._card_up(item, e),
            on_tap_move=lambda e, item=key: self._card_pan(item, e),
            content=face,
        )
        shell = ft.Container(
            width=self.card_w if self.axis == "grid" else None,
            height=self.card_h,
            border_radius=12,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=detector,
        )
        shell._hold_face = face
        return shell

    def cancel_press(self) -> None:
        """A estrela levou o clique: nao abre e nao continua o arraste."""
        self._settled = True
        self._cancel_timer()
        self._gen += 1
        if self.armed:
            self._show_idle()
        self._clear_press()

    def pointer_down_at(self, x: float, y: float, now: float) -> str | None:
        """So a area do cartao. Vao da linha e espaco entre cartoes nao abrem nada."""
        index = self.hit_index(x, y)
        if index is None:
            return None
        self.press(self.keys[index], now, x, y)
        return self.keys[index]

    def hit_index(self, x: float, y: float) -> int | None:
        columns = self.columns if self.axis == "grid" else 1
        spacing_x = self.spacing_x if self.axis == "grid" else 0.0
        width = self.card_w if self.axis == "grid" else max(self.card_w, 1.0)
        return card_hit_index(
            x,
            y,
            count=len(self.keys),
            columns=columns,
            card_w=width,
            card_h=self.card_h,
            spacing_x=spacing_x,
            spacing_y=self.spacing_y,
        )

    def press(self, key: str, now: float, x: float = 0.0, y: float = 0.0) -> None:
        """Teste e ponteiro: comeca a contar o segundo. Nao abre e nao ordena."""
        if key not in self.keys:
            return
        self._cancel_timer()
        self._gen += 1
        self._settled = False
        self.key = key
        self.down_at = float(now)
        self.armed = False
        self.index = self.keys.index(key)
        self.x = float(x)
        self.y = float(y)
        if len(self.keys) < 2:
            return
        gen = self._gen
        timer = threading.Timer(HOLD_SECONDS, lambda: self._timer_fired(gen))
        timer.daemon = True
        self._timer = timer
        timer.start()

    def advance(self, now: float) -> bool:
        """O segundo passou com o ponteiro ainda preso. Devolve se armou."""
        if self._settled or self.key is None or self.down_at is None or self.armed:
            return False
        if float(now) - self.down_at < HOLD_SECONDS or len(self.keys) < 2:
            return False
        self._arm()
        return True

    def move(self, x: float, y: float) -> int | None:
        self.x = float(x)
        self.y = float(y)
        if not self.armed:
            return None
        index = self.index_at(self.x, self.y)
        self._place_floater()
        # So a copia do vao muda. O flow dos detectores fica quieto.
        if index != self.index or not self.visual_host.visible:
            self.index = index
            self._show_visual()
            self._paint(self.visual, self.visual_host, self.floater)
        else:
            self.index = index
            self._paint(self.floater)
        return self.index

    def release(self, now: float, x: float | None = None, y: float | None = None) -> str:
        """'click', 'drop' ou 'cancel'. Soltar sempre desliga o gesto."""
        if x is not None and y is not None:
            self.x = float(x)
            self.y = float(y)
            if self.armed:
                self.index = self.index_at(self.x, self.y)
        if self._settled or self.key is None or self.down_at is None:
            self._clear_press()
            return "cancel"
        self._settled = True
        self._cancel_timer()
        key = self.key
        armed = self.armed
        index = self.index
        elapsed = float(now) - self.down_at
        self._clear_press()
        self._show_idle()
        if armed:
            try:
                self.on_drop(key, index)
            except Exception:
                return "drop"
            return "drop"
        if elapsed < HOLD_SECONDS:
            try:
                self.on_open(key)
            except Exception:
                return "click"
            return "click"
        return "cancel"

    def index_at(self, x: float, y: float) -> int:
        if self.axis == "grid":
            return grid_insertion_index(
                x,
                y,
                count=len(self.keys),
                columns=self.columns,
                card_w=self.card_w,
                card_h=self.card_h,
                spacing_x=self.spacing_x,
                spacing_y=self.spacing_y,
            )
        return grid_insertion_index(
            0.0,
            y,
            count=len(self.keys),
            columns=1,
            card_w=self.card_w,
            card_h=self.card_h,
            spacing_x=0.0,
            spacing_y=self.spacing_y,
        )

    def _arm(self) -> None:
        if self.key is None:
            return
        self.armed = True
        self.index = self.index_at(self.x, self.y)
        self.floater.width = self.card_w
        self.floater.height = self.card_h
        self.floater.content = self.build_card(self.key)
        self.floater.visible = True
        self.floater.scale = 1.04
        self._place_floater()
        self._show_visual()
        self._paint(self.flow, self.visual, self.visual_host, self.floater)

    def _place_floater(self) -> None:
        self.floater.left = self.x - self.card_w / 2.0
        self.floater.top = self.y - self.card_h / 2.0

    def _show_idle(self) -> None:
        self.floater.visible = False
        self.floater.content = None
        self.flow.opacity = 1
        self.visual.controls = []
        self.visual_host.visible = False
        self._paint(self.flow, self.visual, self.visual_host, self.floater)

    def _show_visual(self) -> None:
        """Abre o vao numa copia. O flow dos detectores nao muda de ordem."""
        controls: list[ft.Control] = []
        for kind, key in layout_slots(self.keys, self.key, self.index):
            if kind == "gap":
                controls.append(self._gap())
                continue
            controls.append(self._visual_card(key))
        self.visual.controls = controls
        self.visual_host.visible = True
        self.flow.opacity = 0

    def _visual_card(self, key: str) -> ft.Control:
        return ft.Container(
            width=self.card_w if self.axis == "grid" else None,
            height=self.card_h,
            border_radius=12,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=self.build_card(key),
        )

    def _gap(self) -> ft.Control:
        return ft.Container(
            width=self.card_w if self.axis == "grid" else None,
            height=self.card_h,
            bgcolor=config.COLOR_BG,
            border=ft.Border.all(2, config.COLOR_ACCENT),
            border_radius=12,
            data=_GAP,
        )

    def _paint(self, *controls: ft.Control) -> None:
        for control in controls:
            update = getattr(control, "update", None)
            if not callable(update):
                continue
            try:
                update()
            except Exception:
                continue

    def _clear_press(self) -> None:
        self.key = None
        self.down_at = None
        self.armed = False

    def _cancel_timer(self) -> None:
        timer = self._timer
        self._timer = None
        if timer is not None:
            timer.cancel()

    def _timer_fired(self, gen: int) -> None:
        if gen != self._gen or self._settled:
            return

        def arm() -> None:
            if gen != self._gen or self._settled or self.down_at is None:
                return
            self.advance(self.down_at + HOLD_SECONDS)

        run = getattr(self.page, "run_task", None)
        if callable(run):
            try:
                run(self._arm_async)
                return
            except Exception:
                pass
        arm()

    async def _arm_async(self) -> None:
        if self.down_at is None:
            return
        self.advance(self.down_at + HOLD_SECONDS)

    def _card_down(self, key: str, e) -> None:
        local_x, local_y = _xy(e, 0.0, 0.0)
        origin_x, origin_y = self._origin_of(key)
        global_x, global_y = _global(e, local_x, local_y)
        self._anchor_x = origin_x + local_x
        self._anchor_y = origin_y + local_y
        self._global_x = global_x
        self._global_y = global_y
        self.press(key, time.monotonic(), self._anchor_x, self._anchor_y)

    def _card_pan(self, key: str, e) -> None:
        if self.key != key:
            return
        global_x, global_y = _global(e, self._global_x, self._global_y)
        self.move(
            self._anchor_x + (global_x - self._global_x),
            self._anchor_y + (global_y - self._global_y),
        )

    def _card_up(self, key: str, e) -> None:
        if self.key != key and self.key is not None:
            return
        self._card_pan(key, e)
        self.release(time.monotonic(), self.x, self.y)

    def _card_pan_cancel(self, key: str) -> None:
        """O ponteiro soltou sem pan, ou o gesto caiu. Nao deixa o cartao no ar."""
        if self.key != key:
            return
        self.release(time.monotonic(), self.x, self.y)

    def _origin_of(self, key: str) -> tuple[float, float]:
        index = self.keys.index(key) if key in self.keys else 0
        if self.axis == "grid":
            col = index % self.columns
            row = index // self.columns
            return col * (self.card_w + self.spacing_x), row * (self.card_h + self.spacing_y)
        return 0.0, index * (self.card_h + self.spacing_y)

    def _resized(self, e) -> None:
        if self.axis != "grid":
            width = float(getattr(e, "width", 0) or 0)
            if width > 0:
                self.card_w = width
            return
        width = float(getattr(e, "width", 0) or 0)
        stride = self.card_w + self.spacing_x
        if width <= 0 or stride <= 0:
            return
        columns = max(1, int((width + self.spacing_x) // stride))
        if columns != self.columns:
            self.columns = columns


def _xy(event: Any, fallback_x: float, fallback_y: float) -> tuple[float, float]:
    local = getattr(event, "local_position", None)
    if local is None:
        return fallback_x, fallback_y
    return float(getattr(local, "x", fallback_x)), float(getattr(local, "y", fallback_y))


def _global(event: Any, fallback_x: float, fallback_y: float) -> tuple[float, float]:
    point = getattr(event, "global_position", None)
    if point is None:
        return fallback_x, fallback_y
    return float(getattr(point, "x", fallback_x)), float(getattr(point, "y", fallback_y))
