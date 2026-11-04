"""Feedback do aplicativo: lista que so cresce no feedback.json do SharePoint.

O ponteiro fica em catalog.json > feedback (url download.aspx?UniqueId= e versao).
Sem url ou sem versao, a tela nao abre. O envio le o arquivo, acrescenta um
item e grava de novo. feedback.versao sobe 1 so se esse envio deu certo.
Um WebLogin, PowerShell sem janela, o mesmo caminho das dicas.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import config
from models import CatalogData
from services.catalog_check import as_sao_paulo, sao_paulo_now
from services.catalog_publish import (
    PublishOutcome,
    _upload_catalog_text,
    catalog_fingerprint,
    fetch_remote_catalog_text,
)
from services.sharepoint_manager import (
    PnPWebLoginSession,
    baixar_do_sharepoint,
    enviar_por_unique_id,
    parsear_link_sharepoint,
)
from services.tips import bump_dicas_version
from services.windows_identity import current_windows_login

_READ_ERROR = "Nao foi possivel ler o feedback."
_SEND_ERROR = "Nao foi possivel enviar."
_VERSION_ERROR = "Nao foi possivel atualizar a versao."
_EMPTY_ERROR = "Escreva o feedback."
_INVALID_ERROR = "feedback.json invalido."

ProgressCb = Callable[[float, str], None]


@dataclass
class FeedbackSendResult:
    ok: bool
    message: str = ""
    item: dict[str, str] | None = None
    versao: str = ""
    catalog: CatalogData | None = None


def feedback_timestamp(now: datetime | None = None) -> str:
    """Data e hora em America/Sao_Paulo, sem pedir o relogio na tela."""
    moment = sao_paulo_now() if now is None else as_sao_paulo(now)
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def feedback_item(*, usuario: str, quando: str, app_id: str, texto: str) -> dict[str, str]:
    return {
        "usuario": usuario,
        "quando": quando,
        "app_id": app_id,
        "texto": texto,
    }


def feedback_item_list(data: Any) -> list[Any]:
    """Itens na ordem do arquivo. Lista pura ou objeto antigo com ``itens``."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("itens"), list):
        return data["itens"]
    raise ValueError(_INVALID_ERROR)


def append_feedback(data: Any, item: dict[str, str]) -> list[Any]:
    """Acrescenta no fim e devolve so a lista. O texto guia nao mora aqui."""
    return [*feedback_item_list(data), item]


def publish_feedback_block(
    data: dict[str, Any],
    *,
    uploaded: bool,
    url: str | None = None,
    introducao: str | None = None,
) -> str:
    """Soma 1 em feedback.versao so se o envio do catalogo deu certo.

    Sem ``url``, a url que ja estava no bloco permanece. UniqueId colado
    nao e reescrito. ``uploaded`` falso devolve a versao atual e nao mexe
    no bloco. ``introducao`` None deixa o texto guia como estava.
    """
    block = data.get("feedback")
    current = ""
    raw_url = ""
    if isinstance(block, dict):
        current = str(block.get("versao") or "").strip()
        existing = block.get("url")
        if isinstance(existing, str):
            raw_url = existing
    if not uploaded:
        return current
    if url is None:
        if not isinstance(block, dict) or not raw_url.strip() or not current:
            return current
        updated = dict(block)
        updated["url"] = raw_url
        updated["versao"] = bump_dicas_version(current)
        if introducao is not None:
            updated["introducao"] = introducao
        data["feedback"] = updated
        return updated["versao"]
    stored = url if isinstance(url, str) else str(url or "")
    if not stored.strip():
        return current
    updated = dict(block) if isinstance(block, dict) else {}
    updated["url"] = stored
    updated["versao"] = bump_dicas_version(current)
    if introducao is not None:
        updated["introducao"] = introducao
    data["feedback"] = updated
    return updated["versao"]


