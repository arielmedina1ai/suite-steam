"""Links opcionais: versao local e download silencioso.

O links.json fica em ``%LOCALAPPDATA%/<data_dir>/catalog/links.json``.
A versao ja salva fica ao lado, em ``links.versao``, e so e gravada
depois que o arquivo novo esta no lugar. Falha nao levanta, nao apaga
a copia anterior e nao mostra aviso. O item do menu so aparece quando
o ponteiro esta completo e a copia local dessa versao e valida.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
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


@dataclass
class LinkDraft:
    """Item da aba Links. Descricao pode ficar vazia."""

    titulo: str = ""
    descricao: str = ""
    url: str = ""


@dataclass
class LinkGroupDraft:
    """Grupo na ordem em que a pagina Links mostra."""

    titulo: str = ""
    items: list[LinkDraft] = field(default_factory=list)


@dataclass
class LinksFormState:
    """Aba Links: link ou arquivo local, e os grupos editaveis."""

    url: str = ""
    dest_folder: str = ""
    local_path: str = ""
    local_name: str = ""
    groups: list[LinkGroupDraft] = field(default_factory=list)
    versao: str = ""
    fingerprint: str = ""
    busy: bool = False
    message: str = ""
    notice: str = ""
    notice_ok: bool = False
    conflict: bool = False
    progress: float | None = None
    hold_scroll: bool = False
    select_scroll: float = 0.0
    edit_scroll: float = 0.0

    @property
    def has_file(self) -> bool:
        """Ha link colado ou arquivo local escolhido — o bloco Editar libera."""
        return bool((self.url or "").strip() or (self.local_path or "").strip())


def drafts_from_groups(groups: list[LinkGroup]) -> list[LinkGroupDraft]:
    """Copia os grupos ja filtrados da pagina para o formulario."""
    drafts: list[LinkGroupDraft] = []
    for group in groups:
        drafts.append(
            LinkGroupDraft(
                titulo=group.titulo,
                items=[
                    LinkDraft(titulo=item.titulo, descricao=item.descricao, url=item.url)
                    for item in group.links
                ],
            )
        )
    return drafts


def read_links_groups(path: Path) -> list[LinkGroupDraft]:
    """Grupos de um arquivo local. ValueError se o JSON nao for links.json."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return drafts_from_groups(parse_links_payload(data))


def links_payload(groups: list[LinkGroupDraft]) -> dict[str, Any]:
    """Monta o links.json na ordem editada.

    Grupo sem titulo nao entra. Item sem titulo ou sem url nao entra.
    Descricao vazia permanece. Grupo que ficou sem item valido tambem sai.
    """
    grupos: list[dict[str, Any]] = []
    for group in groups:
        titulo = (group.titulo or "").strip()
        if not titulo:
            continue
        links: list[dict[str, str]] = []
        for item in group.items:
            item_titulo = (item.titulo or "").strip()
            url = (item.url or "").strip()
            descricao = (item.descricao or "").strip()
            if not item_titulo or not url:
                continue
            links.append({"titulo": item_titulo, "descricao": descricao, "url": url})
        if not links:
            continue
        grupos.append({"titulo": titulo, "links": links})
    return {"grupos": grupos}


def _group_at(groups: list[LinkGroupDraft], index: int) -> LinkGroupDraft | None:
    if index < 0 or index >= len(groups):
        return None
    return groups[index]


def _item_at(groups: list[LinkGroupDraft], group_index: int, item_index: int) -> LinkDraft | None:
    group = _group_at(groups, group_index)
    if group is None or item_index < 0 or item_index >= len(group.items):
        return None
    return group.items[item_index]


def set_group_title(groups: list[LinkGroupDraft], index: int, value: str) -> None:
    group = _group_at(groups, index)
    if group is None:
        return
    group.titulo = value or ""


def set_item_field(
    groups: list[LinkGroupDraft],
    group_index: int,
    item_index: int,
    field_name: str,
    value: str,
) -> None:
    item = _item_at(groups, group_index, item_index)
    if item is None:
        return
    text = value or ""
    if field_name == "titulo":
        item.titulo = text
    elif field_name == "descricao":
        item.descricao = text
    elif field_name == "url":
        item.url = text


