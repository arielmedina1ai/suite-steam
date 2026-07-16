"""Download/upload via SharePoint usando templates PowerShell (PnP + WebLogin).

Fluxo validado no ambiente Petrobras:
1. Interpreta o link do SharePoint (arquivo ou pasta).
2. Preenche placeholders no template .ps1.
3. Executa o script com ``powershell.exe`` (Connect-PnPOnline -UseWebLogin).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

import config

ProgressCb = Callable[[float, str], None]


def _scripts_dir() -> Path:
    configured = getattr(config, "SHAREPOINT_SCRIPTS_DIR", None)
    if configured:
        return Path(configured)
    return config.ROOT_DIR / "scripts"


def _template_download() -> Path:
    name = getattr(config, "SHAREPOINT_DOWNLOAD_SCRIPT", "template_sp_download.ps1")
    return _scripts_dir() / name


def _template_upload() -> Path:
    name = getattr(config, "SHAREPOINT_UPLOAD_SCRIPT", "template_sp_upload.ps1")
    return _scripts_dir() / name


@dataclass
class SharePointResult:
    ok: bool
    path: Path | None = None
    message: str = ""
    stdout: str = ""


def parsear_link_sharepoint(url: str) -> dict:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    if "/:x:/r/" in url or "/:f:/r/" in url or "/r/" in url:
        path = parsed.path
        for prefixo in [
            "/:x:/r",
            "/:f:/r",
            "/:b:/r",
            "/:w:/r",
            "/:p:/r",
            "/:u:/r",
            "/:i:/r",
        ]:
            path = path.replace(prefixo, "")

        path_decodificado = unquote(path)
        partes = path_decodificado.strip("/").split("/")

        site_path = "/" + "/".join(partes[:2])
        site_url = base + site_path
        caminho_relativo = "/".join(partes[2:])
        nome_arquivo = partes[-1]
        caminho_pasta = "/".join(partes[2:-1])

        return {
            "site_url": site_url,
            "caminho_sp": caminho_relativo,
            "caminho_pasta": caminho_pasta,
            "nome_arquivo": nome_arquivo,
        }

    if "AllItems.aspx" in url:
        params = parse_qs(parsed.query)
        if "id" in params:
            id_path = unquote(params["id"][0])
            partes = id_path.strip("/").split("/")
            site_path = "/" + "/".join(partes[:2])
            site_url = base + site_path
            return {
                "site_url": site_url,
                "caminho_sp": "/".join(partes[2:]),
                "caminho_pasta": "/".join(partes[2:]),
                "nome_arquivo": None,
            }

    raise ValueError(f"Formato de URL do SharePoint nao reconhecido: {url}")


def parsear_link_pasta_sharepoint(url: str) -> dict:
    """Interpreta link de pasta (ou de arquivo, usando a pasta pai)."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    if "AllItems.aspx" in url:
        params = parse_qs(parsed.query)
        if "id" in params:
            id_path = unquote(params["id"][0])
            partes = id_path.strip("/").split("/")
            site_path = "/" + "/".join(partes[:2])
            site_url = base + site_path
            caminho_pasta = "/".join(partes[2:])
            return {"site_url": site_url, "caminho_sp": caminho_pasta}

    if any(
        p in url
        for p in [
            "/:x:/r",
            "/:f:/r",
            "/:b:/r",
            "/:w:/r",
            "/:p:/r",
            "/:u:/r",
            "/:i:/r",
        ]
    ):
        info = parsear_link_sharepoint(url)
        partes = info["caminho_sp"].split("/")
        caminho_pasta = "/".join(partes[:-1])
        return {"site_url": info["site_url"], "caminho_sp": caminho_pasta}

    raise ValueError(f"Formato de URL do SharePoint nao reconhecido: {url}")