def submit_app_feedback(
    *,
    app_id: str,
    texto: str,
    feedback_url: str,
    usuario: str | None = None,
    now: datetime | None = None,
    read_feedback: Callable[[], tuple[str, str]] | None = None,
    upload_feedback: Callable[[str], tuple[bool, str]] | None = None,
    fetch_catalog: Callable[[], tuple[str, str]] | None = None,
    upload_catalog: Callable[[dict[str, Any]], tuple[bool, str]] | None = None,
) -> FeedbackSendResult:
    """Le o feedback.json, acrescenta o item e grava. Versao so depois do envio.

    Os ganchos existem para o teste. Sem eles, um WebLogin faz a leitura,
    o envio do feedback.json e a gravacao do catalog.json.
    """
    body = (texto or "").strip()
    if not body:
        return FeedbackSendResult(ok=False, message=_EMPTY_ERROR)
    url = (feedback_url or "").strip()
    if not url:
        return FeedbackSendResult(ok=False, message=_SEND_ERROR)
    item = feedback_item(
        usuario=current_windows_login() if usuario is None else usuario,
        quando=feedback_timestamp(now),
        app_id=(app_id or "").strip(),
        texto=body,
    )
    hooks = (
        read_feedback is not None
        or upload_feedback is not None
        or fetch_catalog is not None
        or upload_catalog is not None
    )
    if hooks:
        if (
            read_feedback is None
            or upload_feedback is None
            or fetch_catalog is None
            or upload_catalog is None
        ):
            return FeedbackSendResult(ok=False, message=_SEND_ERROR)
        return _submit_with_hooks(
            item,
            read_feedback=read_feedback,
            upload_feedback=upload_feedback,
            fetch_catalog=fetch_catalog,
            upload_catalog=upload_catalog,
        )
    return _submit_live(item, url)


def _submit_with_hooks(
    item: dict[str, str],
    *,
    read_feedback: Callable[[], tuple[str, str]],
    upload_feedback: Callable[[str], tuple[bool, str]],
    fetch_catalog: Callable[[], tuple[str, str]],
    upload_catalog: Callable[[dict[str, Any]], tuple[bool, str]],
) -> FeedbackSendResult:
    raw, err = read_feedback()
    if err:
        return FeedbackSendResult(ok=False, message=_READ_ERROR)
    parsed, invalid = _parse_feedback(raw)
    if invalid:
        return FeedbackSendResult(ok=False, message=invalid)
    payload = json.dumps(append_feedback(parsed, item), indent=2, ensure_ascii=False) + "\n"
    ok, message = upload_feedback(payload)
    if not ok:
        return FeedbackSendResult(ok=False, message=message or _SEND_ERROR)
    return _bump_after_upload(item, fetch_catalog, upload_catalog)


def _bump_after_upload(
    item: dict[str, str],
    fetch_catalog: Callable[[], tuple[str, str]],
    upload_catalog: Callable[[dict[str, Any]], tuple[bool, str]],
) -> FeedbackSendResult:
    text, err = fetch_catalog()
    if err or not (text or "").strip():
        return FeedbackSendResult(ok=False, message=_VERSION_ERROR)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return FeedbackSendResult(ok=False, message=_VERSION_ERROR)
    if not isinstance(data, dict):
        return FeedbackSendResult(ok=False, message=_VERSION_ERROR)
    before = ""
    block = data.get("feedback")
    if isinstance(block, dict):
        before = str(block.get("versao") or "").strip()
    versao = publish_feedback_block(data, uploaded=True)
    after = ""
    updated = data.get("feedback")
    if isinstance(updated, dict):
        after = str(updated.get("versao") or "").strip()
    if not versao or after == before:
        return FeedbackSendResult(ok=False, message=_VERSION_ERROR)
    ok, message = upload_catalog(data)
    if not ok:
        return FeedbackSendResult(ok=False, message=message or _VERSION_ERROR)
    return FeedbackSendResult(ok=True, item=item, versao=versao)


def _parse_feedback(raw: str) -> tuple[Any, str]:
    text = raw or ""
    if text.lstrip().startswith("<"):
        return None, _READ_ERROR
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, _INVALID_ERROR
    try:
        feedback_item_list(data)
    except ValueError:
        return None, _INVALID_ERROR
    return data, ""


