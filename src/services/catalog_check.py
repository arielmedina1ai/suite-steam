"""Quando a checagem automatica do catalogo deve rodar.

Uma vez por dia local, as 10:00. Se o processo nao estava aberto nesse
horario, a mesma checagem fica devida na proxima abertura (depois das 10:00).
Nao repete no mesmo dia local.
"""
from __future__ import annotations

from datetime import datetime, timedelta

CHECK_HOUR = 10
CHECK_MINUTE = 0
# Fatia maxima de espera para notar relogio, suspensao do PC ou saida do app.
WAIT_SLICE_SECONDS = 15.0


def local_day(now: datetime) -> str:
    """Data local ``YYYY-MM-DD`` (sem fuso: ``datetime.now()`` ja e local)."""
    return now.date().isoformat()


def already_checked_today(last_day: str, now: datetime) -> bool:
    return (last_day or "").strip() == local_day(now)


def next_auto_check_at(last_day: str, now: datetime) -> datetime:
    """Proximo instante local da checagem.

    Dia ainda nao checado e ja passou das 10:00: agora (recuperacao).
    Dia ainda nao checado e antes das 10:00: hoje as 10:00.
    Dia ja checado: amanha as 10:00.
    """
    slot = now.replace(
        hour=CHECK_HOUR,
        minute=CHECK_MINUTE,
        second=0,
        microsecond=0,
    )
    if already_checked_today(last_day, now):
        return slot + timedelta(days=1)
    if now >= slot:
        return now
    return slot


def seconds_until_auto_check(last_day: str, now: datetime) -> float:
    delta = (next_auto_check_at(last_day, now) - now).total_seconds()
    if delta <= 0:
        return 0.0
    return delta


def catalog_check_is_due(last_day: str, now: datetime) -> bool:
    """True se esta hora local pede a checagem e o dia ainda nao foi gravado."""
    if already_checked_today(last_day, now):
        return False
    return seconds_until_auto_check(last_day, now) == 0.0


def window_shows_catalog_notice(window: object | None) -> bool:
    """Linha breve so com a janela na tela.

    Minimizada (barra de tarefas) e bandeja continuam com o processo — a
    checagem roda — mas a frase some antes de a pessoa ver, entao nao pinta.
    """
    if window is None:
        return True
    if not bool(getattr(window, "visible", True)):
        return False
    if bool(getattr(window, "minimized", False)):
        return False
    return True
