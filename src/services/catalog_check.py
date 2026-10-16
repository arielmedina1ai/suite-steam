"""Quando a checagem automatica do catalogo deve rodar.

Uma vez por dia em America/Sao_Paulo (Brasilia), as 10:00 desse fuso.
Nao usa o fuso do Windows nem UTC. So dispara se o processo ja estava
aberto antes das 10:00 e continua aberto quando o relogio chega nesse
horario (ou passa dele, por exemplo apos suspensao). Abrir as 10:00 ou
depois grava o dia e nao sincroniza: a abertura ja baixou o catalogo.
Nao repete no mesmo dia de Sao Paulo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

ZONE_NAME = "America/Sao_Paulo"
CHECK_HOUR = 10
CHECK_MINUTE = 0
# Fatia maxima de espera para notar relogio, suspensao do PC ou saida do app.
WAIT_SLICE_SECONDS = 15.0
# Ultimo recurso, sem transicoes de horario de verao. Brasilia e UTC-3 o ano todo
# desde 2019; o banco America/Sao_Paulo e o caminho normal.
_FIXED_BRT = timezone(timedelta(hours=-3))

_resolved: tuple[tzinfo, str] | None = None


class ZoneUnavailable(Exception):
    """America/Sao_Paulo nao pode ser lido do zoneinfo."""


def reset_zone_cache() -> None:
    global _resolved
    _resolved = None


def _system_has_zone(name: str) -> bool:
    """True se o banco de fusos do sistema tem o arquivo dessa zona."""
    try:
        from zoneinfo import TZPATH
    except ImportError:
        return False
    parts = name.split("/")
    for root in TZPATH:
        if Path(root).joinpath(*parts).is_file():
            return True
    return False


def _tzdata_package_available() -> bool:
    try:
        import tzdata  # noqa: F401
    except ImportError:
        return False
    return True


def _zone_from_zoneinfo() -> tzinfo:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return ZoneInfo(ZONE_NAME)
    except ZoneInfoNotFoundError as exc:
        raise ZoneUnavailable(str(exc)) from exc
    except ModuleNotFoundError as exc:
        raise ZoneUnavailable(str(exc)) from exc


def _load_zone() -> tuple[tzinfo, str]:
    """(zona, origem). Origem: ``system``, ``tzdata`` ou ``fixed-brt``."""
    if _system_has_zone(ZONE_NAME):
        try:
            return _zone_from_zoneinfo(), "system"
        except ZoneUnavailable:
            pass
    if _tzdata_package_available():
        try:
            return _zone_from_zoneinfo(), "tzdata"
        except ZoneUnavailable:
            pass
    return _FIXED_BRT, "fixed-brt"


def resolve_sao_paulo_zone() -> tuple[tzinfo, str]:
    """Zona America/Sao_Paulo e de onde ela veio.

    ``system``: arquivo do sistema (``TZPATH``).
    ``tzdata``: pacote PyPI ``tzdata`` (o que o Windows e o .exe usam).
    ``fixed-brt``: UTC-3 fixo, so se os dois bancos faltarem.
    """
    global _resolved
    if _resolved is None:
        _resolved = _load_zone()
    return _resolved


def sao_paulo_zone() -> tzinfo:
    return resolve_sao_paulo_zone()[0]


def zone_source() -> str:
    return resolve_sao_paulo_zone()[1]


def sao_paulo_now() -> datetime:
    """Agora em America/Sao_Paulo, independente do fuso do Windows."""
    return datetime.now(sao_paulo_zone())


def as_sao_paulo(now: datetime) -> datetime:
    """Instante em America/Sao_Paulo.

    Datetime sem fuso e tratado como relogio de parede ja em Sao Paulo
    (testes e chamadas que montam 10:00). Nao e o fuso do sistema.
    Datetime com fuso e convertido.
    """
    zone = sao_paulo_zone()
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def local_day(now: datetime) -> str:
    """Data ``YYYY-MM-DD`` no calendario de America/Sao_Paulo."""
    return as_sao_paulo(now).date().isoformat()


def already_checked_today(last_day: str, now: datetime) -> bool:
    return (last_day or "").strip() == local_day(now)


def auto_check_day_on_open(now: datetime) -> str:
    """Dia ``YYYY-MM-DD`` a gravar na abertura, ou vazio antes das 10:00.

    Abrir as 10:00:00 ou depois em America/Sao_Paulo nao dispara a
    sincronizacao das 10:00: a abertura ja baixou o catalogo. O dia fica
    marcado para nao repetir. Quem abriu antes devolve vazio e sincroniza
    uma vez quando o relogio cruzar 10:00 com o processo ainda aberto.
    """
    now_sp = as_sao_paulo(now)
    slot = now_sp.replace(
        hour=CHECK_HOUR,
        minute=CHECK_MINUTE,
        second=0,
        microsecond=0,
    )
    if now_sp >= slot:
        return now_sp.date().isoformat()
    return ""


def next_auto_check_at(last_day: str, now: datetime) -> datetime:
    """Proximo instante em America/Sao_Paulo.

    Dia ainda nao marcado e antes das 10:00: hoje as 10:00.
    Dia ainda nao marcado e ja passou das 10:00: agora. Vale para o
    processo que ja estava aberto quando o relogio cruzou (ou voltou da
    suspensao depois das 10:00). Abrir nesse horario grava o dia antes
    e nao consulta este caminho.
    Dia ja marcado: amanha as 10:00.
    """
    now = as_sao_paulo(now)
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
    now_sp = as_sao_paulo(now)
    delta = (next_auto_check_at(last_day, now_sp) - now_sp).total_seconds()
    if delta <= 0:
        return 0.0
    return delta


def catalog_check_is_due(last_day: str, now: datetime) -> bool:
    """True se o processo ja aberto deve sincronizar agora.

    O relogio de Sao Paulo chegou as 10:00 deste dia e o dia ainda nao
    foi gravado. A abertura as 10:00 ou depois grava o dia antes, entao
    isto fica falso e nao ha sincronizacao extra.
    """
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
