import json
from pathlib import Path
from src.dependency_check import DependencyResult
def test_statuses():
    assert DependencyResult('OK',{}).ok and DependencyResult('REPAIRED_OK',{}).ok
def test_script_contract():
    text=Path('scripts/check_and_resolving_dependencies.ps1').read_text(encoding='utf-8')
    assert "$ErrorActionPreference = 'Stop'" in text and '-Repair' in text and '-Quiet' in text
def test_json():
    assert json.loads('{"status":"OK"}')['status']=='OK'