def _download_feedback(session: PnPWebLoginSession, url: str) -> tuple[str, str]:
    folder = tempfile.mkdtemp(prefix="suite-feedback-")
    text = ""
    err = ""
    try:
        result = baixar_do_sharepoint(
            link=url,
            pasta_destino=folder,
            nome_arquivo="feedback.json",
            session=session,
        )
        path = getattr(result, "path", None)
        if not getattr(result, "ok", False) or path is None or not path.is_file():
            err = _READ_ERROR
        else:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                err = _READ_ERROR
    except Exception:
        err = _READ_ERROR
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if err:
        return "", err
    _data, invalid = _parse_feedback(text)
    if invalid:
        return "", invalid
    return text, ""


def _upload_feedback(session: PnPWebLoginSession, url: str, body: str) -> tuple[bool, str]:
    try:
        info = parsear_link_sharepoint(url)
    except ValueError:
        return False, _SEND_ERROR
    if info.get("tipo") != "unique_id":
        return False, _SEND_ERROR
    folder = tempfile.mkdtemp(prefix="suite-feedback-")
    dest = Path(folder) / "feedback.json"
    try:
        dest.write_text(body, encoding="utf-8")
        result = enviar_por_unique_id(
            dest,
            site_url=str(info.get("site_url") or ""),
            unique_id=str(info.get("unique_id") or ""),
            session=session,
        )
        if not getattr(result, "ok", False):
            return False, _SEND_ERROR
        return True, ""
    except Exception:
        return False, _SEND_ERROR
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _submit_live(item: dict[str, str], url: str) -> FeedbackSendResult:
    cat_url = config.REMOTE_CATALOG_URL
    if not cat_url:
        return FeedbackSendResult(ok=False, message=_SEND_ERROR)
    try:
        site = str(parsear_link_sharepoint(cat_url).get("site_url") or "")
    except ValueError:
        return FeedbackSendResult(ok=False, message=_SEND_ERROR)
    if not site:
        return FeedbackSendResult(ok=False, message=_SEND_ERROR)
    session = PnPWebLoginSession(site)
    try:
        start_err = session.start()
        if start_err:
            return FeedbackSendResult(ok=False, message=_SEND_ERROR)
        raw, err = _download_feedback(session, url)
        if err:
            return FeedbackSendResult(ok=False, message=err)
        parsed, invalid = _parse_feedback(raw)
        if invalid:
            return FeedbackSendResult(ok=False, message=invalid)
        body = json.dumps(append_feedback(parsed, item), indent=2, ensure_ascii=False) + "\n"
        ok, message = _upload_feedback(session, url, body)
        if not ok:
            return FeedbackSendResult(ok=False, message=message or _SEND_ERROR)

        published: list[CatalogData] = []

        def fetch() -> tuple[str, str]:
            return fetch_remote_catalog_text(session=session)

        def upload(data: dict[str, Any]) -> tuple[bool, str]:
            outcome = _upload_catalog_text(data, None, session=session)
            if outcome.ok and outcome.catalog is not None:
                published.append(outcome.catalog)
            return outcome.ok, outcome.message or _VERSION_ERROR

        result = _bump_after_upload(item, fetch, upload)
        if published:
            result.catalog = published[-1]
        return result
    finally:
        session.close()


@dataclass
class FeedbackEntry:
    """Um item do feedback.json, na ordem em que foi lido."""

    usuario: str
    quando: str
    app_id: str
    texto: str


@dataclass
class FeedbackCatalogState:
    """Aba Feedback: ponteiro do arquivo e a lista so para ver."""

    url: str = ""
    dest_folder: str = ""
    local_path: str = ""
    local_name: str = ""
    introducao: str = ""
    entries: list[FeedbackEntry] = field(default_factory=list)
    loaded_url: str = ""
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
        return bool((self.url or "").strip() or (self.local_path or "").strip())


