from __future__ import annotations
import json, logging, os, subprocess
from dataclasses import dataclass
from pathlib import Path
log=logging.getLogger(__name__)
@dataclass
class DependencyResult:
    status:str
    details:dict
    @property
    def ok(self): return self.status in {'OK','REPAIRED_OK'}
def _powershell():
    if os.name!='nt': return None
    for name in ('powershell.exe','powershell'):
        for directory in os.environ.get('PATH','').split(os.pathsep):
            candidate=Path(directory)/name
            if candidate.is_file(): return str(candidate)
    return None
def check_and_resolve_dependencies(project_root=None,repair=False,quiet=False,timeout=120):
    root=Path(project_root or Path(__file__).resolve().parents[1]);script=root/'scripts'/'check_and_resolving_dependencies.ps1';exe=_powershell()
    if not exe:return DependencyResult('UNSUPPORTED_ENVIRONMENT',{'message':'Windows PowerShell não encontrado.'})
    args=[exe,'-NoLogo','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script)]+(['-Repair'] if repair else [])+(['-Quiet'] if quiet else [])
    try: completed=subprocess.run(args,cwd=root,capture_output=True,text=True,timeout=timeout,check=False)
    except subprocess.TimeoutExpired:return DependencyResult('REPAIR_FAILED' if repair else 'VALIDATION_FAILED',{'message':'Timeout ao validar dependências.'})
    lines=[line.strip() for line in completed.stdout.splitlines() if line.strip()]
    try: data=json.loads(lines[-1])
    except (IndexError,json.JSONDecodeError): return DependencyResult('REPAIR_FAILED' if repair else 'VALIDATION_FAILED',{'message':'Saída JSON inválida.'})
    return DependencyResult(str(data.get('status','VALIDATION_FAILED')),data)
def ensure_dependencies(project_root=None,auto_repair=False,timeout=120):
    result=check_and_resolve_dependencies(project_root,quiet=True,timeout=timeout)
    if result.ok:return result
    if auto_repair and result.status in {'REPAIR_REQUIRED','MODULE_NOT_FOUND','DEPENDENCY_MISSING','IMPORT_FAILED','MULTIPLE_VERSIONS'}:return check_and_resolve_dependencies(project_root,repair=True,quiet=True,timeout=timeout)
    return result