def _run_templated_ps1(
    template: Path,
    replacements: dict[str, str],
    progress: ProgressCb | None = None,
) -> tuple[int, str, str]:
    if not template.exists():
        raise FileNotFoundError(f"Template nao encontrado: {template}")

    script = template.read_text(encoding="utf-8")
    for key, value in replacements.items():
        script = script.replace(key, value)

    # UTF-8 BOM necessario para PS 5.1 ler acentos corretamente
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False, encoding="utf-8-sig"
    ) as tmp:
        tmp.write(script)
        tmp_path = tmp.name

    if progress:
        progress(0.15, "Abrindo autenticacao SharePoint (WebLogin)...")

    try:
        resultado = subprocess.run(
            ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", tmp_path],
            capture_output=True,
            text=True,
            encoding="cp850",
            errors="replace",
        )
        return resultado.returncode, resultado.stdout or "", resultado.stderr or ""
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def baixar_do_sharepoint(
    link: str,
    pasta_destino: str | Path | None = None,
    nome_arquivo: str | None = None,
    progress: ProgressCb | None = None,
) -> SharePointResult:
    """Baixa um arquivo do SharePoint via template PowerShell (PnP)."""
    try:
        info = parsear_link_sharepoint(link)
    except ValueError as exc:
        return SharePointResult(ok=False, message=str(exc))

    site_url = info["site_url"]
    caminho_sp = info["caminho_sp"]
    nome_final = nome_arquivo or info["nome_arquivo"]
    pasta_final = str(pasta_destino or config.DOWNLOADS_DIR)

    if not nome_final:
        return SharePointResult(
            ok=False,
            message="Nao foi possivel determinar o nome do arquivo. Informe nome_arquivo.",
        )

    if progress:
        progress(0.05, f"Preparando download: {nome_final}")

    try:
        code, stdout, stderr = _run_templated_ps1(
            _template_download(),
            {
                "{{SITE_URL}}": site_url,
                "{{PASTA_DESTINO}}": pasta_final,
                "{{NOME_ARQUIVO}}": nome_final,
                "{{CAMINHO_SP}}": caminho_sp,
            },
            progress=progress,
        )
    except FileNotFoundError as exc:
        return SharePointResult(ok=False, message=str(exc))
    except Exception as exc:
        return SharePointResult(ok=False, message=f"Falha ao executar PowerShell: {exc}")

    caminho_completo = Path(pasta_final) / nome_final
    log = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)

    if caminho_completo.exists():
        if progress:
            progress(1.0, "Download concluido")
        tamanho_kb = caminho_completo.stat().st_size / 1024
        return SharePointResult(
            ok=True,
            path=caminho_completo,
            message=f"Download concluido ({tamanho_kb:.1f} KB).",
            stdout=log,
        )

    detail = log or f"returncode={code}"
    return SharePointResult(
        ok=False,
        message=f"Arquivo nao encontrado apos o download. {detail}",
        stdout=log,
    )


def enviar_para_sharepoint(
    arquivo_local: str | Path,
    link_pasta: str,
    nome_arquivo: str | None = None,
    progress: ProgressCb | None = None,
) -> SharePointResult:
    """Envia um arquivo local para uma pasta do SharePoint via template PowerShell."""
    arquivo = Path(arquivo_local)
    if not arquivo.exists():
        return SharePointResult(ok=False, message=f"Arquivo local nao encontrado: {arquivo}")

    try:
        info = parsear_link_pasta_sharepoint(link_pasta)
    except ValueError as exc:
        return SharePointResult(ok=False, message=str(exc))

    site_url = info["site_url"]
    caminho_sp = info["caminho_sp"]
    nome_final = nome_arquivo or arquivo.name

    if progress:
        progress(0.05, f"Preparando upload: {nome_final}")

    try:
        code, stdout, stderr = _run_templated_ps1(
            _template_upload(),
            {
                "{{SITE_URL}}": site_url,
                "{{ARQUIVO_LOCAL}}": str(arquivo.resolve()),
                "{{NOME_ARQUIVO}}": nome_final,
                "{{CAMINHO_SP}}": caminho_sp,
            },
            progress=progress,
        )
    except FileNotFoundError as exc:
        return SharePointResult(ok=False, message=str(exc))
    except Exception as exc:
        return SharePointResult(ok=False, message=f"Falha ao executar PowerShell: {exc}")

    log = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    if code == 0:
        if progress:
            progress(1.0, "Upload concluido")
        return SharePointResult(
            ok=True,
            path=arquivo,
            message="Upload concluido.",
            stdout=log,
        )

    return SharePointResult(
        ok=False,
        message=f"Falha no upload. {log or f'returncode={code}'}",
        stdout=log,
    )
