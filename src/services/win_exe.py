"""Confere se um arquivo e um executavel Windows (cabecalho MZ/PE)."""
from __future__ import annotations

from pathlib import Path

# SharePoint as vezes grava HTML, pagina de erro ou arquivo incompleto com extensao .exe.
INVALID_EXE_MESSAGE = "O arquivo baixado nao e um executavel valido. Baixe de novo."


def is_windows_pe(path: Path) -> bool:
    """True se o arquivo tem assinatura MZ e PE no offset e_lfanew."""
    try:
        with path.open("rb") as handle:
            dos = handle.read(64)
            if len(dos) < 64 or dos[:2] != b"MZ":
                return False
            pe_offset = int.from_bytes(dos[0x3C:0x40], "little")
            if pe_offset < 64:
                return False
            size = path.stat().st_size
            if pe_offset + 4 > size:
                return False
            handle.seek(pe_offset)
            return handle.read(4) == b"PE\x00\x00"
    except OSError:
        return False
