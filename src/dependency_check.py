from __future__ import annotations
import json, logging, os, subprocess
from dataclasses import dataclass
from pathlib import Path
log = logging.getLogger(__name__)
@dataclass
class DependencyResult:
    status: str
    details: dict
    @property
    def ok(self):
        return self.status in {'OK', 'REPAIRED_OK'}
def _powershell():
    if os.name != 'nt':
        return None
    for name in ('powershell.exe', 'powershell'):
        for directory in os.environ.get('PATH', '').split(os.pathsep):
            candidate = Path(directory) / name
            if candidate.is_file():
                return str(candidate)
    return None
def _run(root, script, repair=False, quiet=True, timeout=120):
    exe = _powershell()
    if not exe:
        return DependencyResult('UNSUPPORTED_ENVIRONMENT', {'message': 'Windows PowerShell não encontrado.'})
    args = [exe, '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script)]
    if repair:
        args.append('-Repair')
    if quiet:
        args.append('-Quiet')
    try:
        completed = subprocess.run(args, cwd=str(root), capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        status = 'REPAIR_FAILED' if repair else 'VALIDATION_FAILED'
        return DependencyResult(status, {'message': 'Timeout ao executar subprocesso PowerShell.'})
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    try:
        payload = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        status = 'REPAIR_FAILED' if repair else 'VALIDATION_FAILED'
        return DependencyResult(status, {'message': 'O subprocesso não retornou JSON válido.'})
    return DependencyResult(str(payload.get('status', 'VALIDATION_FAILED')), payload)
def check_and_resolve_dependencies(project_root=None, repair=False, quiet=False, timeout=120):
    root = Path(project_root or Path(__file__).resolve().parents[1])
    script = root / 'scripts' / 'check_and_resolving_dependencies.ps1'
    initial = _run(root, script, repair=False, quiet=quiet, timeout=timeout)
    if initial.ok or not repair:
        return initial
    repair_result = _run(root, script, repair=True, quiet=quiet, timeout=timeout)
    if repair_result.status not in {'REPAIRED_OK', 'OK'}:
        return repair_result
    final = _run(root, script, repair=False, quiet=quiet, timeout=timeout)
    if final.ok:
        final.status = 'REPAIRED_OK'
    return final
def ensure_dependencies(project_root=None, auto_repair=False, timeout=120):
    return check_and_resolve_dependencies(project_root, repair=auto_repair, quiet=True, timeout=timeout)