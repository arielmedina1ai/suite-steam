"""Tela de feedback do aplicativo. Ocupa o lugar da tela do app, como o tutorial."""
from __future__ import annotations

from collections.abc import Callable

import flet as ft

import config
from models import AppInfo


class FeedbackView:
    def __init__(
        self,
        page: ft.Page,
        app: AppInfo,
        on_back: Callable[[], None],
        on_submit: Callable[[str], str],
        introducao: str = "",
    ) -> None:
        self.page = page
        self.app = app
        self.on_back = on_back
        self.on_submit = on_submit
        self._busy = False
        self._sent = False
        self.introducao = introducao or ""
        self.guide_text = ft.Text(
            self.introducao.strip(),
            size=15,
            color="#D6E5DC",
        )
        self.guide_card = _feedback_card(self.guide_text)
        self.guide_card.visible = bool(self.introducao.strip())
        self.field = ft.TextField(
            multiline=True,
            min_lines=6,
            max_lines=12,
            autofocus=True,
            text_size=15,
            color=config.COLOR_TEXT,
            bgcolor=config.COLOR_SURFACE,
            border_color="#2C4036",
            cursor_color=config.COLOR_ACCENT,
            focused_border_color=config.COLOR_ACCENT,
        )
        self.field_card = _feedback_card(self.field)
        self.send_button = ft.FilledButton(
            "Enviar",
            icon=ft.Icons.SEND,
            style=ft.ButtonStyle(bgcolor=config.COLOR_PRIMARY, color="white"),
            on_click=self._on_send,
        )
        self.error_text = ft.Text("", size=13, color="#E07A7A", visible=False)
        self.sent_text = ft.Text(
            "Feedback enviado.",
            size=16,
            color=config.COLOR_TEXT,
            visible=False,
        )
        self.ok_button = ft.FilledButton(
            "OK",
            visible=False,
            style=ft.ButtonStyle(bgcolor=config.COLOR_PRIMARY, color="white"),
            on_click=self._on_ok,
        )
        self.back_button = ft.OutlinedButton(
            "Voltar",
            icon=ft.Icons.ARROW_BACK,
            on_click=self._on_back,
        )

    def build(self) -> ft.Control:
        return ft.Column(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=16,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(
                            f"Feedback de {self.app.nome}",
                            size=22,
                            weight=ft.FontWeight.BOLD,
                            color=config.COLOR_TEXT,
                            expand=True,
                        ),
                        self.back_button,
                    ],
                ),
                self.guide_card,
                self.field_card,
                self.send_button,
                self.error_text,
                self.sent_text,
                self.ok_button,
            ],
        )

    def _on_back(self, _e=None) -> None:
        if self._busy:
            return
        self.on_back()

    def _on_ok(self, _e=None) -> None:
        if self._busy or not self._sent:
            return
        self.on_back()

    def _on_send(self, _e=None) -> None:
        if self._busy or self._sent:
            return
        text = self.field.value or ""
        if not text.strip():
            self._show_error("Escreva o feedback.")
            return
        self._busy = True
        self.send_button.disabled = True
        self.back_button.disabled = True
        self.error_text.visible = False
        self.error_text.value = ""
        self._safe_update()
        self.page.run_thread(lambda: self._send_worker(text))

    def _send_worker(self, text: str) -> None:
        try:
            message = self.on_submit(text) or ""
        except Exception:
            message = "Nao foi possivel enviar."
        if message:
            self.field.value = text
            self._busy = False
            self.send_button.disabled = False
            self.back_button.disabled = False
            self._show_error(message)
            return
        self._busy = False
        self._show_sent()

    def _show_error(self, message: str) -> None:
        self.error_text.value = message
        self.error_text.visible = True
        self.sent_text.visible = False
        self.ok_button.visible = False
        self._safe_update()

    def _show_sent(self) -> None:
        self._sent = True
        self.field.visible = False
        self.field_card.visible = False
        self.send_button.visible = False
        self.error_text.visible = False
        self.error_text.value = ""
        self.sent_text.visible = True
        self.ok_button.visible = True
        self.back_button.disabled = False
        self.guide_card.visible = False
        self._safe_update()

    def set_introducao(self, text: str, *, refresh: bool = True) -> None:
        self.introducao = text or ""
        shown = self.introducao.strip()
        self.guide_text.value = shown
        self.guide_card.visible = bool(shown) and not self._sent
        if refresh:
            self._safe_update()

    def _safe_update(self) -> None:
        try:
            self.page.update()
        except Exception:
            pass


def _feedback_card(content: ft.Control) -> ft.Container:
    return ft.Container(
        bgcolor=config.COLOR_SURFACE,
        border=ft.Border.all(1, "#2C4036"),
        border_radius=12,
        padding=16,
        content=content,
    )
