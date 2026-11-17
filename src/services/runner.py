"""Execucao/abertura dos arquivos baixados."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class RunError(Exception):
    pass


@dataclass
class RunningApp:
    """Processo de um app do catalogo (nao confundir com a bandeja do hub)."""

    app_id: str
    app_name: str
    popen: subprocess.Popen

    def is_running(self) -> bool:
        return self.popen.poll() is None

    def wait(self) -> int:
        return int(self.popen.wait())


def launch_file(
    path: str | Path,
    *,
    app_id: str = "",
    app_name: str = "",
) -> RunningApp:
    """Abre o arquivo e devolve o processo para a UI acompanhar."""
    p = Path(path)
    if not p.exists():
        raise RunError(f"Arquivo nao encontrado: {p}")

    try:
        if sys.platform.startswith("win"):
            if p.suffix.lower() == ".exe":
                popen = subprocess.Popen(
                    [str(p)],
                    cwd=str(p.parent),
                )
            else:
                # start /wait: fica vivo enquanto o app associado estiver aberto
                popen = subprocess.Popen(
                    ["cmd.exe", "/c", "start", "/wait", "", str(p)],
                    cwd=str(p.parent),
                )
        elif sys.platform == "darwin":
            popen = subprocess.Popen(["open", str(p)])
        else:
            popen = subprocess.Popen(["xdg-open", str(p)])
    except Exception as exc:
        raise RunError(f"Nao foi possivel executar/abrir o arquivo: {exc}") from exc

    return RunningApp(app_id=app_id, app_name=app_name or p.name, popen=popen)


def run_file(path: str | Path) -> None:
    """Compat: dispara a abertura sem rastrear o processo."""
    launch_file(path)
