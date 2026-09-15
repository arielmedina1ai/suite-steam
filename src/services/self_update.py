"""Download e troca do .exe em execucao (Windows empacotado)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import config


def updates_dir() -> Path:
    path = config.USER_DATA_DIR / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def saved_exe_filename() -> str:
    """Nome padrao do .exe (sem sufixo de versao)."""
    if bool(getattr(sys, "frozen", False)):
        name = Path(sys.executable).name
        if name.lower().endswith(".exe") and name[:-4].strip():
            return name
    return f"{config.EXE_NAME}.exe"


def can_replace_running() -> bool:
    return sys.platform.startswith("win") and bool(getattr(sys, "frozen", False))


def running_exe() -> Path | None:
    if not can_replace_running():
        return None
    return Path(sys.executable).resolve()


def spawn_replace_and_relaunch(new_exe: Path) -> str:
    """Agenda troca do exe atual apos este processo sair, e relanca.

    Nao mexe em settings.json ao lado do exe.
    Retorna mensagem de erro curta, ou vazio se o helper foi disparado.
    """
    dest = running_exe()
    src = Path(new_exe)
    if dest is None:
        return "Troca automatica so funciona no .exe empacotado no Windows."
    if not src.exists():
        return "Arquivo da nova versao nao encontrado."

    script = """
param(
    [int]$TargetPid,
    [string]$Src,
    [string]$Dst
)
$ErrorActionPreference = "Continue"
for ($i = 0; $i -lt 180; $i++) {
    $alive = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if (-not $alive) { break }
    Start-Sleep -Milliseconds 400
}
$old = "$Dst.old"
if (Test-Path -LiteralPath $Dst) {
    try { Move-Item -LiteralPath $Dst -Destination $old -Force } catch {}
}
Copy-Item -LiteralPath $Src -Destination $Dst -Force
if (-not (Test-Path -LiteralPath $Dst)) {
    exit 1
}
Start-Process -FilePath $Dst
if (Test-Path -LiteralPath $old) {
    try { Remove-Item -LiteralPath $old -Force } catch {}
}
"""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".ps1",
            delete=False,
            encoding="utf-8-sig",
        ) as tmp:
            tmp.write(script)
            helper = tmp.name
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                helper,
                "-TargetPid",
                str(os.getpid()),
                "-Src",
                str(src.resolve()),
                "-Dst",
                str(dest),
            ],
            close_fds=True,
        )
    except OSError as exc:
        return f"Nao foi possivel iniciar a troca do executavel: {exc}"
    return ""
