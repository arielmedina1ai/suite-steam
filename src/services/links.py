"""Links opcionais: versao local e download silencioso.

O links.json fica em ``%LOCALAPPDATA%/<data_dir>/catalog/links.json``.
A versao ja salva fica ao lado, em ``links.versao``, e so e gravada
depois que o arquivo novo esta no lugar. Falha nao levanta, nao apaga
a copia anterior e nao mostra aviso. O item do menu so aparece quando
o ponteiro esta completo e a copia local dessa versao e valida.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import config
from models import CatalogData, LinkGroup, parse_links_payload
from services.sharepoint_manager import baixar_do_sharepoint

DownloadFn = Callable[[str, Path], Any]


def should_download_links(
    *,
    url: str,
    versao: str,
    saved_versao: str,
    local_exists: bool,
) -> bool:
    """True quando vale baixar. Sem url ou sem versao remota: nao baixa."""
    remote_url = (url or "").strip()
    remote_versao = (versao or "").strip()
    if not remote_url or not remote_versao:
        return False
    if (saved_versao or "").strip() == remote_versao and local_exists:
        return False
    return True


def read_saved_version(path: Path | None = None) -> str:
    version_path = path or config.LINKS_VERSION_FILE
    try:
        return version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_saved_version(versao: str, path: Path | None = None) -> None:
    version_path = path or config.LINKS_VERSION_FILE
    version_path.parent.mkdir(parents=True, exist_ok=True)
    version_path.write_text((versao or "").strip(), encoding="utf-8")


def links_file_valid(path: Path) -> bool:
    """True se o arquivo existe e o JSON tem a lista ``grupos``.

    HTML, JSON quebrado ou formato sem a lista nao valem. Grupos e itens
    incompletos nao invalidam o arquivo: a lista filtrada pode ficar vazia.
    """
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
        if text.lstrip().startswith("<"):
            return False
        parse_links_payload(json.loads(text))
    except (OSError, json.JSONDecodeError, ValueError, TypeError, UnicodeError):
        return False
    return True


def links_menu_visible(
    catalog: CatalogData,
    *,
    links_path: Path | None = None,
    version_path: Path | None = None,
) -> bool:
    """Item Links so com ponteiro completo e copia local valida da mesma versao.

    Ponteiro ausente, download que nao gravou a versao nova, arquivo ausente,
    HTML ou JSON invalido: False. Arquivo valido com zero links: True.
    """
    info = getattr(catalog, "links", None)
    if info is None or not getattr(info, "configured", False):
        return False
    dest = links_path or config.LINKS_FILE
    version_dest = version_path or config.LINKS_VERSION_FILE
    saved = read_saved_version(version_dest)
    if saved != (info.versao or "").strip():
        return False
    return links_file_valid(dest)


def load_local_links(path: Path | None = None) -> list[LinkGroup]:
    """Le a copia local. Arquivo ausente ou invalido vira lista vazia."""
    links_path = path or config.LINKS_FILE
    if not links_file_valid(links_path):
        return []
    try:
        data = json.loads(links_path.read_text(encoding="utf-8"))
        return parse_links_payload(data)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return []


def _quiet_unlink(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _download_links_file(url: str, dest: Path) -> Any:
    dest.parent.mkdir(parents=True, exist_ok=True)
    return baixar_do_sharepoint(
        link=url,
        pasta_destino=dest.parent,
        nome_arquivo=dest.name,
    )


def sync_links(
    catalog: CatalogData,
    *,
    download: DownloadFn | None = None,
    links_path: Path | None = None,
    version_path: Path | None = None,
) -> str:
    """``skipped``, ``downloaded`` ou ``failed``.

    Falha nao levanta e nao apaga a copia anterior. A versao local
    so muda depois que o arquivo novo foi gravado. Sem url ou sem
    versao no ponteiro, nao baixa.
    """
    info = getattr(catalog, "links", None)
    url = getattr(info, "url", "") if info is not None else ""
    versao = getattr(info, "versao", "") if info is not None else ""
    dest = links_path or config.LINKS_FILE
    version_dest = version_path or config.LINKS_VERSION_FILE
    saved = read_saved_version(version_dest)
    if not should_download_links(
        url=url,
        versao=versao,
        saved_versao=saved,
        local_exists=dest.is_file(),
    ):
        return "skipped"
    partial = dest.with_name(dest.name + ".partial")
    _quiet_unlink(partial)
    downloader = download or _download_links_file
    try:
        result = downloader(url.strip(), partial)
    except Exception:
        _quiet_unlink(partial)
        return "failed"
    if not getattr(result, "ok", False):
        _quiet_unlink(partial)
        return "failed"
    source = getattr(result, "path", None) or partial
    try:
        text = Path(source).read_text(encoding="utf-8")
        if text.lstrip().startswith("<"):
            raise ValueError("conteudo HTML")
        parse_links_payload(json.loads(text))
        dest.parent.mkdir(parents=True, exist_ok=True)
        writing = dest.with_name(dest.name + ".writing")
        writing.write_text(text, encoding="utf-8")
        writing.replace(dest)
        write_saved_version(versao.strip(), version_dest)
    except Exception:
        return "failed"
    finally:
        _quiet_unlink(partial)
    return "downloaded"