def add_group(groups: list[LinkGroupDraft]) -> None:
    """Grupo novo entra no fim."""
    groups.append(LinkGroupDraft())


def add_item(groups: list[LinkGroupDraft], group_index: int) -> None:
    """Item novo entra no fim do grupo."""
    group = _group_at(groups, group_index)
    if group is None:
        return
    group.items.append(LinkDraft())


def remove_group(groups: list[LinkGroupDraft], index: int) -> None:
    if _group_at(groups, index) is None:
        return
    del groups[index]


def remove_item(groups: list[LinkGroupDraft], group_index: int, item_index: int) -> None:
    group = _group_at(groups, group_index)
    if group is None or item_index < 0 or item_index >= len(group.items):
        return
    del group.items[item_index]


def move_group(groups: list[LinkGroupDraft], index: int, delta: int) -> bool:
    """Sobe (delta -1) ou desce (delta +1) o grupo. Nas pontas, nao move."""
    target = index + delta
    if index < 0 or target < 0 or index >= len(groups) or target >= len(groups):
        return False
    groups[index], groups[target] = groups[target], groups[index]
    return True


def move_item(
    groups: list[LinkGroupDraft],
    group_index: int,
    item_index: int,
    delta: int,
) -> bool:
    """Sobe ou desce o item dentro do grupo. Nao troca de grupo."""
    group = _group_at(groups, group_index)
    if group is None:
        return False
    target = item_index + delta
    if item_index < 0 or target < 0 or item_index >= len(group.items) or target >= len(group.items):
        return False
    group.items[item_index], group.items[target] = group.items[target], group.items[item_index]
    return True


def relocate_item(
    groups: list[LinkGroupDraft],
    group_index: int,
    item_index: int,
    new_title: str,
) -> bool:
    """Troca o campo de grupo: o item vai para o fim desse grupo.

    Titulo igual ao grupo atual nao move. Grupo ainda inexistente e criado no fim.
    """
    group = _group_at(groups, group_index)
    if group is None or item_index < 0 or item_index >= len(group.items):
        return False
    title = (new_title or "").strip()
    if title == (group.titulo or "").strip():
        return False
    item = group.items.pop(item_index)
    target: LinkGroupDraft | None = None
    for candidate in groups:
        if (candidate.titulo or "").strip() == title:
            target = candidate
            break
    if target is None:
        target = LinkGroupDraft(titulo=title)
        groups.append(target)
    target.items.append(item)
    return True


def bump_links_version(value: str) -> str:
    """Soma 1. Sem versao anterior, a primeira gravacao vale ``1``."""
    raw = (value or "").strip()
    if not raw:
        return "1"
    if raw.isdigit():
        return str(int(raw) + 1)
    digits = ""
    for ch in raw:
        if ch.isdigit():
            digits += ch
        else:
            break
    if digits:
        return str(int(digits) + 1)
    return "1"


def publish_links_block(data: dict[str, Any], *, url: str, uploaded: bool) -> str:
    """Grava ``links.url`` e soma 1 na versao so se o links.json subiu.

    ``uploaded`` falso deixa o bloco como estava e devolve a versao atual.
    """
    block = data.get("links")
    current = ""
    if isinstance(block, dict):
        current = str(block.get("versao") or "").strip()
    if not uploaded:
        return current
    versao = bump_links_version(current)
    data["links"] = {"url": (url or "").strip(), "versao": versao}
    return versao


def store_local_links(
    groups: list[LinkGroupDraft],
    versao: str,
    *,
    links_path: Path | None = None,
    version_path: Path | None = None,
) -> None:
    """Grava o arquivo e, so depois, a versao."""
    dest = links_path or config.LINKS_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(links_payload(groups), indent=2, ensure_ascii=False) + "\n"
    tmp = dest.with_name(dest.name + ".writing")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(dest)
    write_saved_version(versao, version_path)
