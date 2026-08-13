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
