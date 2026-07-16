"""Execucao/abertura dos arquivos baixados."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class RunError(Exception):
    pass


def run_file(path: str | Path) -> None:
    """Executa (.exe) ou abre (.xlsx / .xlsm e outros) o arquivo informado.

    No Windows usa ``os.startfile`` (respeita o programa associado, ex.: Excel).
    Em outros sistemas usa o abridor padrao do SO.
    """
    p = Path(path)
    if not p.exists():
        raise RunError(f"Arquivo nao encontrado: {p}")

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception as exc:
        raise RunError(f"Nao foi possivel executar/abrir o arquivo: {exc}") from exc
