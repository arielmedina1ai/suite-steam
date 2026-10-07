"""Modelos de dados da Suite."""
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
class SuiteUpdateInfo:
    """Metadados de atualizacao da propria Suite (catalog.json > suite)."""

    versao: str = ""
    download_url: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SuiteUpdateInfo":
        if not isinstance(data, dict):
            return cls()
        return cls(
            versao=str(data.get("versao", "")).strip(),
            download_url=str(data.get("download_url", "")).strip(),
        )

    @property
    def available(self) -> bool:
        return bool(self.versao and self.download_url)


@dataclass
class SubSetorInfo:
    id: str
    nome: str
    descricao: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubSetorInfo":
        sid = str(data.get("id", "")).strip()
        return cls(
            id=sid,
            nome=str(data.get("nome", sid)).strip() or sid,
            descricao=str(data.get("descricao", "")).strip(),
        )


@dataclass
class SetorInfo:
    id: str
    nome: str
    descricao: str = ""
    sub_setores: list[SubSetorInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SetorInfo":
        sid = str(data.get("id", "")).strip()
        subs_raw = data.get("sub_setores", [])
        subs: list[SubSetorInfo] = []
        if isinstance(subs_raw, list):
            for item in subs_raw:
                if isinstance(item, dict):
                    try:
                        subs.append(SubSetorInfo.from_dict(item))
                    except (KeyError, TypeError, ValueError):
                        continue
        return cls(
            id=sid,
            nome=str(data.get("nome", sid)).strip() or sid,
            descricao=str(data.get("descricao", "")).strip(),
            sub_setores=subs,
        )

    def sub_setor_by_id(self, sub_id: str) -> SubSetorInfo | None:
        alvo = (sub_id or "").strip()
        for sub in self.sub_setores:
            if sub.id == alvo:
                return sub
        return None


@dataclass
class GerenciaInfo:
    id: str
    nome: str
    descricao: str = ""
    apps: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GerenciaInfo":
        gid = str(data.get("id", "")).strip()
        apps_raw = data.get("apps", [])
        app_ids: list[str] = []
        if isinstance(apps_raw, list):
            for item in apps_raw:
                aid = str(item).strip()
                if aid and aid not in app_ids:
                    app_ids.append(aid)
        return cls(
            id=gid,
            nome=str(data.get("nome", gid)).strip() or gid,
            descricao=str(data.get("descricao", "")).strip(),
            apps=app_ids,
        )


@dataclass
class AppInfo:
    """Metadados de um aplicativo do catalogo."""

    id: str
    nome: str
    descricao: str = ""
    setor: str = ""  # id do setor (catalog.json > setores[].id)
    sub_setor: str = ""  # id do sub-setor
    imagem: str = ""  # capa (tela de detalhe) — pode virar cache local na UI
    imagem_versao: str = "1"
    icone: str = ""  # icone pequeno (cards) — pode virar cache local na UI
    icone_versao: str = "1"
    catalog_imagem: str = ""  # URL original de catalog.json > imagem
    catalog_icone: str = ""  # URL original de catalog.json > icone
    tipo: AppType = AppType.EXE
    download_url: str = ""
    upload_url: str = ""  # link da pasta SharePoint para envio (opcional)
    versao: str = "1.0.0"
    tutorial_markdown_url: str = ""
    tutorial_markdown_versao: str = "1"
    tutorial_videos: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def has_tutorial(self) -> bool:
        """Ha markdown ou ao menos um video com url. O botao ainda exige app instalado."""
        if (self.tutorial_markdown_url or "").strip():
            return True
        return any((url or "").strip() for _titulo, url, _versao in self.iter_tutorial_videos())

    def iter_tutorial_videos(self):
        for item in self.tutorial_videos:
            yield tutorial_video_fields(item)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppInfo":
        imagem = str(data.get("imagem", "")).strip()
        icone = str(data.get("icone", "")).strip()
        markdown_url, markdown_versao, videos = _tutorial_from_dict(data.get("tutorial"))
        return cls(
            id=str(data["id"]).strip(),
            nome=str(data.get("nome", data["id"])).strip(),
            descricao=str(data.get("descricao", "")),
            setor=str(data.get("setor", "")).strip(),
            sub_setor=str(data.get("sub_setor", "")).strip(),
            imagem=imagem,
            imagem_versao=str(data.get("imagem_versao", "1")),
            icone=icone,
            icone_versao=str(data.get("icone_versao", "1")),
            catalog_imagem=imagem,
            catalog_icone=icone,
            tipo=AppType.from_str(str(data.get("tipo", "exe"))),
            download_url=str(data.get("download_url", "")).strip(),
            upload_url=str(data.get("upload_url", "")).strip(),
            versao=str(data.get("versao", "1.0.0")),
            tutorial_markdown_url=markdown_url,
            tutorial_markdown_versao=markdown_versao,
            tutorial_videos=videos,
        )


@dataclass
class CatalogData:
    """Catalogo completo apos parse (antes/depois do filtro por gerencia)."""

    apps: list[AppInfo] = field(default_factory=list)
    suite: SuiteUpdateInfo = field(default_factory=SuiteUpdateInfo)
    gerencias: list[GerenciaInfo] = field(default_factory=list)
    setores: list[SetorInfo] = field(default_factory=list)
    # Rotulo da opcao "sem filtro" no seletor de gerencia (default: Geral)
    gerencia_geral: str = "Geral"

    def gerencia_by_id(self, gerencia_id: str) -> GerenciaInfo | None:
        alvo = (gerencia_id or "").strip()
        for g in self.gerencias:
            if g.id == alvo:
                return g
        return None

    def setor_by_id(self, setor_id: str) -> SetorInfo | None:
        alvo = (setor_id or "").strip()
        for s in self.setores:
            if s.id == alvo:
                return s
        return None

    def filter_for_gerencia(self, gerencia_id: str) -> "CatalogData":
        """Retorna catalogo com apenas os apps da gerencia; id vazio = sem filtro."""
        if not (gerencia_id or "").strip():
            return CatalogData(
                apps=list(self.apps),
                suite=self.suite,
                gerencias=self.gerencias,
                setores=self.setores,
                gerencia_geral=self.gerencia_geral,
            )
        g = self.gerencia_by_id(gerencia_id)
        if g is None:
            # Sem gerencia no catalogo: se houver lista de gerencias, nao mostra nada;
            # se o catalogo legado nao tiver gerencias, mantem todos os apps.
            if self.gerencias:
                return CatalogData(
                    apps=[],
                    suite=self.suite,
                    gerencias=self.gerencias,
                    setores=self.setores,
                    gerencia_geral=self.gerencia_geral,
                )
            return CatalogData(
                apps=list(self.apps),
                suite=self.suite,
                gerencias=self.gerencias,
                setores=self.setores,
                gerencia_geral=self.gerencia_geral,
            )
        allowed = set(g.apps)
        apps = [a for a in self.apps if a.id in allowed]
        return CatalogData(
            apps=apps,
            suite=self.suite,
            gerencias=self.gerencias,
            setores=self.setores,
            gerencia_geral=self.gerencia_geral,
        )


def tutorial_video_fields(item) -> tuple[str, str, str]:
    """titulo, url e versao de um video do catalogo. Versao ausente vale ``1``."""
    if isinstance(item, (list, tuple)):
        titulo = str(item[0]) if len(item) > 0 else ""
        url = str(item[1]) if len(item) > 1 else ""
        versao = str(item[2]).strip() if len(item) > 2 else ""
        return titulo, url, versao or "1"
    return "", "", "1"


def _tutorial_from_dict(raw: Any) -> tuple[str, str, list[tuple[str, str, str]]]:
    """Le tutorial.markdown_url, markdown_versao e videos[{titulo, url, versao}].

    Catalogo sem o bloco continua vazio. Url vazia nao vira video.
    Versao ausente vale ``1`` e nao e um campo do formulario.
    """
    if not isinstance(raw, dict):
        return "", "1", []
    markdown_url = str(raw.get("markdown_url") or "").strip()
    markdown_versao = str(raw.get("markdown_versao") or "").strip() or "1"
    videos: list[tuple[str, str, str]] = []
    items = raw.get("videos")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            titulo = str(item.get("titulo") or "").strip()
            url = str(item.get("url") or "").strip()
            versao = str(item.get("versao") or "").strip() or "1"
            if not url:
                continue
            videos.append((titulo, url, versao))
    return markdown_url, markdown_versao, videos


def parse_catalog_dict(data: dict[str, Any] | list[Any]) -> CatalogData:
    """Parseia o JSON do catalogo (dict completo ou lista legado de apps)."""
    if isinstance(data, list):
        apps: list[AppInfo] = []
        for item in data:
            if isinstance(item, dict):
                try:
                    apps.append(AppInfo.from_dict(item))
                except (KeyError, TypeError):
                    continue
        return CatalogData(apps=apps)

    if not isinstance(data, dict):
        return CatalogData()

    suite = SuiteUpdateInfo.from_dict(
        data.get("suite") if isinstance(data.get("suite"), dict) else None
    )

    gerencias: list[GerenciaInfo] = []
    for item in data.get("gerencias", []) if isinstance(data.get("gerencias"), list) else []:
        if isinstance(item, dict):
            try:
                g = GerenciaInfo.from_dict(item)
                if g.id:
                    gerencias.append(g)
            except (KeyError, TypeError, ValueError):
                continue

    setores: list[SetorInfo] = []
    for item in data.get("setores", []) if isinstance(data.get("setores"), list) else []:
        if isinstance(item, dict):
            try:
                s = SetorInfo.from_dict(item)
                if s.id:
                    setores.append(s)
            except (KeyError, TypeError, ValueError):
                continue

    apps = []
    for item in data.get("apps", []) if isinstance(data.get("apps"), list) else []:
        if isinstance(item, dict):
            try:
                apps.append(AppInfo.from_dict(item))
            except (KeyError, TypeError):
                continue

    geral_raw = data.get("gerencia_geral")
    gerencia_geral = (
        geral_raw.strip()
        if isinstance(geral_raw, str) and geral_raw.strip()
        else "Geral"
    )

    return CatalogData(
        apps=apps,
        suite=suite,
        gerencias=gerencias,
        setores=setores,
        gerencia_geral=gerencia_geral,
    )


def setores_visiveis(catalog: CatalogData) -> list[SetorInfo]:
    """Setores (na ordem do JSON) que tem pelo menos 1 app no catalogo filtrado."""
    used = {(a.setor or "").strip() for a in catalog.apps if (a.setor or "").strip()}
    result: list[SetorInfo] = []
    seen: set[str] = set()
    for s in catalog.setores:
        if s.id in used and s.id not in seen:
            result.append(s)
            seen.add(s.id)
    # Setores so referidos por apps, sem entrada em setores[]
    for app in catalog.apps:
        sid = (app.setor or "").strip()
        if sid and sid not in seen:
            result.append(SetorInfo(id=sid, nome=sid, descricao=""))
            seen.add(sid)
    return result


def apps_do_setor(apps: list[AppInfo], setor_id: str) -> list[AppInfo]:
    alvo = (setor_id or "").strip()
    return [a for a in apps if (a.setor or "").strip() == alvo]


def group_apps_by_sub_setor(
    apps: list[AppInfo],
    setor: SetorInfo | None,
) -> list[tuple[SubSetorInfo | None, list[AppInfo]]]:
    """Agrupa apps do setor na ordem dos sub_setores; resto em 'Outros'."""
    by_sub: dict[str, list[AppInfo]] = {}
    sem_sub: list[AppInfo] = []
    for app in apps:
        sid = (app.sub_setor or "").strip()
        if not sid:
            sem_sub.append(app)
            continue
        by_sub.setdefault(sid, []).append(app)

    groups: list[tuple[SubSetorInfo | None, list[AppInfo]]] = []
    known: set[str] = set()
    if setor is not None:
        for sub in setor.sub_setores:
            known.add(sub.id)
            chunk = by_sub.get(sub.id, [])
            if chunk:
                groups.append((sub, chunk))

    for sid, chunk in by_sub.items():
        if sid not in known and chunk:
            groups.append((SubSetorInfo(id=sid, nome=sid, descricao=""), chunk))

    if sem_sub:
        groups.append((None, sem_sub))

    return groups


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
