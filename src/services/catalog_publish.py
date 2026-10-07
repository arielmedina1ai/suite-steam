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
from catalog.provider import hydrate_catalog_images
from models import CatalogData, parse_catalog_dict
from services.tutorial import (
    apply_tutorial_uploads,
    tutorial_has_local_files,
    validate_tutorial_local_files,
    video_row,
)
from services.sharepoint_manager import (
    PnPWebLoginSession,
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
    preview_capa: str = ""
    preview_icone: str = ""
    tutorial_markdown_url: str = ""
    tutorial_markdown_path: str = ""
    tutorial_videos: list[tuple] = field(default_factory=list)
    select_scroll: float = 0.0
    edit_scroll: float = 0.0
    hold_scroll: bool = False
    original_gerencia_id: str = ""
    folder_choice: str = ROOT_FOLDER
    new_folder_name: str = ""
    move_files: bool = False
    folders: list[str] = field(default_factory=list)
    folders_busy: bool = False
    folders_error: str = ""
    baseline: dict[str, str] = field(default_factory=dict)
    show_form: bool = True
    fingerprint: str = ""
    busy: bool = False
    conflict: bool = False
    message: str = ""
    notice: str = ""
    notice_ok: bool = False
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
            "move_files": "1" if self.move_files else "0",
            "app_path": "",
            "capa_path": "",
            "icone_path": "",
            "tutorial_markdown_path": "",
            "current_download": self.current_download,
            "current_capa": self.current_capa,
            "current_icone": self.current_icone,
            "tutorial_markdown_url": self.tutorial_markdown_url,
            "tutorial_videos": _videos_token(self.tutorial_videos),
        }

    def is_changed(self, key: str) -> bool:
        if key in {"app_path", "capa_path", "icone_path", "tutorial_markdown_path"}:
            return bool((getattr(self, key, "") or "").strip())
        if key == "tutorial_videos":
            return _videos_token(self.tutorial_videos) != (
                self.baseline.get("tutorial_videos") or "[]"
            )
        if key == "move_files":
            current = "1" if self.move_files else "0"
            original = self.baseline.get(key, "0") or "0"
            return current != original
        current = getattr(self, key, "") or ""
        original = self.baseline.get(key, "") or ""
        return current != original

    def video_part_changed(self, index: int, part: str) -> bool:
        if index < 0 or index >= len(self.tutorial_videos):
            return False
        title, url, local = video_row(self.tutorial_videos[index])
        original = _baseline_videos(self.baseline.get("tutorial_videos") or "[]")
        if index >= len(original):
            return True
        orig_title, orig_url, orig_local = original[index]
        if part == "titulo":
            return title != orig_title
        if part == "local":
            return local != orig_local
        return url != orig_url


