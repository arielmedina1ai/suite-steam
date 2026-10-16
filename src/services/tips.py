"""Dicas opcionais: versao local, download silencioso e ciclo do balao.

O tips.json fica em ``%LOCALAPPDATA%/<data_dir>/catalog/tips.json``.
A versao ja salva fica ao lado, em ``tips.versao``, e so e gravada
depois que o arquivo novo esta no lugar.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import config
from models import CatalogData, Dica, parse_tips_payload, tips_payload
from services.sharepoint_manager import baixar_do_sharepoint

# Troca do balao na home. O ciclo em si vive na memoria do processo.
TIP_ROTATE_SECONDS = 60


@dataclass
class DicasFormState:
    """Aba Dicas: link ou arquivo local, e os pares titulo/texto."""

    url: str = ""
    dest_folder: str = ""
    local_path: str = ""
    local_name: str = ""
    pairs: list[tuple[str, str]] = field(default_factory=list)
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

DownloadFn = Callable[[str, Path], Any]


def bump_dicas_version(value: str) -> str:
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


def publish_dicas_block(data: dict[str, Any], *, url: str, uploaded: bool) -> str:
    """Grava ``dicas.url`` e soma 1 na versao so se o tips.json subiu.

    ``uploaded`` falso deixa o bloco como estava e devolve a versao atual.
    """
    block = data.get("dicas")
    current = ""
    if isinstance(block, dict):
        current = str(block.get("versao") or "").strip()
    if not uploaded:
        return current
    versao = bump_dicas_version(current)
    data["dicas"] = {"url": (url or "").strip(), "versao": versao}
    return versao


def should_download_tips(
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
    version_path = path or config.TIPS_VERSION_FILE
    try:
        return version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_saved_version(versao: str, path: Path | None = None) -> None:
    version_path = path or config.TIPS_VERSION_FILE
    version_path.parent.mkdir(parents=True, exist_ok=True)
    version_path.write_text((versao or "").strip(), encoding="utf-8")


def read_tips_pairs(path: Path) -> list[tuple[str, str]]:
    """Pares de um arquivo local. ValueError se o JSON nao for tips.json."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(item.titulo, item.texto) for item in parse_tips_payload(data)]


def load_local_tips(path: Path | None = None) -> list[Dica]:
    """Le a copia local. Arquivo ausente ou invalido vira lista vazia."""
    tips_path = path or config.TIPS_FILE
    if not tips_path.is_file():
        return []
    try:
        data = json.loads(tips_path.read_text(encoding="utf-8"))
        return parse_tips_payload(data)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return []


def store_local_tips(
    pairs: list[tuple[str, str]],
    versao: str,
    *,
    tips_path: Path | None = None,
    version_path: Path | None = None,
) -> None:
    """Grava o arquivo e, so depois, a versao."""
    dest = tips_path or config.TIPS_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(tips_payload(pairs), indent=2, ensure_ascii=False) + "\n"
    tmp = dest.with_name(dest.name + ".writing")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(dest)
    write_saved_version(versao, version_path)


def _quiet_unlink(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _download_tips_file(url: str, dest: Path) -> Any:
    dest.parent.mkdir(parents=True, exist_ok=True)
    return baixar_do_sharepoint(
        link=url,
        pasta_destino=dest.parent,
        nome_arquivo=dest.name,
    )


def sync_tips(
    catalog: CatalogData,
    *,
    download: DownloadFn | None = None,
    tips_path: Path | None = None,
    version_path: Path | None = None,
) -> str:
    """``skipped``, ``downloaded`` ou ``failed``.

    Falha nao levanta e nao apaga a copia anterior. A versao local
    so muda depois que o arquivo novo foi gravado.
    """
    info = catalog.dicas
    dest = tips_path or config.TIPS_FILE
    version_dest = version_path or config.TIPS_VERSION_FILE
    saved = read_saved_version(version_dest)
    if not should_download_tips(
        url=info.url,
        versao=info.versao,
        saved_versao=saved,
        local_exists=dest.is_file(),
    ):
        return "skipped"
    partial = dest.with_name(dest.name + ".partial")
    _quiet_unlink(partial)
    downloader = download or _download_tips_file
    try:
        result = downloader(info.url.strip(), partial)
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
        parse_tips_payload(json.loads(text))
        dest.parent.mkdir(parents=True, exist_ok=True)
        writing = dest.with_name(dest.name + ".writing")
        writing.write_text(text, encoding="utf-8")
        writing.replace(dest)
        write_saved_version(info.versao.strip(), version_dest)
    except Exception:
        return "failed"
    finally:
        _quiet_unlink(partial)
    return "downloaded"


class TipCycle:
    """Embaralha sem repetir. Ao esvaziar, embaralha de novo.

    Lista vazia: ``current`` e ``advance`` devolvem None.
    Uma dica: o avanco seguinte mostra a mesma.
    """

    def __init__(self, tips: list[Dica], rng: Any | None = None) -> None:
        self._tips = list(tips)
        self._rng = rng or random.Random()
        self._queue: list[Dica] = []

    def _refill(self) -> None:
        self._queue = list(self._tips)
        if self._queue:
            self._rng.shuffle(self._queue)

    def current(self) -> Dica | None:
        if not self._tips:
            return None
        if not self._queue:
            self._refill()
        return self._queue[0] if self._queue else None

    def advance(self) -> Dica | None:
        if not self._tips:
            return None
        if self._queue:
            self._queue.pop(0)
        if not self._queue:
            self._refill()
        return self._queue[0] if self._queue else None
