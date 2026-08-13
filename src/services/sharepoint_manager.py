"""Download/upload via SharePoint usando templates PowerShell (PnP + WebLogin).

Fluxo tipico:
1. Interpreta o link do SharePoint (arquivo ou pasta).
2. Preenche placeholders no template .ps1.
3. Executa o script com ``powershell.exe`` (Connect-PnPOnline -UseWebLogin).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import config

ProgressCb = Callable[[float, str], None]
logger = logging.getLogger(__name__)

# No maximo um Uninstall/Install de PnP por processo do app (evita N reinstalações
# em lote de imagens / retries individuais).
_pnp_repair_attempted = False


def _reset_pnp_repair_state() -> None:
    """Reseta a flag de sessao (uso em testes)."""
    global _pnp_repair_attempted
    _pnp_repair_attempted = False


def _scripts_dir() -> Path:
    """Pasta dos templates .ps1 (bundle em modo frozen; ``scripts/`` em dev)."""
    configured = getattr(config, "SHAREPOINT_SCRIPTS_DIR", None)
    if configured:
        return Path(configured)
    bundle = getattr(config, "BUNDLE_DIR", None)
    if bundle:
        return Path(bundle) / "scripts"
    return config.ROOT_DIR / "scripts"


def _template_download() -> Path:
    name = getattr(config, "SHAREPOINT_DOWNLOAD_SCRIPT", "template_sp_download.ps1")
    return _scripts_dir() / name


def _template_download_by_id() -> Path:
    return _scripts_dir() / "template_sp_download_by_id.ps1"


def _template_download_batch() -> Path:
    name = getattr(
        config, "SHAREPOINT_DOWNLOAD_BATCH_SCRIPT", "template_sp_download_batch.ps1"
    )
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
    stderr: str = ""


@dataclass
class SharePointBatchItem:
    """Item para download em lote (uma sessao PnP por site)."""

    id: str
    link: str
    nome_arquivo: str


@dataclass
class SharePointBatchResult:
    ok: bool
    message: str = ""
    paths: dict[str, Path] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    stdout: str = ""


def _format_unique_id(raw: str) -> str:
    """Normaliza UniqueId para GUID com hifens (8-4-4-4-12)."""
    cleaned = (raw or "").strip().strip("{}").replace("-", "")
    if len(cleaned) == 32 and all(c in "0123456789abcdefABCDEF" for c in cleaned):
        return (
            f"{cleaned[0:8]}-{cleaned[8:12]}-{cleaned[12:16]}-"
            f"{cleaned[16:20]}-{cleaned[20:32]}"
        )
    return (raw or "").strip()


def parsear_link_download_aspx(url: str) -> dict:
    """Interpreta links do tipo .../_layouts/15/download.aspx?UniqueId=..."""
    parsed = urlparse(url)
    path_lower = parsed.path.lower()
    marker = "/_layouts/"
    if marker not in path_lower:
        raise ValueError(f"URL nao e download.aspx: {url}")

    idx = path_lower.index(marker)
    site_path = parsed.path[:idx].rstrip("/") or ""
    site_url = f"{parsed.scheme}://{parsed.netloc}{site_path}"

    params = parse_qs(parsed.query)
    unique_raw = None
    for key, values in params.items():
        if key.lower() == "uniqueid" and values:
            unique_raw = unquote(values[0]).strip().strip("{}")
            break
    if not unique_raw:
        raise ValueError("Link download.aspx sem parametro UniqueId.")

    return {
        "tipo": "unique_id",
        "site_url": site_url,
        "unique_id": _format_unique_id(unique_raw),
        "nome_arquivo": None,
        "caminho_sp": None,
    }


def parsear_link_sharepoint(url: str) -> dict:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Formato SharePoint: /_layouts/15/download.aspx?UniqueId=...
    if "download.aspx" in parsed.path.lower() and "uniqueid=" in url.lower():
        return parsear_link_download_aspx(url)

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
            "tipo": "path",
            "site_url": site_url,
            "caminho_sp": caminho_relativo,
            "caminho_pasta": caminho_pasta,
            "nome_arquivo": nome_arquivo,
            "unique_id": None,
        }

    if "AllItems.aspx" in url:
        params = parse_qs(parsed.query)
        if "id" in params:
            id_path = unquote(params["id"][0])
            partes = id_path.strip("/").split("/")
            site_path = "/" + "/".join(partes[:2])
            site_url = base + site_path
            return {
                "tipo": "path",
                "site_url": site_url,
                "caminho_sp": "/".join(partes[2:]),
                "caminho_pasta": "/".join(partes[2:]),
                "nome_arquivo": None,
                "unique_id": None,
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


def _run_powershell(script_path: str, timeout: int = 300) -> tuple[int, str, str]:
    """Executa um .ps1 em subprocesso isolado (sem encerrar PowerShells externos).

    Usado no reparo (NonInteractive). Downloads com WebLogin usam ``_run_templated_ps1``.
    """
    logger.info(
        "Executando PowerShell isolado: exe=powershell.exe script=%s timeout=%ss",
        script_path,
        timeout,
    )
    try:
        processo = subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return 127, "", "powershell.exe nao encontrado neste Windows."
    try:
        stdout, stderr = processo.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        processo.kill()
        processo.wait()
        return 124, "", "Timeout ao executar script PowerShell."
    return processo.returncode, stdout or "", stderr or ""


def is_access_denied_error(stdout: str, stderr: str) -> bool:
    """True quando o SharePoint recusou o arquivo apos o login (nao e falha de modulo)."""
    text = f"{stdout}\n{stderr}".lower()
    return (
        "0x80070005" in text
        or "access is denied" in text
        or "acesso negado" in text
    )


def abrir_pedido_acesso_sharepoint(url: str) -> bool:
    """Abre o link no navegador (tela nativa do SharePoint para solicitar acesso).

    Nao envia o pedido sozinho: o usuario confirma na pagina do SharePoint.
    """
    alvo = (url or "").strip()
    if not alvo.lower().startswith(("http://", "https://")):
        return False
    webbrowser.open(alvo)
    return True


def _mensagem_amigavel_falha(stdout: str, stderr: str) -> str:
    """Traduz saida tecnica do PowerShell em uma linha para a UI (sem dump de script)."""
    text = f"{stdout}\n{stderr}".lower()
    if "login_failed" in text:
        return (
            "Nao foi possivel conectar ao SharePoint (WebLogin). "
            "Conclua o login com a conta corporativa e tente de novo."
        )
    if is_access_denied_error(stdout, stderr):
        return (
            "Sem permissao no arquivo apos o login. "
            "Use a conta corporativa e solicite acesso no SharePoint."
        )
    if "uniqueid invalido" in text:
        return (
            "UniqueId do catalogo e invalido. "
            "Confira catalog.remote_url no settings.json."
        )
    if "serverrelativeurl" in text or "uniqueid" in text:
        return (
            "Nao foi possivel localizar o catalog.json nesse UniqueId. "
            "Confira o site (/teams/...) e se o UniqueId e de um arquivo, nao de pasta."
        )
    if "powershell.exe nao encontrado" in text:
        return "Windows PowerShell nao foi encontrado neste computador."
    return "Falha ao baixar o catalogo do SharePoint. Tente novamente."


def _is_pnp_dependency_error(stdout: str, stderr: str) -> bool:
    """Detecta falha real de modulo/assembly PnP (nao rede, auth ou arquivo ausente).

    Markers propositalmente estreitos: templates emitem ``DEP_ERROR: MODULE_NOT_LOADED``
    quando Import-Module / Connect-PnPOnline nao fica disponivel.
    """
    text = f"{stdout}\n{stderr}".lower()
    markers = [
        "dep_error: module_not_loaded",
        "falha: modulo nao carregado",
        "microsoft.identitymodel.clients.activedirectory",
        "could not load file or assembly",
        "assembly with same name",
        "repair_failed",
    ]
    return any(marker in text for marker in markers)


def _reparar_dependencia_pnp() -> tuple[bool, str]:
    """Reinstala SharePointPnPPowerShellOnline via scripts/reparar_pnp.ps1."""
    script = _scripts_dir() / "reparar_pnp.ps1"
    if not script.exists():
        return False, "Script de reparo nao encontrado."

    started = time.monotonic()
    logger.info("Iniciando reparo PnP: script=%s", script)
    try:
        code, stdout, stderr = _run_powershell(str(script.resolve()), timeout=300)
    except FileNotFoundError:
        return False, "powershell.exe nao encontrado neste Windows."
    duration_ms = int((time.monotonic() - started) * 1000)
    combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)

    if code == 0 and "REPAIR_OK" in stdout:
        logger.info("Reparo PnP concluido com sucesso em %sms", duration_ms)
        return True, "Dependencia PnP reparada com sucesso."

    logger.warning(
        "Reparo PnP falhou: code=%s duration_ms=%s detalhe=%s",
        code,
        duration_ms,
        combined[:500],
    )
    return False, f"Reparo PnP falhou. {combined}"


def _tentar_reparo_se_dependencia(stdout: str, stderr: str) -> bool:
    """Repara no maximo 1x por processo se a saida indicar erro de dependencia.

    Retorna True somente quando o reparo rodou e terminou com REPAIR_OK.
    """
    global _pnp_repair_attempted
    if not _is_pnp_dependency_error(stdout, stderr):
        return False
    if _pnp_repair_attempted:
        logger.info("Reparo PnP ja tentado nesta sessao; nao reinstala de novo.")
        return False
    _pnp_repair_attempted = True
    ok, msg = _reparar_dependencia_pnp()
    if not ok:
        logger.warning("Reparo automatico recusado/falhou: %s", msg)
    return ok


def _run_templated_ps1(
    template: Path,
    replacements: dict[str, str],
    progress: ProgressCb | None = None,
) -> tuple[int, str, str]:
    """Preenche template e roda powershell (WebLogin precisa de UI — sem -NonInteractive)."""
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
    except FileNotFoundError:
        return 127, "", "powershell.exe nao encontrado neste Windows."
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _executar_lote_grupo(
    *,
    site_url: str,
    manifesto: list[dict[str, Any]],
    pasta_final: Path,
    template: Path,
    progress: ProgressCb | None = None,
) -> tuple[dict[str, Path], dict[str, str], str, str]:
    """Executa um grupo (1 site) do download em lote. Retorna paths, errors, stdout, stderr."""
    paths: dict[str, Path] = {}
    errors: dict[str, str] = {}
    man_file = None
    res_file = None
    stdout = ""
    stderr = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as mf:
            json.dump(manifesto, mf, ensure_ascii=False)
            man_file = mf.name
        res_fd, res_file = tempfile.mkstemp(suffix=".json")
        os.close(res_fd)

        code, stdout, stderr = _run_templated_ps1(
            template,
            {
                "{{SITE_URL}}": site_url,
                "{{PASTA_DESTINO}}": str(pasta_final),
                "{{MANIFEST_PATH}}": man_file,
                "{{RESULT_PATH}}": res_file,
            },
            progress=progress,
        )
        combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)

        result_rows: list[Any] = []
        res_path = Path(res_file)
        if res_path.exists() and res_path.stat().st_size > 0:
            try:
                raw = json.loads(res_path.read_text(encoding="utf-8-sig"))
                if isinstance(raw, list):
                    result_rows = raw
                elif isinstance(raw, dict):
                    result_rows = [raw]
            except json.JSONDecodeError:
                errors["_batch_"] = f"Resultado JSON invalido (rc={code})."
        else:
            errors["_batch_"] = (
                f"Script em lote nao gerou resultado (rc={code}). {combined[:300]}"
            )

        for row in result_rows:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id", ""))
            if not rid:
                continue
            if row.get("ok"):
                p = row.get("path") or str(pasta_final / str(row.get("nome_arquivo", "")))
                local = Path(str(p))
                if local.exists():
                    paths[rid] = local
                else:
                    nome = str(row.get("nome_arquivo") or "")
                    candidate = pasta_final / nome if nome else None
                    if candidate and candidate.exists():
                        paths[rid] = candidate
                    else:
                        errors[rid] = "Marcado ok, mas arquivo local ausente."
            else:
                errors[rid] = str(row.get("error") or "falha no download")
    except FileNotFoundError as exc:
        errors["_batch_"] = str(exc)
        stderr = str(exc)
    except Exception as exc:
        errors["_batch_"] = f"Falha ao executar lote: {exc}"
        stderr = str(exc)
    finally:
        for tmp in (man_file, res_file):
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
    return paths, errors, stdout, stderr


def baixar_varios_do_sharepoint(
    itens: list[SharePointBatchItem],
    pasta_destino: str | Path | None = None,
    progress: ProgressCb | None = None,
) -> SharePointBatchResult:
    """Baixa varios arquivos com 1 Connect-PnPOnline por site (WebLogin).

    Agrupa por site_url. Cada grupo gera um manifesto JSON e executa
    ``template_sp_download_batch.ps1``. Se o grupo falhar por dependencia PnP,
    tenta no maximo um reparo (por processo) e um retry desse grupo.
    """
    if not itens:
        return SharePointBatchResult(ok=True, message="Nenhum arquivo para baixar.")

    pasta_final = Path(pasta_destino or config.DOWNLOADS_DIR)
    pasta_final.mkdir(parents=True, exist_ok=True)

    # Agrupa por site
    grupos: dict[str, list[dict[str, Any]]] = {}
    parse_errors: dict[str, str] = {}
    for item in itens:
        try:
            info = parsear_link_sharepoint(item.link)
        except ValueError as exc:
            parse_errors[item.id] = str(exc)
            continue
        site = info["site_url"]
        entry: dict[str, Any] = {
            "id": item.id,
            "nome_arquivo": item.nome_arquivo,
            "tipo": info.get("tipo") or "path",
        }
        if entry["tipo"] == "unique_id":
            entry["unique_id"] = info["unique_id"]
        else:
            entry["caminho_sp"] = info.get("caminho_sp")
            if not entry["caminho_sp"]:
                parse_errors[item.id] = "Caminho SharePoint nao determinado."
                continue
        grupos.setdefault(site, []).append(entry)

    paths: dict[str, Path] = {}
    errors: dict[str, str] = dict(parse_errors)
    logs: list[str] = []
    template = _template_download_batch()

    total_grupos = max(len(grupos), 1)
    for g_idx, (site_url, manifesto) in enumerate(grupos.items()):
        if progress:
            progress(
                0.1 + 0.8 * (g_idx / total_grupos),
                f"Baixando lote ({len(manifesto)} arquivo(s)) — login unico...",
            )

        g_paths, g_errors, stdout, stderr = _executar_lote_grupo(
            site_url=site_url,
            manifesto=manifesto,
            pasta_final=pasta_final,
            template=template,
            progress=progress,
        )
        combined = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
        logs.append(combined)

        # Sem nenhum arquivo do grupo: se for dependencia, repara 1x e repete o grupo.
        if not g_paths and _is_pnp_dependency_error(stdout, stderr):
            if progress:
                progress(0.2, "Lote falhou por dependencia PnP. Tentando reparo...")
            if _tentar_reparo_se_dependencia(stdout, stderr):
                if progress:
                    progress(0.35, "Dependencia reparada. Repetindo lote...")
                g_paths, g_errors, stdout, stderr = _executar_lote_grupo(
                    site_url=site_url,
                    manifesto=manifesto,
                    pasta_final=pasta_final,
                    template=template,
                    progress=progress,
                )
                combined = "\n".join(
                    part for part in (stdout.strip(), stderr.strip()) if part
                )
                logs.append(combined)

        paths.update(g_paths)
        errors.update(g_errors)

    ok_count = len(paths)
    total = len(itens)
    if progress:
        progress(1.0, f"Lote concluido: {ok_count}/{total} arquivo(s).")

    all_ok = ok_count == total and not errors
    return SharePointBatchResult(
        ok=all_ok or ok_count > 0,
        message=f"Lote: {ok_count}/{total} arquivo(s) baixados.",
        paths=paths,
        errors=errors,
        stdout="\n".join(logs),
    )


def baixar_do_sharepoint(
    link: str,
    pasta_destino: str | Path | None = None,
    nome_arquivo: str | None = None,
    progress: ProgressCb | None = None,
) -> SharePointResult:
    """Baixa um arquivo do SharePoint via template PowerShell (PnP + WebLogin).

    Aceita:
    - links /:u:/r/... (caminho)
    - links .../_layouts/15/download.aspx?UniqueId=...

    Em falha de dependencia PnP, tenta um reparo isolado e um unico retry.
    """
    try:
        info = parsear_link_sharepoint(link)
    except ValueError as exc:
        return SharePointResult(ok=False, message=str(exc))

    site_url = info["site_url"]
    pasta_final = str(pasta_destino or config.DOWNLOADS_DIR)
    nome_final = nome_arquivo or info.get("nome_arquivo") or "download.bin"

    if progress:
        progress(0.05, f"Preparando download: {nome_final}")

    result = _executar_download_sharepoint(
        info=info,
        site_url=site_url,
        pasta_final=pasta_final,
        nome_final=nome_final,
        progress=progress,
    )
    if result.ok:
        return result

    # Reparo so apos falha de dependencia; no maximo 1x por processo do app.
    if not _is_pnp_dependency_error(result.stdout, result.stderr):
        return result

    if progress:
        progress(0.2, "Dependencia PnP com problema. Iniciando reparo...")
    logger.info("Falha de dependencia PnP detectada; iniciando reparo automatico.")
    if not _tentar_reparo_se_dependencia(result.stdout, result.stderr):
        return SharePointResult(
            ok=False,
            message=(
                "Falha ao sincronizar por dependencia PnP e o reparo automatico "
                "nao concluiu (ou ja foi tentado nesta sessao)."
            ),
            stdout=result.stdout,
            stderr=result.stderr,
        )

    if progress:
        progress(0.35, "Dependencia reparada. Tentando download novamente...")
    logger.info("Reparo PnP ok; repetindo download em novo subprocesso.")
    retry = _executar_download_sharepoint(
        info=info,
        site_url=site_url,
        pasta_final=pasta_final,
        nome_final=nome_final,
        progress=progress,
    )
    if retry.ok:
        return retry

    return SharePointResult(
        ok=False,
        message=(
            "Dependencia PnP foi reparada, mas o download ainda falhou. "
            f"{retry.message}"
        ),
        stdout=retry.stdout,
        stderr=retry.stderr,
    )


def _executar_download_sharepoint(
    *,
    info: dict[str, Any],
    site_url: str,
    pasta_final: str,
    nome_final: str,
    progress: ProgressCb | None = None,
) -> SharePointResult:
    """Uma tentativa de download em subprocesso PowerShell isolado."""
    try:
        if info.get("tipo") == "unique_id":
            code, stdout, stderr = _run_templated_ps1(
                _template_download_by_id(),
                {
                    "{{SITE_URL}}": site_url,
                    "{{PASTA_DESTINO}}": pasta_final,
                    "{{NOME_ARQUIVO}}": nome_final,
                    "{{UNIQUE_ID}}": info["unique_id"],
                },
                progress=progress,
            )
        else:
            if not info.get("caminho_sp"):
                return SharePointResult(
                    ok=False, message="Caminho SharePoint nao determinado."
                )
            code, stdout, stderr = _run_templated_ps1(
                _template_download(),
                {
                    "{{SITE_URL}}": site_url,
                    "{{PASTA_DESTINO}}": pasta_final,
                    "{{NOME_ARQUIVO}}": nome_final,
                    "{{CAMINHO_SP}}": info["caminho_sp"],
                },
                progress=progress,
            )
    except FileNotFoundError as exc:
        return SharePointResult(ok=False, message=str(exc))
    except Exception as exc:
        return SharePointResult(ok=False, message=f"Falha ao executar PowerShell: {exc}")

    caminho_completo = Path(pasta_final) / nome_final

    if caminho_completo.exists():
        if progress:
            progress(1.0, "Download concluido")
        tamanho_kb = caminho_completo.stat().st_size / 1024
        return SharePointResult(
            ok=True,
            path=caminho_completo,
            message=f"Download concluido ({tamanho_kb:.1f} KB).",
            stdout=stdout,
            stderr=stderr,
        )

    # stdout/stderr ficam no resultado para diagnostico; a UI recebe so a linha amigavel.
    return SharePointResult(
        ok=False,
        message=_mensagem_amigavel_falha(stdout, stderr),
        stdout=stdout,
        stderr=stderr,
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