def parse_feedback_entries(data: Any) -> list[FeedbackEntry]:
    """Le a lista do feedback.json. Formato errado levanta ValueError."""
    raw_items = feedback_item_list(data)
    entries: list[FeedbackEntry] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        entries.append(
            FeedbackEntry(
                usuario=str(item.get("usuario") or ""),
                quando=str(item.get("quando") or ""),
                app_id=str(item.get("app_id") or ""),
                texto=str(item.get("texto") or ""),
            )
        )
    return entries


def read_feedback_document(path: Path) -> list[FeedbackEntry]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_feedback_entries(data)


def _entries_from_text(text: str) -> tuple[list[FeedbackEntry], str]:
    if (text or "").lstrip().startswith("<"):
        return [], _READ_ERROR
    try:
        return parse_feedback_entries(json.loads(text)), ""
    except (json.JSONDecodeError, ValueError, TypeError):
        return [], _INVALID_ERROR


def should_download_feedback(
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


def read_saved_feedback_version(path: Path | None = None) -> str:
    version_path = path or config.FEEDBACK_VERSION_FILE
    try:
        return version_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_saved_feedback_version(versao: str, path: Path | None = None) -> None:
    version_path = path or config.FEEDBACK_VERSION_FILE
    version_path.parent.mkdir(parents=True, exist_ok=True)
    version_path.write_text((versao or "").strip(), encoding="utf-8")


def load_local_feedback(path: Path | None = None) -> list[FeedbackEntry]:
    """Le a copia local. Arquivo ausente ou invalido vira lista vazia."""
    feedback_path = path or config.FEEDBACK_FILE
    if not feedback_path.is_file():
        return []
    try:
        return read_feedback_document(feedback_path)
    except (OSError, json.JSONDecodeError, ValueError, TypeError, UnicodeError):
        return []


def _quiet_unlink(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _download_feedback_file(url: str, dest: Path) -> Any:
    dest.parent.mkdir(parents=True, exist_ok=True)
    return baixar_do_sharepoint(
        link=url,
        pasta_destino=dest.parent,
        nome_arquivo=dest.name,
    )


def sync_feedback(
    catalog: CatalogData,
    *,
    download: Callable[[str, Path], Any] | None = None,
    feedback_path: Path | None = None,
    version_path: Path | None = None,
) -> str:
    """``skipped``, ``downloaded`` ou ``failed``.

    Falha nao levanta e nao apaga a copia anterior. A versao local
    so muda depois que o arquivo novo foi gravado.
    """
    info = catalog.feedback
    dest = feedback_path or config.FEEDBACK_FILE
    version_dest = version_path or config.FEEDBACK_VERSION_FILE
    saved = read_saved_feedback_version(version_dest)
    if not should_download_feedback(
        url=info.url,
        versao=info.versao,
        saved_versao=saved,
        local_exists=dest.is_file(),
    ):
        return "skipped"
    partial = dest.with_name(dest.name + ".partial")
    _quiet_unlink(partial)
    downloader = download or _download_feedback_file
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
        parse_feedback_entries(json.loads(text))
        dest.parent.mkdir(parents=True, exist_ok=True)
        writing = dest.with_name(dest.name + ".writing")
        writing.write_text(text, encoding="utf-8")
        writing.replace(dest)
        write_saved_feedback_version(info.versao.strip(), version_dest)
    except Exception:
        return "failed"
    finally:
        _quiet_unlink(partial)
    return "downloaded"


def load_feedback_document(url: str) -> tuple[list[FeedbackEntry], str]:
    """Baixa o feedback.json (PnP) so para mostrar a lista. Nao grava de volta."""
    link = (url or "").strip()
    if not link:
        return [], "Cole o link do feedback.json."
    folder = tempfile.mkdtemp(prefix="suite-feedback-")
    try:
        result = baixar_do_sharepoint(
            link=link,
            pasta_destino=folder,
            nome_arquivo="feedback.json",
        )
        path = getattr(result, "path", None)
        if not getattr(result, "ok", False) or path is None or not path.is_file():
            return [], _READ_ERROR
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return [], _READ_ERROR
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return _entries_from_text(text)


def _parse_quando(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def ordered_feedback_entries(entries: list[FeedbackEntry]) -> list[FeedbackEntry]:
    """Mais recente primeiro, se toda data puder ser lida. Senao, a ordem do arquivo."""
    moments = [_parse_quando(item.quando) for item in entries]
    if not entries or any(moment is None for moment in moments):
        return list(entries)
    ranked = sorted(
        enumerate(entries),
        key=lambda pair: (moments[pair[0]], pair[0]),
        reverse=True,
    )
    return [item for _index, item in ranked]


def feedback_app_label(entry: FeedbackEntry, names: dict[str, str] | None = None) -> str:
    """Nome do app no catalogo. Sem nome, fica o app_id."""
    found = ((names or {}).get(entry.app_id) or "").strip()
    return found or entry.app_id


def save_feedback_pointer(
    form: FeedbackCatalogState,
    *,
    expected_fingerprint: str,
    progress: ProgressCb | None = None,
    fetch_text: Callable[[], tuple[str, str]] | None = None,
    upload_catalog: Callable[[dict[str, Any]], PublishOutcome] | None = None,
) -> PublishOutcome:
    """Grava introducao e o ponteiro no catalog.json. Nao regrava a lista.

    A url colada entra como foi colada. A versao sobe 1 so se o catalogo subir.
    """

    def report(pct: float, msg: str) -> None:
        if progress:
            progress(pct, msg)

    stored = (form.url or "").strip()
    if not stored:
        return PublishOutcome(ok=False, message="Cole o link do feedback.json.")

    def _apply(text: str) -> PublishOutcome | tuple[dict[str, Any], str]:
        remote_fp = catalog_fingerprint(text)
        if expected_fingerprint and remote_fp != expected_fingerprint:
            return PublishOutcome(
                ok=False,
                conflict=True,
                message=(
                    "O catalogo remoto mudou desde que esta tela abriu. "
                    "Reabra o catalogo e tente de novo."
                ),
                fingerprint=remote_fp,
            )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return PublishOutcome(ok=False, message=f"Catalogo remoto invalido: {exc}")
        if not isinstance(data, dict):
            return PublishOutcome(ok=False, message="Catalogo remoto invalido.")
        publish_feedback_block(
            data,
            uploaded=True,
            url=stored,
            introducao=form.introducao,
        )
        return data, remote_fp

    if fetch_text is not None or upload_catalog is not None:
        if fetch_text is None or upload_catalog is None:
            return PublishOutcome(ok=False, message="Salvar feedback incompleto.")
        text, err = fetch_text()
        if err:
            return PublishOutcome(ok=False, message=err)
        applied = _apply(text)
        if isinstance(applied, PublishOutcome):
            return applied
        data, _fp = applied
        report(-1.0, "Enviando catalog.json...")
        return upload_catalog(data)

    session: PnPWebLoginSession | None = None
    try:
        cat_url = config.REMOTE_CATALOG_URL
        if not cat_url:
            return PublishOutcome(ok=False, message="catalog.remote_url nao configurado.")
        try:
            site = str(parsear_link_sharepoint(cat_url).get("site_url") or "")
        except ValueError as exc:
            return PublishOutcome(ok=False, message=str(exc))
        if not site:
            return PublishOutcome(ok=False, message="Site do catalog.remote_url nao determinado.")
        session = PnPWebLoginSession(site, progress=report)
        start_err = session.start()
        if start_err:
            return PublishOutcome(ok=False, message=start_err)
        report(-1.0, "Relendo catalogo remoto...")
        text, err = fetch_remote_catalog_text(progress=report, session=session)
        if err:
            return PublishOutcome(ok=False, message=err)
        applied = _apply(text)
        if isinstance(applied, PublishOutcome):
            return applied
        data, _fp = applied
        report(-1.0, "Enviando catalog.json...")
        return _upload_catalog_text(data, report, session=session)
    finally:
        if session is not None:
            session.close()
