"""Detecta e encerra processos de apps do catalogo ja abertos (mesmo fora desta sessao).

No Windows usa a API nativa (sem PowerShell / sem janela de console).
"""
from __future__ import annotations

import os
import signal
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
    wanted_l = str(target).lower()
    name_l = target.name.lower()
    parent_l = target.parent.name.lower()
    suffix = target.suffix.lower()
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
        if name_l and parent_l and name_l in cmd_l and parent_l in cmd_l:
            found.append(pid)
    if found or suffix not in {".xlsx", ".xlsm", ".xls"} or not sys.platform.startswith("win"):
        return list(dict.fromkeys(found))
    # Planilhas: o processo e o Excel; consultar command line so desses PIDs
    for pid, exe, _cmd in rows:
        exe_l = (exe or "").lower()
        if "excel" not in exe_l:
            continue
        cmd_l = _win_command_line(pid).lower()
        if wanted_l in cmd_l or (name_l and parent_l and name_l in cmd_l and parent_l in cmd_l):
            found.append(pid)
    return list(dict.fromkeys(found))


def running_catalog_map(
    paths_by_app_id: dict[str, str],
    snapshot: list[tuple[int, str, str]] | None = None,
) -> dict[str, list[int]]:
    if not paths_by_app_id:
        return {}
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
            _win_terminate_tree(targets)
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline and _any_alive(targets):
                time.sleep(0.2)
            if _any_alive(targets):
                _win_terminate_tree(targets, force=True)
                time.sleep(0.3)
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
        return _win_pid_alive(pid)
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


# --- Windows (ctypes, sem PowerShell) ---------------------------------------

_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_VM_READ = 0x0010
_PROCESS_TERMINATE = 0x0001
_STILL_ACTIVE = 259
_ProcessCommandLineInformation = 60


def _win_pid_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return int(code.value) == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _win_terminate_tree(pids: list[int], force: bool = False) -> None:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    children = _win_descendants(pids)
    ordered = list(dict.fromkeys(list(reversed(children)) + list(pids)))
    for pid in ordered:
        handle = kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
        if not handle:
            continue
        try:
            kernel32.TerminateProcess(handle, 1)
        finally:
            kernel32.CloseHandle(handle)


def _win_descendants(roots: list[int]) -> list[int]:
    parent_of = {pid: ppid for pid, ppid in _win_pid_parents()}
    root_set = set(roots)
    out: list[int] = []
    changed = True
    while changed:
        changed = False
        for pid, ppid in parent_of.items():
            if pid in root_set or pid in out:
                continue
            if ppid in root_set or ppid in out:
                out.append(pid)
                changed = True
    return out


def _win_pid_parents() -> list[tuple[int, int]]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap in (0, wintypes.HANDLE(-1).value if hasattr(wintypes.HANDLE, "value") else -1):
        return []
    rows: list[tuple[int, int]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return rows


def _win_snapshot() -> list[tuple[int, str, str]]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    invalid = ctypes.c_void_p(-1).value
    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == invalid:
        return []

    rows: list[tuple[int, str, str]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = int(entry.th32ProcessID)
            exe = _win_image_path(kernel32, pid) or (entry.szExeFile or "")
            rows.append((pid, exe, ""))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return rows


def _win_image_path(kernel32, pid: int) -> str:
    import ctypes
    from ctypes import wintypes

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value or ""
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _win_command_line(pid: int) -> str:
    """Melhor esforco via NtQueryInformationProcess; vazio se o SO recusar."""
    import ctypes
    from ctypes import wintypes

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", ctypes.c_void_p),
        ]

    ntdll = ctypes.WinDLL("ntdll")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_VM_READ, False, pid
    )
    if not handle:
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        length = wintypes.ULONG(0)
        ntdll.NtQueryInformationProcess(
            handle, _ProcessCommandLineInformation, None, 0, ctypes.byref(length)
        )
        if not length.value:
            return ""
        buf = ctypes.create_string_buffer(length.value)
        status = ntdll.NtQueryInformationProcess(
            handle,
            _ProcessCommandLineInformation,
            buf,
            length.value,
            ctypes.byref(length),
        )
        if status != 0:
            return ""
        us = UNICODE_STRING.from_buffer_copy(buf.raw[: ctypes.sizeof(UNICODE_STRING)])
        if not us.Buffer or not us.Length:
            return ""
        nchars = us.Length // 2
        return ctypes.wstring_at(us.Buffer, nchars) or ""
    except (ValueError, OSError, TypeError):
        return ""
    finally:
        kernel32.CloseHandle(handle)


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
