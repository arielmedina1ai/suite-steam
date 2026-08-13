"""Testes do reparo condicional PnP (caminho unico: baixar_do_sharepoint)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.sharepoint_manager import (  # noqa: E402
    SharePointResult,
    _is_pnp_dependency_error,
    _reparar_dependencia_pnp,
    _reset_pnp_repair_state,
    _run_powershell,
    _scripts_dir,
    _tentar_reparo_se_dependencia,
    baixar_do_sharepoint,
)


SAMPLE_LINK = (
    "https://empresa.sharepoint.com/teams/site/_layouts/15/download.aspx"
    "?UniqueId=12345678-1234-1234-1234-1234567890ab"
)

DEP_STDERR = "DEP_ERROR: MODULE_NOT_LOADED\nFALHA: Modulo nao carregado."


def setup_function() -> None:
    _reset_pnp_repair_state()


def test_is_pnp_dependency_error_detects_specific_markers():
    assert _is_pnp_dependency_error("", DEP_STDERR)
    assert _is_pnp_dependency_error(
        "", "Could not load file or assembly Microsoft.IdentityModel.Clients.ActiveDirectory"
    )
    assert _is_pnp_dependency_error("", "REPAIR_FAILED: boom")


def test_is_pnp_dependency_error_ignores_auth_and_network():
    # Markers genericos removidos: nao reinstalar em 401 / rede / cmdlet no log.
    assert not _is_pnp_dependency_error("401 Unauthorized", "access denied")
    assert not _is_pnp_dependency_error("timeout de rede", "")
    assert not _is_pnp_dependency_error("Connect-PnPOnline", "Import-Module")
    assert not _is_pnp_dependency_error("SharePointPnPPowerShellOnline", "")
    assert not _is_pnp_dependency_error("FileNotFoundException", "arquivo.xml")


def test_scripts_dir_resolves_reparar_pnp():
    script = _scripts_dir() / "reparar_pnp.ps1"
    assert script.exists()


def test_run_powershell_timeout():
    fake = MagicMock()
    fake.communicate.side_effect = __import__("subprocess").TimeoutExpired(
        cmd="x", timeout=1
    )
    fake.kill = MagicMock()
    fake.wait = MagicMock()
    with patch("services.sharepoint_manager.subprocess.Popen", return_value=fake):
        code, stdout, stderr = _run_powershell("dummy.ps1", timeout=1)
    assert code == 124
    assert "Timeout" in stderr
    fake.kill.assert_called_once()


def test_run_powershell_missing_exe():
    with patch(
        "services.sharepoint_manager.subprocess.Popen",
        side_effect=FileNotFoundError("powershell.exe"),
    ):
        code, _stdout, stderr = _run_powershell("dummy.ps1")
    assert code == 127
    assert "powershell" in stderr.lower()


def test_reparar_dependencia_pnp_missing_script(tmp_path):
    with patch("services.sharepoint_manager._scripts_dir", return_value=tmp_path):
        ok, msg = _reparar_dependencia_pnp()
    assert not ok
    assert "nao encontrado" in msg.lower()


def test_reparar_dependencia_pnp_ok(tmp_path):
    script = tmp_path / "reparar_pnp.ps1"
    script.write_text("# dummy", encoding="utf-8")
    with patch("services.sharepoint_manager._scripts_dir", return_value=tmp_path), patch(
        "services.sharepoint_manager._run_powershell",
        return_value=(0, "REPAIR_OK\n", ""),
    ):
        ok, msg = _reparar_dependencia_pnp()
    assert ok
    assert "sucesso" in msg.lower()


def test_reparar_dependencia_pnp_failed(tmp_path):
    script = tmp_path / "reparar_pnp.ps1"
    script.write_text("# dummy", encoding="utf-8")
    with patch("services.sharepoint_manager._scripts_dir", return_value=tmp_path), patch(
        "services.sharepoint_manager._run_powershell",
        return_value=(1, "REPAIR_FAILED: boom", ""),
    ):
        ok, msg = _reparar_dependencia_pnp()
    assert not ok
    assert "falhou" in msg.lower()


def test_baixar_sucesso_sem_reparo(tmp_path):
    destino = tmp_path / "out.bin"
    success = SharePointResult(ok=True, path=destino, message="ok", stdout="ok")
    with patch(
        "services.sharepoint_manager._executar_download_sharepoint",
        return_value=success,
    ) as download, patch(
        "services.sharepoint_manager._reparar_dependencia_pnp"
    ) as repair:
        result = baixar_do_sharepoint(
            SAMPLE_LINK, pasta_destino=tmp_path, nome_arquivo="out.bin"
        )
    assert result.ok
    download.assert_called_once()
    repair.assert_not_called()


def test_baixar_erro_nao_dependencia_sem_reparo():
    fail = SharePointResult(
        ok=False,
        message="Sem permissao no arquivo do catalogo apos o login.",
        stdout="401 Unauthorized",
        stderr="",
    )
    with patch(
        "services.sharepoint_manager._executar_download_sharepoint",
        return_value=fail,
    ), patch("services.sharepoint_manager._reparar_dependencia_pnp") as repair:
        result = baixar_do_sharepoint(
            SAMPLE_LINK, pasta_destino=".", nome_arquivo="x.bin"
        )
    assert not result.ok
    repair.assert_not_called()


def test_baixar_erro_dependencia_repair_ok_retry_ok(tmp_path):
    destino = tmp_path / "out.bin"
    fail = SharePointResult(
        ok=False,
        message="Modulo ausente",
        stdout="",
        stderr=DEP_STDERR,
    )
    success = SharePointResult(ok=True, path=destino, message="ok")
    with patch(
        "services.sharepoint_manager._executar_download_sharepoint",
        side_effect=[fail, success],
    ) as download, patch(
        "services.sharepoint_manager._reparar_dependencia_pnp",
        return_value=(True, "ok"),
    ) as repair:
        result = baixar_do_sharepoint(
            SAMPLE_LINK, pasta_destino=tmp_path, nome_arquivo="out.bin"
        )
    assert result.ok
    assert download.call_count == 2
    repair.assert_called_once()


def test_baixar_erro_dependencia_repair_failed():
    fail = SharePointResult(
        ok=False,
        message="Modulo ausente",
        stdout=DEP_STDERR,
        stderr="",
    )
    with patch(
        "services.sharepoint_manager._executar_download_sharepoint",
        return_value=fail,
    ) as download, patch(
        "services.sharepoint_manager._reparar_dependencia_pnp",
        return_value=(False, "REPAIR_FAILED"),
    ):
        result = baixar_do_sharepoint(
            SAMPLE_LINK, pasta_destino=".", nome_arquivo="x.bin"
        )
    assert not result.ok
    assert "reparo" in result.message.lower()
    assert download.call_count == 1


def test_reparo_no_maximo_uma_vez_por_sessao():
    with patch(
        "services.sharepoint_manager._reparar_dependencia_pnp",
        return_value=(True, "ok"),
    ) as repair:
        assert _tentar_reparo_se_dependencia("", DEP_STDERR) is True
        assert _tentar_reparo_se_dependencia("", DEP_STDERR) is False
    repair.assert_called_once()


def test_nao_encerra_processos_externos():
    text = (ROOT / "scripts" / "reparar_pnp.ps1").read_text(encoding="utf-8")
    assert "Stop-Process" not in text
    assert "REPAIR_OK" in text
    assert "Write-Error" not in text
    manager = (SRC / "services" / "sharepoint_manager.py").read_text(encoding="utf-8")
    assert "Stop-Process" not in manager
    assert "taskkill" not in manager.lower()


def test_templates_emitem_dep_error():
    for name in (
        "template_sp_download.ps1",
        "template_sp_download_by_id.ps1",
        "template_sp_download_batch.ps1",
        "template_sp_upload.ps1",
    ):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "DEP_ERROR: MODULE_NOT_LOADED" in text


def test_logs_nao_contem_credenciais():
    manager = (SRC / "services" / "sharepoint_manager.py").read_text(encoding="utf-8")
    for forbidden in ("password", "client_secret", "clientsecret", "cookie", "token="):
        assert forbidden not in manager.lower()


def test_orphan_stack_removido():
    assert not (SRC / "dependency_check.py").exists()
    assert not (ROOT / "scripts" / "check_and_resolving_dependencies.ps1").exists()
