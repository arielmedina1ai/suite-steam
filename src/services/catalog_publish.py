"""Publicacao de apps no catalog.json remoto (PnP WebLogin)."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
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


KEEP_FOLDER = "__keep__"
ROOT_FOLDER = "__root__"
NEW_FOLDER = "__new__"


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
    current_download: str = ""
    current_capa: str = ""
    current_icone: str = ""
    original_gerencia_id: str = ""
    folder_choice: str = ROOT_FOLDER
    new_folder_name: str = ""
    folders: list[str] = field(default_factory=list)
    folders_busy: bool = False
    folders_error: str = ""
    baseline: dict[str, str] = field(default_factory=dict)
    show_form: bool = True
    fingerprint: str = ""
    busy: bool = False
    conflict: bool = False
    message: str = ""
    progress: float | None = None

    def capture_baseline(self) -> None:
        self.baseline = {
            "nome": self.nome,
            "descricao": self.descricao,
            "versao": self.versao,
            "tipo": self.tipo,
            "gerencia_id": self.gerencia_id,
            "setor_id": self.setor_id,
            "sub_setor_id": self.sub_setor_id,
            "upload_url": self.upload_url,
            "folder_choice": self.folder_choice,
            "new_folder_name": self.new_folder_name,
            "app_path": "",
            "capa_path": "",
            "icone_path": "",
        }

    def is_changed(self, key: str) -> bool:
        if key in {"app_path", "capa_path", "icone_path"}:
            return bool((getattr(self, key, "") or "").strip())
        current = getattr(self, key, "") or ""
        original = self.baseline.get(key, "") or ""
        return current != original


@dataclass
class DraftSubSetor:
    orig_id: str = ""
    orig_nome: str = ""
    orig_descricao: str = ""
    id: str = ""
    nome: str = ""
    descricao: str = ""

    def is_changed(self, key: str) -> bool:
        if not self.orig_id:
            return True
        if key == "id":
            return self.id != self.orig_id
        if key == "nome":
            return self.nome != self.orig_nome
        if key == "descricao":
            return self.descricao != self.orig_descricao
        return False


@dataclass
class DraftSetor:
    orig_id: str = ""
    orig_nome: str = ""
    orig_descricao: str = ""
    id: str = ""
    nome: str = ""
    descricao: str = ""
    sub_setores: list[DraftSubSetor] = field(default_factory=list)

    def is_changed(self, key: str) -> bool:
        if not self.orig_id:
            return True
        if key == "id":
            return self.id != self.orig_id
        if key == "nome":
            return self.nome != self.orig_nome
        if key == "descricao":
            return self.descricao != self.orig_descricao
        return False


@dataclass
class DraftGerencia:
    orig_id: str = ""
    orig_nome: str = ""
    orig_descricao: str = ""
    orig_apps: list[str] = field(default_factory=list)
    id: str = ""
    nome: str = ""
    descricao: str = ""
    apps: list[str] = field(default_factory=list)

    def is_changed(self, key: str) -> bool:
        if not self.orig_id:
            return True
        if key == "id":
            return self.id != self.orig_id
        if key == "nome":
            return self.nome != self.orig_nome
        if key == "descricao":
            return self.descricao != self.orig_descricao
        if key == "apps":
            return list(self.apps) != list(self.orig_apps)
        return False


@dataclass
class StructureFormState:
    gerencia_geral: str = "Geral"
    orig_gerencia_geral: str = "Geral"
    gerencias: list[DraftGerencia] = field(default_factory=list)
    setores: list[DraftSetor] = field(default_factory=list)
    sel: str = ""
    fingerprint: str = ""
    busy: bool = False
    conflict: bool = False
    message: str = ""
    progress: float | None = None
    dirty: bool = False


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


def folder_url_for_child(root_url: str, child: str) -> str:
    info = _folder_info(root_url)
    caminho = (info.get("caminho_sp") or "").strip("/")
    leaf = (child or "").strip().strip("/")
    if leaf:
        caminho = f"{caminho}/{leaf}" if caminho else leaf
    return f"{info['site_url']}/{caminho}"


def existing_remote_filename(url: str, fallback: str) -> str:
    raw = (url or "").strip()
    if raw:
        try:
            info = parsear_link_sharepoint(raw)
            nome = str(info.get("nome_arquivo") or "").strip()
            leaf = Path(nome.replace("\\", "/")).name if nome else ""
            if leaf and leaf not in {".", "..", "download.aspx", "download"}:
                return leaf
        except ValueError:
            pass
    return fallback


def resolve_app_upload_folder(form: PublishFormState, existing_url: str) -> tuple[str | None, str]:
    """Pasta de destino do Arquivo. None = manter o local remoto atual."""
    choice = (form.folder_choice or "").strip() or KEEP_FOLDER
    if choice == KEEP_FOLDER:
        if (existing_url or "").strip():
            return None, ""
        choice = ROOT_FOLDER
    root = (config.PUBLISH_FOLDER_URL or "").strip()
    if not root:
        return None, "publish.folder_url nao configurado no settings.json."
    if choice == NEW_FOLDER:
        raw = (form.new_folder_name or "").strip()
        name = slug_from_name(raw)
        if not raw:
            return None, "Informe o nome da nova pasta."
        if not name or name == "app":
            name = raw.replace("/", "-").replace("\\", "-").strip("-") or raw
        try:
            return folder_url_for_child(root, name), ""
        except ValueError as exc:
            return None, str(exc)
    try:
        if choice == ROOT_FOLDER:
            return root, ""
        return folder_url_for_child(root, choice), ""
    except ValueError as exc:
        return None, str(exc)


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


def replace_existing_file(
    local: Path,
    existing_url: str,
    progress: ProgressCb | None = None,
) -> tuple[bool, str]:
    """Sobrescreve o arquivo ja referenciado no catalogo (pasta+nome ou UniqueId)."""
    url = (existing_url or "").strip()
    if not url:
        return False, "Nao ha link compartilhado para substituir."
    try:
        info = parsear_link_sharepoint(url)
    except ValueError as exc:
        return False, f"Link remoto nao reconhecido para substituir: {exc}"
    if info.get("tipo") == "unique_id":
        result = enviar_por_unique_id(
            local,
            site_url=str(info.get("site_url") or ""),
            unique_id=str(info.get("unique_id") or ""),
            progress=progress,
        )
        if not result.ok:
            return False, result.message or "Falha ao substituir pelo UniqueId."
        return True, url
    dest_name = str(info.get("nome_arquivo") or "").strip()
    dest_name = Path(dest_name.replace("\\", "/")).name if dest_name else ""
    if not dest_name or dest_name in {".", ".."}:
        return False, "Link remoto sem nome de arquivo para substituir."
    staged = _copy_named(local, dest_name)
    try:
        result = enviar_para_sharepoint(
            staged,
            url,
            nome_arquivo=dest_name,
            progress=progress,
        )
        if not result.ok:
            return False, result.message or "Falha ao substituir o arquivo remoto."
        return True, url
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

    folder_url = (config.PUBLISH_FOLDER_URL or "").strip()

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
    download_url = str(current.get("download_url") or form.current_download or "").strip()
    imagem = str(current.get("imagem") or form.current_capa or "").strip()
    icone_url = str(current.get("icone") or form.current_icone or "").strip()
    imagem_versao = str(current.get("imagem_versao") or "1")
    icone_versao = str(current.get("icone_versao") or "1")

    needs_new_media = any(
        local is not None and not existing
        for local, existing in (
            (capa, imagem),
            (icone, icone_url),
        )
    )
    app_folder_url: str | None = None
    keep_app_location = True
    if app_path is not None:
        app_folder_url, folder_err = resolve_app_upload_folder(form, download_url)
        if folder_err:
            return PublishOutcome(ok=False, message=folder_err)
        keep_app_location = app_folder_url is None
        if not keep_app_location and not app_folder_url:
            return PublishOutcome(ok=False, message="Pasta de destino do arquivo nao determinada.")

    if (needs_new_media or (app_path is not None and not keep_app_location)) and not folder_url:
        return PublishOutcome(
            ok=False,
            message="publish.folder_url nao configurado no settings.json.",
        )

    def _put_to(local: Path, dest_name: str, dest_folder: str, kind: str, msg: str) -> tuple[bool, str]:
        report(-1.0, msg)
        ok, message = _upload_named(local, dest_name, dest_folder, report)
        if not ok:
            return False, message
        try:
            meta = _folder_info(dest_folder)
        except ValueError as exc:
            return False, str(exc)
        url = sharing_url(
            meta["site_url"],
            meta["caminho_sp"],
            dest_name,
            kind,
        )
        return True, url

    def _send_media(local: Path, existing: str, dest_name: str, kind: str, msg: str) -> tuple[bool, str]:
        if existing:
            report(-1.0, msg)
            return replace_existing_file(local, existing, report)
        return _put_to(local, dest_name, folder_url, kind, msg)

    if app_path is not None:
        dest_name = existing_remote_filename(
            download_url,
            f"{app_id}{_ext_for_tipo(tipo, app_path)}",
        )
        if keep_app_location:
            report(-1.0, "Enviando arquivo do aplicativo...")
            ok, payload = replace_existing_file(app_path, download_url, report)
        else:
            assert app_folder_url is not None
            ok, payload = _put_to(
                app_path,
                dest_name,
                app_folder_url,
                _app_kind(tipo),
                "Enviando arquivo do aplicativo...",
            )
        if not ok:
            return PublishOutcome(ok=False, message=payload or "Falha no upload do aplicativo.")
        download_url = payload
    if capa is not None:
        dest_name = existing_remote_filename(
            imagem,
            f"{app_id}-capa{capa.suffix.lower() or '.png'}",
        )
        ok, payload = _send_media(capa, imagem, dest_name, "image", "Enviando capa...")
        if not ok:
            return PublishOutcome(ok=False, message=payload or "Falha no upload da capa.")
        imagem = payload
        imagem_versao = bump_media_version(imagem_versao)
    if icone is not None:
        dest_name = existing_remote_filename(
            icone_url,
            f"{app_id}-icone{icone.suffix.lower() or '.png'}",
        )
        ok, payload = _send_media(icone, icone_url, dest_name, "image", "Enviando icone...")
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


def structure_from_catalog(catalog: CatalogData, fingerprint: str = "") -> StructureFormState:
    geral = (catalog.gerencia_geral or "").strip() or "Geral"
    return StructureFormState(
        gerencia_geral=geral,
        orig_gerencia_geral=geral,
        gerencias=[
            DraftGerencia(
                orig_id=g.id,
                orig_nome=g.nome,
                orig_descricao=g.descricao,
                orig_apps=list(g.apps),
                id=g.id,
                nome=g.nome,
                descricao=g.descricao,
                apps=list(g.apps),
            )
            for g in catalog.gerencias
        ],
        setores=[
            DraftSetor(
                orig_id=s.id,
                orig_nome=s.nome,
                orig_descricao=s.descricao,
                id=s.id,
                nome=s.nome,
                descricao=s.descricao,
                sub_setores=[
                    DraftSubSetor(
                        orig_id=sub.id,
                        orig_nome=sub.nome,
                        orig_descricao=sub.descricao,
                        id=sub.id,
                        nome=sub.nome,
                        descricao=sub.descricao,
                    )
                    for sub in s.sub_setores
                ],
            )
            for s in catalog.setores
        ],
        fingerprint=fingerprint,
    )


def _upload_catalog_text(data: dict[str, Any], progress: ProgressCb | None) -> PublishOutcome:
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
        result = upload_catalog_json(tmp_path, progress=progress)
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


def _fill_ids(nome: str, current_id: str, existing: set[str]) -> str:
    cid = (current_id or "").strip()
    if cid and cid not in existing:
        return cid
    return unique_app_id(nome or cid or "item", existing)


def save_catalog_structure(
    form: StructureFormState,
    *,
    expected_fingerprint: str,
    progress: ProgressCb | None = None,
) -> PublishOutcome:
    def report(pct: float, msg: str) -> None:
        if progress:
            progress(pct, msg)

    g_ids: set[str] = set()
    gerencias_out: list[dict[str, Any]] = []
    for g in form.gerencias:
        nome = (g.nome or "").strip() or (g.id or "").strip()
        if not nome:
            return PublishOutcome(ok=False, message="Toda gerencia precisa de nome.")
        gid = _fill_ids(nome, g.id, g_ids)
        g_ids.add(gid)
        g.id = gid
        gerencias_out.append(
            {
                "id": gid,
                "nome": nome,
                "descricao": (g.descricao or "").strip(),
                "apps": [a for a in g.apps if a],
            }
        )

    s_ids: set[str] = set()
    setor_map: dict[str, str] = {}
    sub_map: dict[tuple[str, str], str] = {}
    setores_out: list[dict[str, Any]] = []
    for s in form.setores:
        nome = (s.nome or "").strip() or (s.id or "").strip()
        if not nome:
            return PublishOutcome(ok=False, message="Todo setor precisa de nome.")
        sid = _fill_ids(nome, s.id, s_ids)
        s_ids.add(sid)
        s.id = sid
        if s.orig_id:
            setor_map[s.orig_id] = sid
        sub_ids: set[str] = set()
        subs_out: list[dict[str, Any]] = []
        for sub in s.sub_setores:
            snome = (sub.nome or "").strip() or (sub.id or "").strip()
            if not snome:
                return PublishOutcome(ok=False, message="Todo sub-setor precisa de nome.")
            sub_id = _fill_ids(snome, sub.id, sub_ids)
            sub_ids.add(sub_id)
            sub.id = sub_id
            if s.orig_id and sub.orig_id:
                sub_map[(s.orig_id, sub.orig_id)] = sub_id
            subs_out.append(
                {
                    "id": sub_id,
                    "nome": snome,
                    "descricao": (sub.descricao or "").strip(),
                }
            )
        setores_out.append(
            {
                "id": sid,
                "nome": nome,
                "descricao": (s.descricao or "").strip(),
                "sub_setores": subs_out,
            }
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

    apps = data.get("apps")
    if isinstance(apps, list):
        for item in apps:
            if not isinstance(item, dict):
                continue
            old_setor = str(item.get("setor") or "").strip()
            old_sub = str(item.get("sub_setor") or "").strip()
            if old_setor in setor_map:
                item["setor"] = setor_map[old_setor]
            mapped_sub = sub_map.get((old_setor, old_sub))
            if mapped_sub:
                item["sub_setor"] = mapped_sub

    geral = (form.gerencia_geral or "").strip() or "Geral"
    data["gerencia_geral"] = geral
    data["gerencias"] = gerencias_out
    data["setores"] = setores_out

    report(-1.0, "Enviando catalog.json...")
    return _upload_catalog_text(data, report)
