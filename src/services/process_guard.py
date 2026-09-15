"""Detecta e encerra processos de apps do catalogo ja abertos (mesmo fora desta sessao)."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def snapshot_processes() -> list[tuple[int, str, str]]:
    """Lista (pid, executable_path, command_line). Ignora o proprio hub."""
    me = os.getpid()
    if sys.platform.startswith("win"):
        rows = _win_snapshot()
    else:
        rows = _posix_snapshot()
    return [(pid, exe, cmd) for pid, exe, cmd in rows if pid and pid != me]


def pids_for_file(path: str | Path, snapshot: list[tuple[int, str, str]] | None = None) -> list[int]:
    """PIDs cujo executavel ou linha de comando apontam para o arquivo do app."""
    target = Path(path)
    try:
        target = target.resolve()
    except OSError:
        target = Path(path)
    if not str(target):
        return []
    rows = snapshot if snapshot is not None else snapshot_processes()
    wanted = str(target)
    wanted_l = wanted.lower()
    name_l = target.name.lower()
    found: list[int] = []
    for pid, exe, cmd in rows:
        exe_l = (exe or "").lower()
        cmd_l = (cmd or "").lower()
        if exe_l and _same_path(exe_l, wanted_l):
            found.append(pid)
            continue
        if cmd_l and wanted_l in cmd_l:
            found.append(pid)
            continue
        parent_l = target.parent.name.lower()
        if (
            name_l
            and parent_l
            and name_l in cmd_l
            and parent_l in cmd_l
        ):
            found.append(pid)
    return list(dict.fromkeys(found))


def running_catalog_map(
    paths_by_app_id: dict[str, str],
    snapshot: list[tuple[int, str, str]] | None = None,
) -> dict[str, list[int]]:
    rows = snapshot if snapshot is not None else snapshot_processes()
    out: dict[str, list[int]] = {}
    for app_id, path in paths_by_app_id.items():
        if not path:
            continue
        pids = pids_for_file(path, rows)
        if pids:
            out[app_id] = pids
    return out


def terminate_pids(pids: list[int], timeout_s: float = 8.0) -> str:
    """Encerra PIDs (nao o hub). Retorna erro curto ou vazio."""
    me = os.getpid()
    targets = [int(p) for p in pids if int(p) > 0 and int(p) != me]
    if not targets:
        return ""
    try:
        if sys.platform.startswith("win"):
            for pid in targets:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline and _any_alive(targets):
                time.sleep(0.3)
            if _any_alive(targets):
                for pid in targets:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                time.sleep(0.4)
        else:
            for pid in targets:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline and _any_alive(targets):
                time.sleep(0.2)
            for pid in targets:
                if _pid_alive(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
    except OSError as exc:
        return f"Nao foi possivel encerrar o processo: {exc}"
    if _any_alive(targets):
        return "Nao foi possivel encerrar o aplicativo em execucao."
    return ""


def _any_alive(pids: list[int]) -> bool:
    return any(_pid_alive(p) for p in pids)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            out = (result.stdout or "").strip().lower()
            if "no tasks" in out or not out:
                return False
            return str(pid) in out
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _same_path(a: str, b: str) -> bool:
    left = a.replace("/", "\\").rstrip("\\")
    right = b.replace("/", "\\").rstrip("\\")
    return left == right


def _win_snapshot() -> list[tuple[int, str, str]]:
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId, ExecutablePath, CommandLine | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    raw = (result.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    rows: list[tuple[int, str, str]] = []
    if not isinstance(data, list):
        return rows
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item.get("ProcessId") or 0)
        except (TypeError, ValueError):
            continue
        exe = str(item.get("ExecutablePath") or "")
        cmd = str(item.get("CommandLine") or "")
        rows.append((pid, exe, cmd))
    return rows


def _posix_snapshot() -> list[tuple[int, str, str]]:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return []
    rows: list[tuple[int, str, str]] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        exe = ""
        try:
            exe = str((entry / "exe").resolve())
        except OSError:
            pass
        cmd = ""
        try:
            cmd = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(
                "utf-8", errors="replace"
            )
        except OSError:
            pass
        rows.append((pid, exe, cmd))
    return rows