def _videos_token(videos: list) -> str:
    return json.dumps(
        [[titulo, url, local] for titulo, url, local in (video_row(item) for item in videos)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _baseline_videos(raw: str) -> list[tuple[str, str, str]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [video_row(item) for item in data if isinstance(item, list)]


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
    notice: str = ""
    notice_ok: bool = False
    progress: float | None = None
    dirty: bool = False
    select_scroll: float = 0.0
    edit_scroll: float = 0.0
    hold_scroll: bool = False


@dataclass
class PublishOutcome:
    ok: bool
    message: str
    conflict: bool = False
    catalog: CatalogData | None = None
    fingerprint: str = ""
    app_id: str = ""


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


def catalog_http_url(value: str) -> str:
    """URL http(s) de catalog.json; ignora path local de cache de midia."""
    raw = (value or "").strip()
    if raw.lower().startswith(("http://", "https://")):
        return raw
    return ""


def catalog_json_media_urls(app_id: str) -> tuple[str, str]:
    """Le `imagem` e `icone` do catalog.json em cache (nao do path local de midia)."""
    path = config.CATALOG_CACHE_FILE
    alvo = (app_id or "").strip()
    if not alvo or not path.exists():
        return "", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    for item in data.get("apps") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() != alvo:
            continue
        return catalog_http_url(str(item.get("imagem") or "")), catalog_http_url(str(item.get("icone") or ""))
    return "", ""


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
    raw = (value or "").strip() or "1"
    if raw.isdigit():
        return str(int(raw) + 1)
    match = re.match(r"^(\d+)", raw)
    if match:
        return str(int(match.group(1)) + 1)
    return "2"


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


def exact_folder_name(raw: str) -> tuple[str | None, str]:
    name = (raw or "").strip()
    if not name:
        return None, "Informe o nome da nova pasta."
    if "/" in name or "\\" in name:
        return None, "Nome da pasta nao pode conter barras."
    if name in {".", ".."}:
        return None, "Nome da pasta invalido."
    return name, ""


def same_sharepoint_folder(file_url: str, folder_url: str) -> bool:
    raw_file = catalog_http_url(file_url) or (file_url or "").strip()
    raw_folder = catalog_http_url(folder_url) or (folder_url or "").strip()
    if not raw_file or not raw_folder:
        return False
    try:
        file_info = parsear_link_sharepoint(raw_file)
        dest = parsear_link_pasta_sharepoint(raw_folder)
    except ValueError:
        return False
    if file_info.get("tipo") == "unique_id":
        return False
    file_folder = str(file_info.get("caminho_pasta") or "").strip("/").replace("\\", "/")
    dest_folder = str(dest.get("caminho_sp") or "").strip("/").replace("\\", "/")
    site_a = str(file_info.get("site_url") or "").rstrip("/").lower()
    site_b = str(dest.get("site_url") or "").rstrip("/").lower()
    return bool(site_a and site_a == site_b and file_folder.lower() == dest_folder.lower())


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


def original_upload_name(local: Path) -> str:
    raw = str(local)
    name = raw.replace("\\", "/").rstrip("/").split("/")[-1].strip()
    if not name or name in {".", ".."}:
        return "arquivo"
    return name


def folder_url_of_file(file_url: str) -> str:
    info = parsear_link_pasta_sharepoint(file_url)
    site = (info.get("site_url") or "").rstrip("/")
    caminho = (info.get("caminho_sp") or "").strip("/")
    if not site:
        raise ValueError("Link sem site para determinar a pasta.")
    return f"{site}/{caminho}" if caminho else site


def folder_choice_destination(form: PublishFormState, existing_url: str) -> tuple[str | None, str]:
    """Pasta escolhida no dropdown (publish.folder_url). Pasta Destino e upload_url."""
    choice = (form.folder_choice or "").strip() or KEEP_FOLDER
    root = (config.PUBLISH_FOLDER_URL or "").strip()
    if choice == KEEP_FOLDER:
        pasted = catalog_http_url(form.upload_url) or (form.upload_url or "").strip()
        if pasted.lower().startswith(("http://", "https://")):
            return pasted, ""
        for url in (existing_url, form.current_download, form.current_capa, form.current_icone):
            raw = catalog_http_url(url) or (url or "").strip()
            if not raw:
                continue
            try:
                return folder_url_of_file(raw), ""
            except ValueError:
                continue
        if root:
            return root, ""
        return None, "Nao foi possivel determinar a pasta atual. Escolha uma pasta em Pasta Destino."
    if not root:
        return None, "publish.folder_url nao configurado no settings.json."
    if choice == NEW_FOLDER:
        name, name_err = exact_folder_name(form.new_folder_name)
        if name_err:
            return None, name_err
        try:
            return folder_url_for_child(root, name or ""), ""
        except ValueError as exc:
            return None, str(exc)
    try:
        if choice == ROOT_FOLDER:
            return root, ""
        return folder_url_for_child(root, choice), ""
    except ValueError as exc:
        return None, str(exc)


def infer_pasta_destino(*urls: str) -> str:
    for url in urls:
        raw = catalog_http_url(url) or (url or "").strip()
        if not raw:
            continue
        try:
            return folder_url_of_file(raw)
        except ValueError:
            continue
    return (config.PUBLISH_FOLDER_URL or "").strip()


def resolve_pasta_destino(form: PublishFormState, existing_url: str) -> tuple[str | None, str]:
    """Pasta Destino = upload_url, ou pasta escolhida em publish.folder_url."""
    if (form.folder_choice or "").strip() == NEW_FOLDER:
        return folder_choice_destination(form, existing_url)
    pasted = catalog_http_url(form.upload_url) or (form.upload_url or "").strip()
    if pasted.lower().startswith(("http://", "https://")):
        return pasted, ""
    return folder_choice_destination(form, existing_url)


def _upload_named(
    local: Path,
    dest_name: str,
    folder_url: str,
    progress: ProgressCb | None,
    session: PnPWebLoginSession | None = None,
) -> tuple[bool, str]:
    staged = _copy_named(local, dest_name)
    try:
        result = enviar_para_sharepoint(
            staged,
            folder_url,
            nome_arquivo=dest_name,
            progress=progress,
            session=session,
        )
        return result.ok, result.message
    finally:
        try:
            shutil.rmtree(staged.parent, ignore_errors=True)
        except OSError:
            pass


def _create_chosen_folder(
    form: PublishFormState,
    dest_folder: str,
    session: PnPWebLoginSession,
) -> str:
    """Cria a pasta nova no SharePoint. Erro se falhar; nao ignora."""
    if (form.folder_choice or "").strip() != NEW_FOLDER:
        return ""
    name, name_err = exact_folder_name(form.new_folder_name)
    if name_err:
        return name_err
    root = (config.PUBLISH_FOLDER_URL or "").strip()
    if not root:
        return "publish.folder_url nao configurado no settings.json."
    try:
        parent = parsear_link_pasta_sharepoint(root)
    except ValueError as exc:
        return str(exc)
    result = session.create_folder(parent, name or "")
    if not result.ok:
        return result.message or "Falha ao criar a pasta no SharePoint."
    return ""


def _relocate_catalog_file(
    file_url: str,
    dest_folder: str,
    kind: str,
    session: PnPWebLoginSession,
) -> tuple[str | None, str]:
    """Move o arquivo remoto para dest. None = manter URL atual. Erro em str."""
    raw = catalog_http_url(file_url) or (file_url or "").strip()
    if not raw.lower().startswith(("http://", "https://")):
        return None, ""
    if same_sharepoint_folder(raw, dest_folder):
        return None, ""
    result = session.move_remote(raw, dest_folder)
    if not result.ok:
        return None, result.message or "Falha ao mover arquivo no SharePoint."
    if result.skipped:
        return None, ""
    name = (result.remote_name or "").strip()
    if not name:
        try:
            info = parsear_link_sharepoint(raw)
            name = str(info.get("nome_arquivo") or "").strip()
        except ValueError:
            name = ""
    if not name:
        return None, "Nao foi possivel determinar o nome do arquivo apos mover."
    try:
        meta = _folder_info(dest_folder)
    except ValueError as exc:
        return None, str(exc)
    return sharing_url(meta["site_url"], meta["caminho_sp"], name, kind), ""


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


def fetch_remote_catalog_text(
    progress: ProgressCb | None = None,
    session: PnPWebLoginSession | None = None,
) -> tuple[str, str]:
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
        session=session,
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


def upload_catalog_json(
    local: Path,
    progress: ProgressCb | None = None,
    session: PnPWebLoginSession | None = None,
):
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
            session=session,
        )
    nome = info.get("nome_arquivo") or "catalog.json"
    return enviar_para_sharepoint(
        local, url, nome_arquivo=str(nome), progress=progress, session=session
    )


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
    pasted_download = catalog_http_url(form.current_download)
    if is_new and (app_path is None or not app_path.is_file()) and not pasted_download:
        return PublishOutcome(ok=False, message="Escolha o arquivo do aplicativo ou cole o link em Arquivo.")
    if app_path is not None and not app_path.is_file():
        return PublishOutcome(ok=False, message="Arquivo do aplicativo nao encontrado.")
    capa = Path(form.capa_path) if form.capa_path else None
    icone = Path(form.icone_path) if form.icone_path else None
    for label, path in (("capa", capa), ("icone", icone), ("app", app_path)):
        if path is not None and not path.is_file():
            return PublishOutcome(ok=False, message=f"Arquivo de {label} nao encontrado.")
    tutorial_err = validate_tutorial_local_files(
        form.tutorial_markdown_path, form.tutorial_videos
    )
    if tutorial_err:
        return PublishOutcome(ok=False, message=tutorial_err)
    tutorial_upload = tutorial_has_local_files(
        form.tutorial_markdown_path, form.tutorial_videos
    )

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
        imagem = catalog_http_url(str(current.get("imagem") or ""))
        icone_url = catalog_http_url(str(current.get("icone") or ""))
        imagem_versao = str(current.get("imagem_versao") or "1")
        icone_versao = str(current.get("icone_versao") or "1")

        chosen, folder_err = resolve_pasta_destino(form, download_url)
        if folder_err and (
            (form.folder_choice or "").strip() == NEW_FOLDER
            or form.move_files
            or app_path is not None
            or capa is not None
            or icone is not None
            or tutorial_upload
        ):
            return PublishOutcome(ok=False, message=folder_err)
        dest_folder = chosen or ""
        if (form.folder_choice or "").strip() == NEW_FOLDER:
            if not dest_folder:
                return PublishOutcome(ok=False, message=folder_err or "Informe o nome da nova pasta.")
            report(-1.0, "Criando pasta no SharePoint...")
            create_err = _create_chosen_folder(form, dest_folder, session)
            if create_err:
                return PublishOutcome(ok=False, message=create_err)
        elif form.move_files and not dest_folder:
            return PublishOutcome(ok=False, message=folder_err or "Informe a Pasta Destino para mover os arquivos.")
        elif (
            app_path is not None or capa is not None or icone is not None or tutorial_upload
        ) and not dest_folder:
            return PublishOutcome(ok=False, message="Informe a Pasta Destino dos arquivos.")

        def _put_to(local: Path, dest_name: str, dest_folder_url: str, kind: str, msg: str) -> tuple[bool, str]:
            report(-1.0, msg)
            ok, message = _upload_named(
                local, dest_name, dest_folder_url, report, session=session
            )
            if not ok:
                return False, message
            try:
                meta = _folder_info(dest_folder_url)
            except ValueError as exc:
                return False, str(exc)
            url = sharing_url(
                meta["site_url"],
                meta["caminho_sp"],
                dest_name,
                kind,
            )
            return True, url

        pasted_download = catalog_http_url(form.current_download)
        if pasted_download:
            download_url = pasted_download
        pasted_capa = catalog_http_url(form.current_capa)
        if pasted_capa:
            imagem = pasted_capa
        pasted_icone = catalog_http_url(form.current_icone)
        if pasted_icone:
            icone_url = pasted_icone

        if form.move_files and dest_folder:
            if app_path is None and download_url:
                report(-1.0, "Movendo arquivo do aplicativo...")
                moved, move_err = _relocate_catalog_file(
                    download_url, dest_folder, _app_kind(tipo), session
                )
                if move_err:
                    return PublishOutcome(ok=False, message=move_err)
                if moved:
                    download_url = moved
            if capa is None and imagem:
                report(-1.0, "Movendo capa...")
                moved, move_err = _relocate_catalog_file(
                    imagem, dest_folder, "image", session
                )
                if move_err:
                    return PublishOutcome(ok=False, message=move_err)
                if moved:
                    imagem = moved
                    imagem_versao = bump_media_version(imagem_versao)
            if icone is None and icone_url:
                report(-1.0, "Movendo icone...")
                moved, move_err = _relocate_catalog_file(
                    icone_url, dest_folder, "image", session
                )
                if move_err:
                    return PublishOutcome(ok=False, message=move_err)
                if moved:
                    icone_url = moved
                    icone_versao = bump_media_version(icone_versao)

        if app_path is not None:
            ok, payload = _put_to(
                app_path,
                original_upload_name(app_path),
                dest_folder,
                _app_kind(tipo),
                "Enviando arquivo do aplicativo...",
            )
            if not ok:
                return PublishOutcome(ok=False, message=payload or "Falha no upload do aplicativo.")
            download_url = payload
        if capa is not None:
            ok, payload = _put_to(
                capa,
                original_upload_name(capa),
                dest_folder,
                "image",
                "Enviando capa...",
            )
            if not ok:
                return PublishOutcome(ok=False, message=payload or "Falha no upload da capa.")
            imagem = payload
            imagem_versao = bump_media_version(imagem_versao)
        if icone is not None:
            ok, payload = _put_to(
                icone,
                original_upload_name(icone),
                dest_folder,
                "image",
                "Enviando icone...",
            )
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
        upload_url = dest_folder if (form.folder_choice or "").strip() == NEW_FOLDER else (form.upload_url or "").strip() or dest_folder
        if upload_url:
            entry["upload_url"] = upload_url
        elif "upload_url" in current:
            entry["upload_url"] = ""
        def _upload_tutorial(local: Path, msg: str) -> tuple[bool, str]:
            return _put_to(
                local,
                original_upload_name(local),
                dest_folder,
                "file",
                msg,
            )

        tutorial_block, tutorial_err = apply_tutorial_uploads(
            form.tutorial_markdown_url,
            form.tutorial_markdown_path,
            form.tutorial_videos,
            _upload_tutorial,
        )
        if tutorial_err or tutorial_block is None:
            return PublishOutcome(ok=False, message=tutorial_err or "Falha no tutorial.")
        entry["tutorial"] = tutorial_block

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
            result = upload_catalog_json(tmp_path, progress=report, session=session)
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
        hydrate_catalog_images(
            catalog,
            seed_app_id=app_id,
            capa_local=capa,
            icone_local=icone,
        )
        return PublishOutcome(
            ok=True,
            message="Catalogo publicado.",
            catalog=catalog,
            fingerprint=catalog_fingerprint(new_text),
            app_id=app_id,
        )
    finally:
        if session is not None:
            session.close()


def remove_app_entry(data: dict[str, Any], app_id: str) -> None:
    alvo = (app_id or "").strip()
    apps = data.get("apps")
    if isinstance(apps, list):
        data["apps"] = [
            item
            for item in apps
            if not (isinstance(item, dict) and str(item.get("id") or "").strip() == alvo)
        ]
    for item in data.get("gerencias") or []:
        if not isinstance(item, dict):
            continue
        item["apps"] = [a for a in (item.get("apps") or []) if str(a).strip() != alvo]


@dataclass
class PendingSharePointDelete:
    session: PnPWebLoginSession
    data: dict[str, Any]
    current: dict[str, Any]
    app_id: str
    folder_files: list[str]
    upload_url: str


def _same_folder_url(left: str, right: str) -> bool:
    try:
        a = parsear_link_pasta_sharepoint(left)
        b = parsear_link_pasta_sharepoint(right)
    except ValueError:
        return False
    site_a = str(a.get("site_url") or "").rstrip("/").lower()
    site_b = str(b.get("site_url") or "").rstrip("/").lower()
    path_a = str(a.get("caminho_sp") or "").strip("/").replace("\\", "/").lower()
    path_b = str(b.get("caminho_sp") or "").strip("/").replace("\\", "/").lower()
    return bool(site_a and site_a == site_b and path_a == path_b)


def _folder_files_excluding_catalog_assets(
    names: list[str],
    current: dict[str, Any],
    folder_url: str,
) -> list[str]:
    """Lista a pasta sem o arquivo do app, a capa e o icone se estiverem nela."""
    listed = [(n or "").strip() for n in names if (n or "").strip()]
    listed_lower = {n.lower() for n in listed}
    omit: set[str] = set()
    for key in ("download_url", "imagem", "icone"):
        raw = catalog_http_url(str(current.get(key) or ""))
        if not raw:
            continue
        leaf = existing_remote_filename(raw, "")
        leaf_key = leaf.lower() if leaf else ""
        lives_in = False
        try:
            info = parsear_link_sharepoint(raw)
        except ValueError:
            info = {}
        if info.get("tipo") == "unique_id":
            lives_in = bool(leaf_key and leaf_key in listed_lower)
        elif folder_url:
            lives_in = same_sharepoint_folder(raw, folder_url)
        if lives_in and leaf_key:
            omit.add(leaf_key)
    return [n for n in listed if n.lower() not in omit]


def _delete_entry_sharepoint_files(
    session: PnPWebLoginSession,
    current: dict[str, Any],
    report: ProgressCb,
) -> str:
    urls: list[str] = []
    seen: set[str] = set()
    for key in ("download_url", "imagem", "icone"):
        raw = catalog_http_url(str(current.get(key) or ""))
        if raw and raw not in seen:
            seen.add(raw)
            urls.append(raw)
    for url in urls:
        report(-1.0, "Excluindo arquivo no SharePoint...")
        result = session.delete_remote(url)
        if not result.ok:
            return result.message or "Falha ao excluir arquivo no SharePoint."
    return ""


def abort_prepared_app_delete(pending: PendingSharePointDelete | None) -> None:
    if pending is None:
        return
    try:
        pending.session.close()
    except Exception:
        pass


def complete_prepared_app_delete(
    pending: PendingSharePointDelete,
    *,
    delete_folder: bool,
    progress: ProgressCb | None = None,
) -> PublishOutcome:
    def report(pct: float, msg: str) -> None:
        if progress:
            progress(pct, msg)

    session = pending.session
    try:
        err = _delete_entry_sharepoint_files(session, pending.current, report)
        if err:
            return PublishOutcome(ok=False, message=err)
        if delete_folder and pending.upload_url:
            root = (config.PUBLISH_FOLDER_URL or "").strip()
            if root and _same_folder_url(pending.upload_url, root):
                return PublishOutcome(
                    ok=False,
                    message="A Pasta Destino e a pasta raiz de publicacao e nao pode ser excluida.",
                )
            report(-1.0, "Excluindo Pasta Destino no SharePoint...")
            result = session.delete_folder(pending.upload_url)
            if not result.ok:
                return PublishOutcome(
                    ok=False,
                    message=result.message or "Falha ao excluir a Pasta Destino no SharePoint.",
                )
        remove_app_entry(pending.data, pending.app_id)
        report(-1.0, "Enviando catalog.json...")
        return _upload_catalog_text(pending.data, report, session=session)
    finally:
        session.close()


def prepare_sharepoint_app_delete(
    app_id: str,
    *,
    expected_fingerprint: str,
    progress: ProgressCb | None = None,
) -> tuple[PendingSharePointDelete | None, PublishOutcome | None]:
    def report(pct: float, msg: str) -> None:
        if progress:
            progress(pct, msg)

    alvo = (app_id or "").strip()
    if not alvo:
        return None, PublishOutcome(ok=False, message="Nenhum aplicativo selecionado.")

    session: PnPWebLoginSession | None = None
    try:
        cat_url = config.REMOTE_CATALOG_URL
        if not cat_url:
            return None, PublishOutcome(ok=False, message="catalog.remote_url nao configurado.")
        try:
            site = str(parsear_link_sharepoint(cat_url).get("site_url") or "")
        except ValueError as exc:
            return None, PublishOutcome(ok=False, message=str(exc))
        if not site:
            return None, PublishOutcome(ok=False, message="Site do catalog.remote_url nao determinado.")
        session = PnPWebLoginSession(site, progress=report)
        start_err = session.start()
        if start_err:
            return None, PublishOutcome(ok=False, message=start_err)

        report(-1.0, "Relendo catalogo remoto...")
        text, err = fetch_remote_catalog_text(progress=report, session=session)
        if err:
            return None, PublishOutcome(ok=False, message=err)
        remote_fp = catalog_fingerprint(text)
        if expected_fingerprint and remote_fp != expected_fingerprint:
            return None, PublishOutcome(
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
            return None, PublishOutcome(ok=False, message=f"Catalogo remoto invalido: {exc}")
        if not isinstance(data, dict):
            return None, PublishOutcome(ok=False, message="Catalogo remoto invalido.")

        current: dict[str, Any] | None = None
        for item in data.get("apps") or []:
            if isinstance(item, dict) and str(item.get("id") or "").strip() == alvo:
                current = dict(item)
                break
        if current is None:
            return None, PublishOutcome(ok=False, message="Aplicativo nao encontrado no catalogo remoto.")

        upload_url = catalog_http_url(str(current.get("upload_url") or ""))
        names: list[str] = []
        if upload_url:
            root = (config.PUBLISH_FOLDER_URL or "").strip()
            if root and _same_folder_url(upload_url, root):
                upload_url = ""
            else:
                report(-1.0, "Listando Pasta Destino...")
                listed = session.list_folder_files(upload_url)
                if not listed.ok:
                    return None, PublishOutcome(
                        ok=False,
                        message=listed.message or "Falha ao listar a Pasta Destino.",
                    )
                names = _folder_files_excluding_catalog_assets(
                    list(listed.files),
                    current,
                    upload_url,
                )
        pending = PendingSharePointDelete(
            session=session,
            data=data,
            current=current,
            app_id=alvo,
            folder_files=names,
            upload_url=upload_url,
        )
        session = None
        return pending, None
    finally:
        if session is not None:
            session.close()


def delete_catalog_app(
    app_id: str,
    *,
    expected_fingerprint: str,
    delete_sharepoint_files: bool,
    delete_folder: bool = False,
    progress: ProgressCb | None = None,
) -> PublishOutcome:
    def report(pct: float, msg: str) -> None:
        if progress:
            progress(pct, msg)

    if delete_sharepoint_files:
        pending, early = prepare_sharepoint_app_delete(
            app_id,
            expected_fingerprint=expected_fingerprint,
            progress=progress,
        )
        if early is not None:
            return early
        if pending is None:
            return PublishOutcome(ok=False, message="Falha ao preparar exclusao.")
        return complete_prepared_app_delete(
            pending,
            delete_folder=delete_folder,
            progress=progress,
        )

    alvo = (app_id or "").strip()
    if not alvo:
        return PublishOutcome(ok=False, message="Nenhum aplicativo selecionado.")

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

        current: dict[str, Any] | None = None
        for item in data.get("apps") or []:
            if isinstance(item, dict) and str(item.get("id") or "").strip() == alvo:
                current = dict(item)
                break
        if current is None:
            return PublishOutcome(ok=False, message="Aplicativo nao encontrado no catalogo remoto.")

        remove_app_entry(data, alvo)
        report(-1.0, "Enviando catalog.json...")
        return _upload_catalog_text(data, report, session=session)
    finally:
        if session is not None:
            session.close()


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


def _upload_catalog_text(
    data: dict[str, Any],
    progress: ProgressCb | None,
    session: PnPWebLoginSession | None = None,
) -> PublishOutcome:
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
        result = upload_catalog_json(tmp_path, progress=progress, session=session)
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
    hydrate_catalog_images(catalog)
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
        text, err = fetch_remote_catalog_text(progress=report, session=session)
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

        live_setor_ids = {s.id for s in form.setores}
        kept_setor_orig = {s.orig_id for s in form.setores if s.orig_id}
        kept_sub_orig = {
            (s.orig_id, sub.orig_id)
            for s in form.setores
            for sub in s.sub_setores
            if s.orig_id and sub.orig_id
        }
        apps = data.get("apps")
        if isinstance(apps, list):
            for item in apps:
                if not isinstance(item, dict):
                    continue
                old_setor = str(item.get("setor") or "").strip()
                old_sub = str(item.get("sub_setor") or "").strip()
                if old_setor in setor_map:
                    item["setor"] = setor_map[old_setor]
                elif old_setor and old_setor not in kept_setor_orig and old_setor not in live_setor_ids:
                    item["setor"] = ""
                    item["sub_setor"] = ""
                    old_sub = ""
                mapped_sub = sub_map.get((old_setor, old_sub))
                if mapped_sub:
                    item["sub_setor"] = mapped_sub
                elif old_sub and (old_setor, old_sub) not in kept_sub_orig:
                    item["sub_setor"] = ""

        geral = (form.gerencia_geral or "").strip() or "Geral"
        data["gerencia_geral"] = geral
        data["gerencias"] = gerencias_out
        data["setores"] = setores_out

        report(-1.0, "Enviando catalog.json...")
        return _upload_catalog_text(data, report, session=session)
    finally:
        if session is not None:
            session.close()
