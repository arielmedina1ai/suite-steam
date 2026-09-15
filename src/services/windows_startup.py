"""Iniciar com o Windows (atalho na pasta Startup). Apenas Windows + .exe."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import config


def supported() -> bool:
    return sys.platform.startswith("win") and bool(getattr(sys, "frozen", False))


def shortcut_path() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    folder = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return folder / f"{config.EXE_NAME}.lnk"


def target_exe() -> Path | None:
    if not supported():
        return None
    return Path(sys.executable).resolve()


def is_registered() -> bool:
    return shortcut_path().exists()


def set_start_with_windows(enabled: bool) -> str:
    """Cria ou remove o atalho. Retorna mensagem de erro curta, ou vazio se ok."""
    if not sys.platform.startswith("win"):
        return ""
    if not bool(getattr(sys, "frozen", False)):
        return ""
    dest = shortcut_path()
    if not enabled:
        try:
            if dest.exists():
                dest.unlink()
        except OSError as exc:
            return f"Nao foi possivel desligar o inicio automatico: {exc}"
        return ""
    exe = target_exe()
    if exe is None or not exe.exists():
        return "Executavel nao encontrado para o inicio automatico."
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _ps_quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    ps = (
        "$s = New-Object -ComObject WScript.Shell; "
        f"$c = $s.CreateShortcut({_ps_quote(str(dest))}); "
        f"$c.TargetPath = {_ps_quote(str(exe))}; "
        f"$c.WorkingDirectory = {_ps_quote(str(exe.parent))}; "
        "$c.WindowStyle = 7; "
        "$c.Save()"
    )
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return f"Nao foi possivel ligar o inicio automatico: {exc}"
    if result.returncode != 0 or not dest.exists():
        err = (result.stderr or result.stdout or "").strip()
        return err[:180] or "Falha ao criar atalho de inicio com o Windows."
    return ""
