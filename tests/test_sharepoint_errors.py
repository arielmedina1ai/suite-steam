"""Mensagens amigaveis e parse de UniqueId (download.aspx)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from services.sharepoint_manager import (  # noqa: E402
    _mensagem_amigavel_falha,
    abrir_pedido_acesso_sharepoint,
    is_access_denied_error,
    is_access_request_ok,
    parsear_link_download_aspx,
)


DUMP = """
Site: https://empresa.sharepoint.com/teams/bdoc_20250301010735
UniqueId recebido: 874d1635-b0f4-49ca-987b-fc15cd7bc6ff
CSOM GetFileById falhou: Access is denied. (Exception from HRESULT: 0x80070005 (E_ACCESSDENIED))
FALHA: nao foi possivel obter ServerRelativeUrl do UniqueId.
"""


def test_mensagem_access_denied_nao_despeja_powershell():
    msg = _mensagem_amigavel_falha(DUMP, "Invoke-PnPSPRestMethod : Uri de solicitação inválida")
    assert "0x80070005" not in msg
    assert "Invoke-PnPSPRestMethod" not in msg
    assert "permissao" in msg.lower() or "permissão" in msg.lower()
    assert "solicite acesso" in msg.lower()


def test_mensagem_login_failed():
    msg = _mensagem_amigavel_falha("FALHA: LOGIN_FAILED cancelled", "")
    assert "conectar" in msg.lower()


def test_parse_uniqueid_com_chaves_urlencoded():
    url = (
        "https://empresa.sharepoint.com/teams/bdoc/_layouts/15/download.aspx"
        "?UniqueId=%7B874D1635-B0F4-49CA-987B-FC15CD7BC6FF%7D"
    )
    info = parsear_link_download_aspx(url)
    assert info["tipo"] == "unique_id"
    assert info["site_url"] == "https://empresa.sharepoint.com/teams/bdoc"
    assert info["unique_id"] == "874D1635-B0F4-49CA-987B-FC15CD7BC6FF"


def test_template_rest_usa_uri_absoluta():
    text = (ROOT / "scripts" / "template_sp_download_by_id.ps1").read_text(encoding="utf-8")
    assert "_api/web/GetFileById" in text
    assert "TrimEnd" in text
    assert "LOGIN_FAILED" in text
    assert 'Invoke-PnPSPRestMethod -Url "_api/' not in text


def test_is_access_denied_error():
    assert is_access_denied_error("", DUMP)
    assert not is_access_denied_error("timeout de rede", "")


def test_abrir_pedido_acesso_recusa_url_invalida():
    assert abrir_pedido_acesso_sharepoint("") is False
    assert abrir_pedido_acesso_sharepoint("catalog.json") is False


def test_abrir_pedido_acesso_abre_http(monkeypatch):
    opened: list[str] = []
    monkeypatch.setattr(
        "services.sharepoint_manager.webbrowser.open",
        lambda url: opened.append(url),
    )
    assert abrir_pedido_acesso_sharepoint("https://empresa.sharepoint.com/x") is True
    assert opened == ["https://empresa.sharepoint.com/x"]


def test_access_request_ok_tem_prioridade_na_mensagem():
    stdout = DUMP + "\nACCESS_REQUEST_OK\n"
    assert is_access_request_ok(stdout, "")
    msg = _mensagem_amigavel_falha(stdout, "")
    assert "automatico" in msg.lower()
    assert "0x80070005" not in msg


def test_access_request_failed_nao_conta_como_ok():
    assert not is_access_request_ok("ACCESS_REQUEST_FAILED: boom", "")


def test_helper_pedido_acesso_existe():
    text = (ROOT / "scripts" / "pnp_request_access.ps1").read_text(encoding="utf-8")
    assert "function Request-SuiteAccess" in text
    assert "ACCESS_REQUEST_OK" in text
    assert "_api/web/requestaccess" in text
