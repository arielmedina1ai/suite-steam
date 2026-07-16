"""Modelos de dados da Suite Petrobras."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AppType(str, Enum):
    EXE = "exe"
    XLSX = "xlsx"
    XLSM = "xlsm"

    @classmethod
    def from_str(cls, value: str) -> "AppType":
        value = (value or "").strip().lower()
        for item in cls:
            if item.value == value:
                return item
        # fallback baseado na extensao do valor recebido
        if value.endswith("xlsm"):
            return cls.XLSM
        if value.endswith("xlsx") or value.endswith("xls"):
            return cls.XLSX
        return cls.EXE

    @property
    def is_spreadsheet(self) -> bool:
        """Planilhas Excel (.xlsx / .xlsm) — abertas via Excel, nao executadas."""
        return self in (AppType.XLSX, AppType.XLSM)

    @property
    def file_extension(self) -> str:
        return f".{self.value}"


class InstallStatus(str, Enum):
    NOT_INSTALLED = "not_installed"
    DOWNLOADING = "downloading"
    INSTALLED = "installed"
    ERROR = "error"


@dataclass
class AppInfo:
    """Metadados de um aplicativo do catalogo."""

    id: str
    nome: str
    descricao: str = ""
    imagem: str = ""
    tipo: AppType = AppType.EXE
    download_url: str = ""
    upload_url: str = ""  # link da pasta SharePoint para envio (opcional)
    versao: str = "1.0.0"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppInfo":
        return cls(
            id=str(data["id"]).strip(),
            nome=str(data.get("nome", data["id"])).strip(),
            descricao=str(data.get("descricao", "")),
            imagem=str(data.get("imagem", "")),
            tipo=AppType.from_str(str(data.get("tipo", "exe"))),
            download_url=str(data.get("download_url", "")).strip(),
            upload_url=str(data.get("upload_url", "")).strip(),
            versao=str(data.get("versao", "1.0.0")),
        )


@dataclass
class InstallState:
    """Estado local de instalacao de um aplicativo."""

    app_id: str
    status: InstallStatus = InstallStatus.NOT_INSTALLED
    local_path: str | None = None
    versao: str | None = None
    progress: float = 0.0
    message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, app_id: str, data: dict[str, Any]) -> "InstallState":
        return cls(
            app_id=app_id,
            status=InstallStatus(data.get("status", InstallStatus.INSTALLED.value)),
            local_path=data.get("local_path"),
            versao=data.get("versao"),
            extra=data.get("extra", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "local_path": self.local_path,
            "versao": self.versao,
            "extra": self.extra,
        }
