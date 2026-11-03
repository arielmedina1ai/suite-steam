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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import config
from models import CatalogData
from services.catalog_check import as_sao_paulo, sao_paulo_now
from services.catalog_publish import _upload_catalog_text, fetch_remote_catalog_text
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


def append_feedback(data: Any, item: dict[str, str]) -> list[Any]:
    """Acrescenta no fim. Qualquer outro formato e erro — a lista nao encolhe."""
    if not isinstance(data, list):
        raise ValueError(_INVALID_ERROR)
    return [*data, item]


def publish_feedback_block(data: dict[str, Any], *, uploaded: bool) -> str:
    """Soma 1 em feedback.versao so se o feedback.json subiu.

    A url fica como estava. UniqueId colado nao e reescrito.
    ``uploaded`` falso devolve a versao atual e nao mexe no bloco.
    """
    block = data.get("feedback")
    current = ""
    if isinstance(block, dict):
        current = str(block.get("versao") or "").strip()
    if not uploaded or not isinstance(block, dict):
        return current
    raw_url = block.get("url")
    if not isinstance(raw_url, str) or not raw_url.strip() or not current:
        return current
    updated = dict(block)
    updated["url"] = raw_url
    updated["versao"] = bump_dicas_version(current)
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
    if not isinstance(data, list):
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
