"""Tutorial do app: corte do markdown, cache local e bloco do catalogo.

O player nao entra aqui. Este modulo so prepara texto e arquivos.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import config
from services.sharepoint_manager import baixar_do_sharepoint

_H2 = re.compile(r"^##(?!#)\s*(.*?)\s*$")
_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def video_row(item) -> tuple[str, str, str, str]:
    """titulo, url do catalogo, caminho local, nome original do arquivo escolhido."""
    if isinstance(item, (list, tuple)):
        titulo = str(item[0]) if len(item) > 0 else ""
        url = str(item[1]) if len(item) > 1 else ""
        local = str(item[2]) if len(item) > 2 else ""
        nome = str(item[3]) if len(item) > 3 else ""
        return titulo, url, local, nome
    return "", "", "", ""


def with_video_part(item, part: str, value: str) -> tuple[str, str, str, str]:
    """Troca um campo da linha sem perder titulo, url, arquivo local ou nome original."""
    titulo, url, local, nome = video_row(item)
    if part == "titulo":
        return value, url, local, nome
    if part == "url":
        return titulo, value, local, nome
    if part == "nome":
        return titulo, url, local, value
    return titulo, url, value, nome


def tutorial_catalog_block(
    markdown_url: str,
    videos: list,
) -> dict:
    """Bloco ``tutorial`` gravado no catalog.json. Url vazia nao gera video.

    O terceiro item da linha, se existir, e so o arquivo local. Nao entra no JSON.
    """
    items = []
    for item in videos:
        titulo, url, _local, _nome = video_row(item)
        clean = (url or "").strip()
        if not clean:
            continue
        items.append({"titulo": (titulo or "").strip(), "url": clean})
    return {
        "markdown_url": (markdown_url or "").strip(),
        "videos": items,
    }


def tutorial_has_local_files(markdown_path: str, videos: list) -> bool:
    if (markdown_path or "").strip():
        return True
    return any(video_row(item)[2].strip() for item in videos)


def validate_tutorial_local_files(markdown_path: str, videos: list) -> str:
    """Extensao errada ou arquivo ausente. Vazio se nao ha o que enviar."""
    md = _as_local(markdown_path)
    if md is not None:
        if md.suffix.lower() != ".md":
            return "Somente .md."
        if not md.is_file():
            return "Arquivo de markdown nao encontrado."
    for item in videos:
        local = _as_local(video_row(item)[2])
        if local is None:
            continue
        if local.suffix.lower() != ".mp4":
            return "Somente .mp4."
        if not local.is_file():
            return "Arquivo de video nao encontrado."
    return ""


def apply_tutorial_uploads(
    markdown_url: str,
    markdown_path: str,
    videos: list,
    upload,
) -> tuple[dict | None, str]:
    """Cola o link se nao houver arquivo novo. Arquivo escolhido substitui o link.

    ``upload(path, message)`` usa a mesma sessao WebLogin do restante do save
    e devolve ``(ok, url_ou_erro)``.
    """
    err = validate_tutorial_local_files(markdown_path, videos)
    if err:
        return None, err
    md_url = _http_url(markdown_url)
    md = _as_local(markdown_path)
    if md is not None:
        ok, payload = upload(md, "Enviando markdown...")
        if not ok:
            return None, payload or "Falha no upload do markdown."
        md_url = (payload or "").strip()
        invalidate_tutorial_cache(md_url, ".md")
    out: list[tuple[str, str]] = []
    for item in videos:
        titulo, url, local_raw, _nome = video_row(item)
        final = _http_url(url)
        local = _as_local(local_raw)
        if local is not None:
            ok, payload = upload(local, "Enviando video...")
            if not ok:
                return None, payload or "Falha no upload do video."
            final = (payload or "").strip()
            invalidate_tutorial_cache(final, ".mp4")
        if not final:
            continue
        out.append(((titulo or "").strip(), final))
    return tutorial_catalog_block(md_url, out), ""


def _as_local(raw: str) -> Path | None:
    text = (raw or "").strip()
    if not text:
        return None
    return Path(text)


def _http_url(value: str) -> str:
    raw = (value or "").strip()
    if raw.lower().startswith(("http://", "https://")):
        return raw
    return ""


def invalidate_tutorial_cache(url: str, suffix: str) -> None:
    """Apaga a copia local dessa URL para o proximo Tutorial baixar o arquivo novo."""
    raw = (url or "").strip()
    if not raw:
        return
    target = cache_path_for(raw, suffix)
    try:
        if target.is_file():
            target.unlink()
    except OSError:
        pass


def split_markdown_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Parte o markdown nos titulos ## (nivel 2).

    O texto antes do primeiro ## fica sempre visivel.
    ### e blocos cercados por crases nao abrem um topico novo.
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    intro: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    title: str | None = None
    body: list[str] = []
    fence = False

    def flush() -> None:
        nonlocal title, body
        if title is None:
            return
        sections.append((title.strip() or "Topico", "\n".join(body).strip("\n")))
        title = None
        body = []

    for line in lines:
        if line.lstrip().startswith("```"):
            fence = not fence
        heading = None if fence else _H2.match(line)
        if heading is not None:
            flush()
            title = heading.group(1)
            body = []
            continue
        if title is None:
            intro.append(line)
        else:
            body.append(line)
    flush()
    return "\n".join(intro).strip("\n"), sections


def is_sharepoint_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    try:
        host = (urlparse(raw).hostname or "").lower()
    except ValueError:
        host = ""
    if "sharepoint." in host:
        return True
    low = raw.lower()
    return (
        "sharepoint.com" in low
        or "/:i:/" in low
        or "/:u:/" in low
        or "/:v:/" in low
        or "/:x:/" in low
    )


def _image_target(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("<") and ">" in text:
        return text[1 : text.index(">")].strip()
    return text.split()[0].strip() if text else ""


def prepare_markdown_for_display(text: str) -> str:
    """Imagem https publica permanece. Imagem do SharePoint vira link.

    Link de video no texto continua link: nao ha player dentro do markdown.
    """

    def repl(match: re.Match[str]) -> str:
        alt, raw = match.group(1), match.group(2)
        url = _image_target(raw)
        if not is_sharepoint_url(url):
            return match.group(0)
        label = (alt or "").strip() or "imagem"
        return f"[{label}]({url})"

    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            fence = not fence
            out.append(line)
            continue
        if fence:
            out.append(line)
            continue
        out.append(_IMG.sub(repl, line))
    return "\n".join(out)


def is_mp4_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    path = unquote(urlparse(raw).path).replace("\\", "/").rstrip("/")
    name = path.split("/")[-1].lower() if path else ""
    return name.endswith(".mp4")


def cache_path_for(url: str, suffix: str) -> Path:
    digest = hashlib.sha256((url or "").strip().encode("utf-8")).hexdigest()[:20]
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    return config.TUTORIAL_CACHE_DIR / f"{digest}{ext}"


def download_to_cache(url: str, suffix: str, progress=None) -> tuple[Path | None, str]:
    """Baixa com o PnP ja usado no catalogo. Reusa o arquivo se ja estiver em cache."""
    target = cache_path_for(url, suffix)
    if target.is_file() and target.stat().st_size > 0:
        return target, ""
    config.TUTORIAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    result = baixar_do_sharepoint(
        link=url,
        pasta_destino=config.TUTORIAL_CACHE_DIR,
        nome_arquivo=target.name,
        progress=progress,
    )
    if result.ok and result.path and Path(result.path).is_file():
        return Path(result.path), ""
    return None, (result.message or "Falha no download.").strip()
