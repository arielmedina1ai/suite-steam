"""Publicacao de apps no catalog.json remoto (PnP WebLogin)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse

import config
from models import CatalogData, parse_catalog_dict
from services.sharepoint_manager import (
    baixar_do_sharepoint,
    enviar_para_sharepoint,
    enviar_por_unique_id,
    parsear_link_pasta_sharepoint,
    parsear_link_sharepoint,
)

ProgressCb = Callable[[float, str], None]


@dataclass
class PublishFormState:
    editing_id: str | None = None
    nome: str = ""
    descricao: str = ""
    versao: str = "1.0.0"
    tipo: str = "exe"
    gerencia_id: str = ""
    setor_id: str = ""
    sub_setor_id: str = ""
    upload_url: str = ""
    app_path: str = ""
    capa_path: str = ""
    icone_path: str = ""
    original_gerencia_id: str = ""
    show_form: bool = False
    fingerprint: str = ""
    busy: bool = False
    conflict: bool = False
    message: str = ""
    progress: float | None = None


@dataclass
class PublishOutcome:
    ok: bool
    message: str
    conflict: bool = False
    catalog: CatalogData | None = None
    fingerprint: str = ""


def catalog_fingerprint(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def fingerprint_cache_file() -> str:
    path = config.CATALOG_CACHE_FILE
    if not path.exists():
        return ""
    try:
        return catalog_fingerprint(path.read_text(encoding="utf-8"))
    except OSError:
        return ""


def slug_from_name(nome: str) -> str:
    raw = unicodedata.normalize("NFKD", nome or "")
    ascii_name = raw.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or "app"


def unique_app_id(nome: str, existing: set[str]) -> str:
    base = slug_from_name(nome)
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def bump_media_version(value: str) -> str:
    raw = (value or "1").strip() or "1"
    if raw.isdigit():
        return str(int(raw) + 1)
    return f"{raw}.1"


def sharing_url(site_url: str, caminho_sp: str, filename: str, kind: str) -> str:
    marker = {"file": "u", "sheet": "x", "image": "i"}.get(kind, "u")
    parsed = urlparse(site_url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    parts.extend(p for p in caminho_sp.replace("\\", "/").split("/") if p)
    parts.append(filename)
    rel = "/" + "/".join(quote(p, safe="") for p in parts)
    return f"{parsed.scheme}://{parsed.netloc}/:{marker}:/r{rel}"


def _copy_named(src: Path, dest_name: str) -> Path:
    folder = Path(tempfile.mkdtemp(prefix="suite-pub-"))
    dest = folder / dest_name
    shutil.copy2(src, dest)
    return dest


def _folder_info(folder_url: str) -> dict[str, str]:
    return parsear_link_pasta_sharepoint(folder_url)


def _upload_named(
    local: Path,
    dest_name: str,
    folder_url: str,
    progress: ProgressCb | None,
) -> tuple[bool, str]:
    staged = _copy_named(local, dest_name)
    try:
        result = enviar_para_sharepoint(
            staged,
            folder_url,
            nome_arquivo=dest_name,
            progress=progress,
        )
        return result.ok, result.message
    finally:
        try:
            shutil.rmtree(staged.parent, ignore_errors=True)
        except OSError:
            pass


def _app_kind(tipo: str) -> str:
    t = (tipo or "exe").strip().lower()
    if t in {"xlsx", "xlsm"}:
        return "sheet"
    return "file"


def _ext_for_tipo(tipo: str, local: Path | None) -> str:
    if local is not None and local.suffix:
        return local.suffix.lower()
    t = (tipo or "exe").strip().lower() or "exe"
    return f".{t}"


def fetch_remote_catalog_text(progress: ProgressCb | None = None) -> tuple[str, str]:
    url = config.REMOTE_CATALOG_URL
    if not url:
        return "", "catalog.remote_url nao configurado."
    dest = config.CATALOG_CACHE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    result = baixar_do_sharepoint(
        link=url,
        pasta_destino=dest,
        nome_arquivo="catalog.json",
        progress=progress,
    )
    if not (result.ok and result.path and result.path.exists()):
        return "", result.message or "Falha ao ler o catalogo remoto."
    try:
        text = result.path.read_text(encoding="utf-8")
    except OSError as exc:
        return "", str(exc)
    if text.lstrip().startswith("<"):
        return "", "Catalogo remoto nao e JSON."
    return text, ""


def upload_catalog_json(local: Path, progress: ProgressCb | None = None):
    url = config.REMOTE_CATALOG_URL
    if not url:
        from services.sharepoint_manager import SharePointResult

        return SharePointResult(ok=False, message="catalog.remote_url nao configurado.")
    try:
        info = parsear_link_sharepoint(url)
    except ValueError:
        info = {}
    if info.get("tipo") == "unique_id":
        return enviar_por_unique_id(
            local,
            site_url=str(info.get("site_url") or ""),
            unique_id=str(info.get("unique_id") or ""),
            progress=progress,
        )
    nome = info.get("nome_arquivo") or "catalog.json"
    return enviar_para_sharepoint(local, url, nome_arquivo=str(nome), progress=progress)


def apply_gerencia_change(
    data: dict[str, Any],
    app_id: str,
    *,
    old_gerencia_id: str,
    new_gerencia_id: str,
) -> None:
    old_id = (old_gerencia_id or "").strip()
    new_id = (new_gerencia_id or "").strip()
    if old_id == new_id:
        if new_id:
            for item in data.get("gerencias") or []:
                if isinstance(item, dict) and str(item.get("id") or "").strip() == new_id:
                    apps = [str(x).strip() for x in (item.get("apps") or []) if str(x).strip()]
                    if app_id not in apps:
                        apps.append(app_id)
                        item["apps"] = apps
                    return
        return
    for item in data.get("gerencias") or []:
        if not isinstance(item, dict):
            continue
        gid = str(item.get("id") or "").strip()
        apps = [str(x).strip() for x in (item.get("apps") or []) if str(x).strip()]
        if gid == old_id:
            apps = [x for x in apps if x != app_id]
        if gid == new_id and app_id not in apps:
            apps.append(app_id)
        item["apps"] = apps


def upsert_app_entry(data: dict[str, Any], entry: dict[str, Any]) -> None:
    apps = data.get("apps")
    if not isinstance(apps, list):
        apps = []
        data["apps"] = apps
    app_id = entry["id"]
    for i, item in enumerate(apps):
        if isinstance(item, dict) and str(item.get("id") or "").strip() == app_id:
            merged = dict(item)
            merged.update(entry)
            apps[i] = merged
            return
    apps.append(entry)


def publish_app(
    form: PublishFormState,
    *,
    expected_fingerprint: str,
    progress: ProgressCb | None = None,
) -> PublishOutcome:
    def report(pct: float, msg: str) -> None:
        if progress:
            progress(pct, msg)

    nome = (form.nome or "").strip()
    if not nome:
        return PublishOutcome(ok=False, message="Informe o nome do aplicativo.")
    is_new = not (form.editing_id or "").strip()
    app_path = Path(form.app_path) if form.app_path else None
    if is_new and (app_path is None or not app_path.is_file()):
        return PublishOutcome(ok=False, message="Escolha o arquivo do aplicativo.")
    if app_path is not None and not app_path.is_file():
        return PublishOutcome(ok=False, message="Arquivo do aplicativo nao encontrado.")
    capa = Path(form.capa_path) if form.capa_path else None
    icone = Path(form.icone_path) if form.icone_path else None
    for label, path in (("capa", capa), ("icone", icone), ("app", app_path)):
        if path is not None and not path.is_file():
            return PublishOutcome(ok=False, message=f"Arquivo de {label} nao encontrado.")

    needs_upload = any(p is not None for p in (app_path, capa, icone))
    folder_url = (config.PUBLISH_FOLDER_URL or "").strip()
    if needs_upload and not folder_url:
        return PublishOutcome(
            ok=False,
            message="publish.folder_url nao configurado no settings.json.",
        )

    report(-1.0, "Relendo catalogo remoto...")
    text, err = fetch_remote_catalog_text(progress=report)
    if err:
        return PublishOutcome(ok=False, message=err)
    remote_fp = catalog_fingerprint(text)
    if expected_fingerprint and remote_fp != expected_fingerprint:
        return PublishOutcome(
            ok=False,
            conflict=True,
            message=(
                "O catalogo remoto mudou desde que esta tela abriu. "
                "Reabra Publicar e tente de novo."
            ),
            fingerprint=remote_fp,
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return PublishOutcome(ok=False, message=f"Catalogo remoto invalido: {exc}")
    if not isinstance(data, dict):
        return PublishOutcome(ok=False, message="Catalogo remoto invalido.")

    existing_ids = {
        str(item.get("id") or "").strip()
        for item in (data.get("apps") or [])
        if isinstance(item, dict)
    }
    app_id = (form.editing_id or "").strip() or unique_app_id(nome, existing_ids)
    current: dict[str, Any] = {}
    for item in data.get("apps") or []:
        if isinstance(item, dict) and str(item.get("id") or "").strip() == app_id:
            current = dict(item)
            break

    tipo = (form.tipo or current.get("tipo") or "exe").strip().lower() or "exe"
    download_url = str(current.get("download_url") or "").strip()
    imagem = str(current.get("imagem") or "").strip()
    icone_url = str(current.get("icone") or "").strip()
    imagem_versao = str(current.get("imagem_versao") or "1")
    icone_versao = str(current.get("icone_versao") or "1")

    folder_meta = None
    if needs_upload:
        try:
            folder_meta = _folder_info(folder_url)
        except ValueError as exc:
            return PublishOutcome(ok=False, message=str(exc))

    def _put(local: Path, dest_name: str, kind: str, msg: str) -> tuple[bool, str]:
        report(-1.0, msg)
        ok, message = _upload_named(local, dest_name, folder_url, report)
        if not ok:
            return False, message
        assert folder_meta is not None
        url = sharing_url(
            folder_meta["site_url"],
            folder_meta["caminho_sp"],
            dest_name,
            kind,
        )
        return True, url

    if app_path is not None:
        dest_name = f"{app_id}{_ext_for_tipo(tipo, app_path)}"
        ok, payload = _put(app_path, dest_name, _app_kind(tipo), f"Enviando {dest_name}...")
        if not ok:
            return PublishOutcome(ok=False, message=payload or "Falha no upload do aplicativo.")
        download_url = payload
    if capa is not None:
        dest_name = f"{app_id}-capa{capa.suffix.lower() or '.png'}"
        ok, payload = _put(capa, dest_name, "image", "Enviando capa...")
        if not ok:
            return PublishOutcome(ok=False, message=payload or "Falha no upload da capa.")
        imagem = payload
        imagem_versao = bump_media_version(imagem_versao)
    if icone is not None:
        dest_name = f"{app_id}-icone{icone.suffix.lower() or '.png'}"
        ok, payload = _put(icone, dest_name, "image", "Enviando icone...")
        if not ok:
            return PublishOutcome(ok=False, message=payload or "Falha no upload do icone.")
        icone_url = payload
        icone_versao = bump_media_version(icone_versao)

    if not download_url:
        return PublishOutcome(ok=False, message="O aplicativo precisa de um arquivo / download_url.")

    entry: dict[str, Any] = {
        "id": app_id,
        "nome": nome,
        "descricao": (form.descricao or "").strip(),
        "setor": (form.setor_id or "").strip(),
        "sub_setor": (form.sub_setor_id or "").strip(),
        "tipo": tipo,
        "versao": (form.versao or "").strip() or "1.0.0",
        "download_url": download_url,
        "imagem": imagem,
        "imagem_versao": imagem_versao,
        "icone": icone_url,
        "icone_versao": icone_versao,
    }
    upload_url = (form.upload_url or "").strip()
    if upload_url:
        entry["upload_url"] = upload_url
    elif "upload_url" in current:
        entry["upload_url"] = ""

    upsert_app_entry(data, entry)
    apply_gerencia_change(
        data,
        app_id,
        old_gerencia_id=form.original_gerencia_id if not is_new else "",
        new_gerencia_id=form.gerencia_id,
    )

    report(-1.0, "Enviando catalog.json...")
    new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix="catalog-",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(new_text)
        tmp_path = Path(tmp.name)
    try:
        result = upload_catalog_json(tmp_path, progress=report)
        if not result.ok:
            return PublishOutcome(
                ok=False,
                message=result.message or "Falha ao enviar catalog.json. O catalogo anterior permanece.",
            )
        config.CATALOG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_path, config.CATALOG_CACHE_FILE)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    catalog = parse_catalog_dict(data)
    return PublishOutcome(
        ok=True,
        message="Catalogo publicado.",
        catalog=catalog,
        fingerprint=catalog_fingerprint(new_text),
    )
