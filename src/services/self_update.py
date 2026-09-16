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

# SRC = download interno; DST = exe em uso (nome padrao). Limpa extras no fim.
_UPDATER_CMD = r"""@echo off
setlocal EnableExtensions
set "PID=%~1"
set "SRC=%~2"
set "DST=%~3"
set "UPDATES=%~4"
set "WORKDIR=%~dp3"
:wait
tasklist /FI "PID eq %PID%" | findstr /I /C:" %PID% " >nul
if not errorlevel 1 (
  ping 127.0.0.1 -n 2 >nul
  goto wait
)
ping 127.0.0.1 -n 4 >nul
if exist "%DST%.old" del /F /Q "%DST%.old" >nul 2>&1
if exist "%DST%.bak" del /F /Q "%DST%.bak" >nul 2>&1
if exist "%DST%" move /Y "%DST%" "%DST%.old" >nul 2>&1
copy /Y "%SRC%" "%DST%" >nul
if not exist "%DST%" (
  if exist "%DST%.old" move /Y "%DST%.old" "%DST%" >nul 2>&1
)
set "_MEIPASS2="
set "_PYI_APPLICATION_HOME_DIR="
set "_PYI_ARCHIVE_FILE="
set "_PYI_PARENT_PROCESS_LEVEL="
set "PYTHONHOME="
set "PYTHONPATH="
if exist "%DST%" start "" /D "%WORKDIR%" "%DST%"
if exist "%DST%.old" del /F /Q "%DST%.old" >nul 2>&1
if exist "%DST%.bak" del /F /Q "%DST%.bak" >nul 2>&1
del /F /Q "%~dp3*.new.exe" >nul 2>&1
del /F /Q "%~dp3*.bak" >nul 2>&1
if not "%UPDATES%"=="" (
  if exist "%UPDATES%" (
    del /F /Q "%UPDATES%\*.*" >nul 2>&1
    rmdir /S /Q "%UPDATES%" >nul 2>&1
  )
)
if exist "%SRC%" (
  if /I not "%SRC%"=="%DST%" del /F /Q "%SRC%" >nul 2>&1
)
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


def can_replace_running() -> bool:
    return sys.platform.startswith("win") and bool(getattr(sys, "frozen", False))


def running_exe() -> Path | None:
    if not can_replace_running():
        return None
    return Path(sys.executable).resolve()


def _safe_unlink(path: Path) -> None:
    try:
        if path.is_file() or path.is_symlink():
            path.unlink()
    except OSError:
        pass


def cleanup_update_artifacts(*, keep: Path | None = None) -> None:
    """Remove *.new.exe / *.bak / *.old ao lado do hub e o conteudo de updates/."""
    keep_res: Path | None = None
    if keep is not None:
        try:
            keep_res = keep.resolve()
        except OSError:
            keep_res = keep

    dest = running_exe()
    if dest is not None:
        parent = dest.parent
        _safe_unlink(Path(str(dest) + ".old"))
        _safe_unlink(Path(str(dest) + ".bak"))
        stem = dest.stem
        for pattern in ("*.new.exe", "*.bak"):
            for path in parent.glob(pattern):
                try:
                    resolved = path.resolve()
                except OSError:
                    resolved = path
                if keep_res is not None and resolved == keep_res:
                    continue
                if resolved == dest:
                    continue
                _safe_unlink(path)
        extra = parent / f"{stem}.new.exe"
        if extra != dest:
            _safe_unlink(extra)

    folder = config.USER_DATA_DIR / "updates"
    if folder.exists():
        try:
            for path in folder.iterdir():
                try:
                    resolved = path.resolve()
                except OSError:
                    resolved = path
                if keep_res is not None and resolved == keep_res:
                    continue
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    _safe_unlink(path)
            leftover = [p for p in folder.iterdir()]
            if not leftover:
                folder.rmdir()
        except OSError:
            shutil.rmtree(folder, ignore_errors=True)


def spawn_replace_and_relaunch(new_exe: Path) -> str:
    """Agenda .cmd: espera o PID, substitui o exe pelo nome padrao, limpa extras.

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
    dest = dest.parent / saved_exe_filename()

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
        updates = str((config.USER_DATA_DIR / "updates").resolve())
        subprocess.Popen(
            [
                "cmd.exe",
                "/d",
                "/c",
                helper,
                str(os.getpid()),
                str(src),
                str(dest),
                updates,
            ],
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
