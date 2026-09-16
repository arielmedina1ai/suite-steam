"""Helpers de barra de progresso (percentual visivel, sem fingir 100% cedo)."""
from __future__ import annotations


def bar_value(pct: float | None) -> float | None:
    """None = indeterminado. pct < 0 tambem e indeterminado."""
    if pct is None or pct < 0:
        return None
    return min(max(float(pct), 0.0), 1.0)


def label(pct: float | None, msg: str) -> str:
    text = (msg or "").strip()
    if pct is None or pct < 0:
        return text
    pct_i = int(round(min(max(float(pct), 0.0), 1.0) * 100))
    if text:
        return f"{pct_i}%  {text}"
    return f"{pct_i}%"
