"""Download e troca do .exe em execucao (Windows empacotado, PyInstaller onefile).

Nao lanca um segundo binario congelado como atualizador: um .cmd (cmd.exe)
espera o PID sair, troca o arquivo e so entao inicia o exe novo.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import config
from services.sharepoint_manager import parsear_link_sharepoint

_PYI_ENV_KEYS = (
    "_MEIPASS2",
    "_PYI_APPLICATION_HOME_DIR",
    "_PYI_ARCHIVE_FILE",
    "_PYI_PARENT_PROCESS_LEVEL",
    "_PYI_LINUX_PROCESS_NAME",
    "PYTHONHOME",
    "PYTHONPATH",
)

_UPDATER_CMD = r"""@echo off
setlocal EnableExtensions
set "PID=%~1"
set "SRC=%~2"
set "DST=%~3"
set "WORKDIR=%~dp3"
:wait
tasklist /FI "PID eq %PID%" | findstr /I /C:" %PID% " >nul
if not errorlevel 1 (
  ping 127.0.0.1 -n 2 >nul
  goto wait
)
ping 127.0.0.1 -n 4 >nul
if exist "%DST%.old" del /F /Q "%DST%.old" >nul 2>&1
if exist "%DST%" move /Y "%DST%" "%DST%.old" >nul 2>&1
copy /Y "%SRC%" "%DST%" >nul
if not exist "%DST%" exit /B 1
set "_MEIPASS2="
set "_PYI_APPLICATION_HOME_DIR="
set "_PYI_ARCHIVE_FILE="
set "_PYI_PARENT_PROCESS_LEVEL="
set "PYTHONHOME="
set "PYTHONPATH="
start "" /D "%WORKDIR%" "%DST%"
if exist "%DST%.old" del /F /Q "%DST%.old" >nul 2>&1
del "%~f0" >nul 2>&1
"""


def updates_dir() -> Path:
    path = config.USER_DATA_DIR / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def saved_exe_filename() -> str:
    """Nome padrao do .exe instalado (sem sufixo de versao). So local."""
    if bool(getattr(sys, "frozen", False)):
        name = Path(sys.executable).name
        if name.lower().endswith(".exe") and name[:-4].strip():
            return name
    return f"{config.EXE_NAME}.exe"


def catalog_remote_filename(download_url: str) -> str | None:
    """Nome do objeto no SharePoint, como no link do catalogo. Nao inventa *.new.exe."""
    raw = (download_url or "").strip()
    if not raw:
        return None
    try:
        info = parsear_link_sharepoint(raw)
        nome = info.get("nome_arquivo")
        if nome:
            leaf = Path(str(nome).replace("\\", "/")).name
            if leaf and leaf not in {".", ".."}:
                return leaf
    except ValueError:
        pass
    leaf = unquote(Path(urlparse(raw).path).name)
    leaf = leaf.split("?")[0].strip()
    if leaf.lower() in {"", "download.aspx", "download"}:
        return None
    if leaf in {".", ".."}:
        return None
    return leaf


def staging_exe_path() -> Path:
    """Temporario local irmao do exe em execucao (*.new.exe). Nao e nome remoto."""
    name = saved_exe_filename()
    if name.lower().endswith(".exe"):
        staged = name[:-4] + ".new.exe"
    else:
        staged = name + ".new.exe"
    running = running_exe()
    if running is not None:
        return running.parent / staged
    return updates_dir() / staged


def stage_downloaded_exe(downloaded: Path) -> Path:
    """Copia bytes ja baixados para o staging local. Nao mexe no SharePoint."""
    src = Path(downloaded).resolve()
    staged = staging_exe_path()
    staged.parent.mkdir(parents=True, exist_ok=True)
    if src == staged.resolve():
        return staged
    shutil.copy2(src, staged)
    return staged


def can_replace_running() -> bool:
    return sys.platform.startswith("win") and bool(getattr(sys, "frozen", False))


def running_exe() -> Path | None:
    if not can_replace_running():
        return None
    return Path(sys.executable).resolve()


def spawn_replace_and_relaunch(new_exe: Path) -> str:
    """Agenda .cmd: espera o PID, substitui o exe, inicia o novo.

    Nao mexe em settings.json ao lado do exe.
    Nao dispara outro PyInstaller / python*.dll.
    Retorna mensagem de erro curta, ou vazio se o helper foi disparado.
    """
    dest = running_exe()
    src = Path(new_exe).resolve()
    if dest is None:
        return "Troca automatica so funciona no .exe empacotado no Windows."
    if not src.exists():
        return "Arquivo da nova versao nao encontrado."

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".cmd",
            delete=False,
            encoding="ascii",
            newline="\r\n",
        ) as tmp:
            tmp.write(_UPDATER_CMD)
            helper = tmp.name
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("_PYI") or key in _PYI_ENV_KEYS:
                env.pop(key, None)
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        subprocess.Popen(
            ["cmd.exe", "/d", "/c", helper, str(os.getpid()), str(src), str(dest)],
            cwd=str(dest.parent),
            env=env,
            close_fds=True,
            creationflags=flags,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return f"Nao foi possivel iniciar a troca do executavel: {exc}"
    return ""
