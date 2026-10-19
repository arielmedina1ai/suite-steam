"""Segurar o cartao e arrastar, sem o fantasma do Draggable.

O Flet 0.85 nao espera no Draggable nem abre um vao na secao.
O gesto fica no ponteiro: timer no pressionar, arraste depois.
O mouse por cima fica no cartao, nao neste detector.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import flet as ft

import config
from services.favorites import HOLD_SECONDS, grid_insertion_index, layout_slots

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
        self.flow: ft.Control
        if axis == "grid":
            self.flow = ft.Row(wrap=True, spacing=spacing_x, run_spacing=spacing_y)
        else:
            self.flow = ft.Column(
                spacing=spacing_y,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            )
        self.floater = ft.Container(
            visible=False,
            data=_FLOAT,
            left=0,
            top=0,
            width=self.card_w,
            height=self.card_h,
            scale=1.04,
            border_radius=12,
            shadow=ft.BoxShadow(
                blur_radius=18,
                color="#66000000",
                offset=ft.Offset(0, 8),
            ),
        )
        self.stack = ft.Stack(
            controls=[self.flow, self.floater],
            clip_behavior=ft.ClipBehavior.NONE,
        )
        self.gesture = ft.GestureDetector(
            content=self.stack,
            on_tap_down=self._tap_down,
            on_tap_up=self._tap_up,
            on_tap_cancel=self._tap_cancel,
            on_tap_move=self._tap_move,
            on_pan_update=self._pan_update,
            on_pan_end=self._pan_end,
            on_pan_cancel=self._tap_cancel,
            on_size_change=self._resized,
        )
        self._show_idle()

    def control(self) -> ft.Control:
        return self.gesture

    def cancel_press(self) -> None:
        """A estrela levou o clique: nao abre e nao continua o arraste."""
        self._settled = True
        self._cancel_timer()
        self._gen += 1
        if self.armed:
            self._show_idle()
        self._clear_press()

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
        self.index = self.index_at(self.x, self.y)
        self._place_floater()
        self._fill(dragging=self.key, index=self.index)
        self._paint()
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
        self._fill(dragging=self.key, index=self.index)
        self._paint()

    def _place_floater(self) -> None:
        self.floater.left = self.x - self.card_w / 2.0
        self.floater.top = self.y - self.card_h / 2.0

    def _show_idle(self) -> None:
        self.floater.visible = False
        self.floater.content = None
        self._fill(dragging=None, index=None)
        self._paint()

    def _fill(self, *, dragging: str | None, index: int | None) -> None:
        controls: list[ft.Control] = []
        for kind, key in layout_slots(self.keys, dragging, index):
            if kind == "gap":
                controls.append(self._gap())
            else:
                controls.append(self.build_card(key))
        self.flow.controls = controls

    def _gap(self) -> ft.Control:
        return ft.Container(
            width=self.card_w,
            height=self.card_h,
            border=ft.Border.all(2, config.COLOR_ACCENT),
            border_radius=12,
            data=_GAP,
        )

    def _paint(self) -> None:
        for control in (self.flow, self.floater, self.stack):
            update = getattr(control, "update", None)
            if not callable(update):
                continue
            try:
                update()
            except Exception:
                return

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

    def _tap_down(self, e) -> None:
        x, y = _xy(e, self.x, self.y)
        index = self.index_at(x, y)
        if index < 0 or index >= len(self.keys):
            return
        self.press(self.keys[index], time.monotonic(), x, y)

    def _tap_move(self, e) -> None:
        self.move(*_xy(e, self.x, self.y))

    def _pan_update(self, e) -> None:
        self.move(*_xy(e, self.x, self.y))

    def _tap_up(self, e) -> None:
        x, y = _xy(e, self.x, self.y)
        self.release(time.monotonic(), x, y)

    def _pan_end(self, e) -> None:
        self.release(time.monotonic())

    def _tap_cancel(self, _e=None) -> None:
        if self.armed:
            return
        self._cancel_timer()
        self._gen += 1

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
