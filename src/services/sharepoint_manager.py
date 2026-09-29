"""Download/upload via SharePoint usando templates PowerShell (PnP + WebLogin).

Fluxo tipico:
1. Interpreta o link do SharePoint (arquivo ou pasta).
2. Preenche placeholders no template .ps1.
3. Executa o script com ``powershell.exe`` (Connect-PnPOnline -UseWebLogin).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import config

ProgressCb = Callable[[float, str], None]


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


def _template_upload_by_id() -> Path:
    return _scripts_dir() / "template_sp_upload_by_id.ps1"


def _template_list_folders() -> Path:
    name = getattr(config, "SHAREPOINT_LIST_FOLDERS_SCRIPT", "template_sp_list_folders.ps1")
    return _scripts_dir() / name


def _template_session() -> Path:
    name = getattr(config, "SHAREPOINT_SESSION_SCRIPT", "template_sp_session.ps1")
    return _scripts_dir() / name


def _hidden_subprocess_kwargs() -> dict:
    """powershell.exe sem janela: CREATE_NO_WINDOW + -WindowStyle Hidden."""
    kwargs: dict = {}
    if sys.platform.startswith("win"):
        flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        kwargs["creationflags"] = flags
        startupinfo = subprocess.STARTUPINFO()
        show = getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
        startupinfo.dwFlags |= show
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _powershell_file_cmd(script_path: str) -> list[str]:
    return [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        script_path,
    ]


@dataclass
class SharePointResult:
    ok: bool
    path: Path | None = None
    message: str = ""
    stdout: str = ""
    skipped: bool = False
    remote_name: str = ""


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
            unique_raw = values[0]
            break
    if not unique_raw:
        raise ValueError("Link download.aspx sem parametro UniqueId.")

    # Mantem o UniqueId como veio na URL; o PowerShell normaliza o Guid.
    return {
        "tipo": "unique_id",
        "site_url": site_url,
        "unique_id": unique_raw.strip(),
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
        partes = (info.get("caminho_sp") or "").split("/")
        caminho_pasta = "/".join(partes[:-1]) if info.get("nome_arquivo") else "/".join(partes)
        return {"site_url": info["site_url"], "caminho_sp": caminho_pasta}

    path = unquote(parsed.path).strip("/")
    partes = [p for p in path.split("/") if p]
    if (
        parsed.scheme in {"http", "https"}
        and len(partes) >= 3
        and partes[0].lower() in {"sites", "teams"}
    ):
        site_path = "/" + "/".join(partes[:2])
        site_url = base + site_path
        caminho_pasta = "/".join(partes[2:])
        if caminho_pasta:
            return {"site_url": site_url, "caminho_sp": caminho_pasta}

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
        # Indeterminado: WebLogin nao tem bytes ainda (nao fingir percentual)
        progress(-1.0, "Abrindo autenticacao SharePoint (WebLogin)...")

    try:
        resultado = subprocess.run(
            _powershell_file_cmd(tmp_path),
            capture_output=True,
            text=True,
            encoding="cp850",
            errors="replace",
            **_hidden_subprocess_kwargs(),
        )
        return resultado.returncode, resultado.stdout or "", resultado.stderr or ""
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


class PnPWebLoginSession:
    """Um powershell.exe + um Connect-PnPOnline para varias operacoes."""

    def __init__(self, site_url: str, progress: ProgressCb | None = None) -> None:
        self.site_url = (site_url or "").strip()
        self.progress = progress
        self._proc: subprocess.Popen | None = None
        self._dir: Path | None = None
        self._script: str | None = None

    def start(self) -> str:
        if not self.site_url:
            return "site_url vazio para WebLogin."
        template = _template_session()
        if not template.exists():
            return f"Template nao encontrado: {template}"
        self._dir = Path(tempfile.mkdtemp(prefix="suite-pnp-"))
        script = template.read_text(encoding="utf-8")
        script = script.replace("{{SITE_URL}}", self.site_url)
        script = script.replace("{{CONTROL_DIR}}", str(self._dir))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", delete=False, encoding="utf-8-sig"
        ) as tmp:
            tmp.write(script)
            self._script = tmp.name
        if self.progress:
            self.progress(-1.0, "Abrindo autenticacao SharePoint (WebLogin)...")
        try:
            popen_kwargs = _hidden_subprocess_kwargs()
            if sys.platform.startswith("win"):
                popen_kwargs["creationflags"] = int(popen_kwargs.get("creationflags", 0)) | int(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                )
            self._proc = subprocess.Popen(
                _powershell_file_cmd(self._script),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                **popen_kwargs,
            )
        except Exception as exc:
            return f"Falha ao iniciar PowerShell: {exc}"
        ready = self._dir / "ready.txt"
        deadline = time.time() + 300
        while time.time() < deadline:
            if ready.is_file():
                return ""
            if self._proc.poll() is not None:
                return "PowerShell encerrou antes do WebLogin."
            time.sleep(0.2)
        return "Tempo esgotado aguardando o WebLogin."

    def close(self) -> None:
        proc = self._proc
        if self._dir is not None:
            try:
                (self._dir / "quit").write_text("1", encoding="ascii")
            except OSError:
                pass
        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        if proc is not None and proc.poll() is None and sys.platform.startswith("win"):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=5,
                    **_hidden_subprocess_kwargs(),
                )
            except Exception:
                pass
        self._proc = None
        if self._script:
            try:
                os.unlink(self._script)
            except OSError:
                pass
            self._script = None
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None

    def __enter__(self) -> "PnPWebLoginSession":
        err = self.start()
        if err:
            self.close()
            raise RuntimeError(err)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def _send(self, payload: dict[str, Any], timeout: float = 600) -> dict[str, Any]:
        if self._dir is None or self._proc is None:
            return {"ok": False, "error": "Sessao PnP nao iniciada."}
        ack = self._dir / "ack.json"
        cmd = self._dir / "cmd.json"
        tmp = self._dir / "cmd.json.tmp"
        try:
            if ack.exists():
                ack.unlink()
        except OSError:
            pass
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cmd)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if ack.is_file() and ack.stat().st_size > 0:
                try:
                    raw = ack.read_text(encoding="utf-8-sig")
                    data = json.loads(raw) if raw.strip() else {}
                except (OSError, json.JSONDecodeError):
                    time.sleep(0.05)
                    continue
                try:
                    ack.unlink()
                except OSError:
                    pass
                if not isinstance(data, dict):
                    return {"ok": False, "error": "ack invalido"}
                return data
            if self._proc.poll() is not None:
                return {"ok": False, "error": "PowerShell encerrou no meio da operacao."}
            time.sleep(0.1)
        return {"ok": False, "error": "Tempo esgotado na operacao SharePoint."}

    def download(
        self,
        info: dict[str, Any],
        pasta_final: str,
        nome_final: str,
    ) -> SharePointResult:
        site = str(info.get("site_url") or self.site_url)
        if info.get("tipo") == "unique_id":
            ack = self._send(
                {
                    "op": "download_id",
                    "site_url": site,
                    "pasta_destino": pasta_final,
                    "nome_arquivo": nome_final,
                    "unique_id": info.get("unique_id") or "",
                }
            )
        else:
            caminho = info.get("caminho_sp")
            if not caminho:
                return SharePointResult(ok=False, message="Caminho SharePoint nao determinado.")
            ack = self._send(
                {
                    "op": "download_path",
                    "site_url": site,
                    "pasta_destino": pasta_final,
                    "nome_arquivo": nome_final,
                    "caminho_sp": caminho,
                }
            )
        if ack.get("ok"):
            path = Path(str(ack.get("path") or ""))
            if path.is_file():
                return SharePointResult(ok=True, path=path, message="Download concluido.")
            return SharePointResult(ok=False, message="Download sem arquivo local.")
        return SharePointResult(ok=False, message=str(ack.get("error") or "Falha no download."))

    def upload_folder(
        self,
        arquivo: Path,
        info: dict[str, Any],
        nome_final: str,
    ) -> SharePointResult:
        ack = self._send(
            {
                "op": "upload_folder",
                "site_url": str(info.get("site_url") or self.site_url),
                "arquivo_local": str(arquivo.resolve()),
                "nome_arquivo": nome_final,
                "caminho_sp": info.get("caminho_sp") or "",
            }
        )
        if ack.get("ok"):
            return SharePointResult(ok=True, path=arquivo, message="Upload concluido.")
        return SharePointResult(ok=False, message=str(ack.get("error") or "Falha no upload."))

    def upload_unique_id(
        self,
        arquivo: Path,
        *,
        site_url: str,
        unique_id: str,
    ) -> SharePointResult:
        ack = self._send(
            {
                "op": "upload_id",
                "site_url": site_url or self.site_url,
                "arquivo_local": str(arquivo.resolve()),
                "unique_id": unique_id,
            }
        )
        if ack.get("ok"):
            return SharePointResult(ok=True, path=arquivo, message="Upload concluido.")
        return SharePointResult(ok=False, message=str(ack.get("error") or "Falha no upload."))

    def delete_remote(self, file_url: str) -> SharePointResult:
        raw = (file_url or "").strip()
        if not raw.lower().startswith(("http://", "https://")):
            return SharePointResult(ok=False, message="Link remoto ausente.")
        try:
            info = parsear_link_sharepoint(raw)
        except ValueError as exc:
            return SharePointResult(ok=False, message=str(exc))
        site = str(info.get("site_url") or self.site_url)
        if info.get("tipo") == "unique_id":
            ack = self._send(
                {
                    "op": "delete_id",
                    "site_url": site,
                    "unique_id": info.get("unique_id") or "",
                }
            )
        else:
            caminho = info.get("caminho_sp") or ""
            nome = str(info.get("nome_arquivo") or "").strip()
            if not caminho:
                return SharePointResult(ok=False, message="Caminho SharePoint nao determinado.")
            ack = self._send(
                {
                    "op": "delete_path",
                    "site_url": site,
                    "caminho_sp": caminho,
                    "nome_arquivo": nome,
                }
            )
        if ack.get("ok"):
            return SharePointResult(ok=True, message="Arquivo removido no SharePoint.")
        return SharePointResult(ok=False, message=str(ack.get("error") or "Falha ao excluir no SharePoint."))

    def create_folder(self, parent_info: dict[str, Any], name: str) -> SharePointResult:
        nome = (name or "").strip()
        if not nome:
            return SharePointResult(ok=False, message="Informe o nome da nova pasta.")
        if "/" in nome or "\\" in nome:
            return SharePointResult(ok=False, message="Nome da pasta nao pode conter barras.")
        ack = self._send(
            {
                "op": "create_folder",
                "site_url": str(parent_info.get("site_url") or self.site_url),
                "pasta_pai": parent_info.get("caminho_sp") or "",
                "nome_pasta": nome,
            }
        )
        if ack.get("ok"):
            return SharePointResult(ok=True, message="Pasta criada no SharePoint.")
        return SharePointResult(
            ok=False,
            message=str(ack.get("error") or "Falha ao criar a pasta no SharePoint."),
        )

    def move_remote(self, file_url: str, dest_folder_url: str) -> SharePointResult:
        raw = (file_url or "").strip()
        dest = (dest_folder_url or "").strip()
        if not raw.lower().startswith(("http://", "https://")):
            return SharePointResult(ok=False, message="Link remoto ausente.")
        if not dest:
            return SharePointResult(ok=False, message="Pasta destino ausente.")
        try:
            src = parsear_link_sharepoint(raw)
            folder = parsear_link_pasta_sharepoint(dest)
        except ValueError as exc:
            return SharePointResult(ok=False, message=str(exc))
        payload: dict[str, Any] = {
            "op": "move_file",
            "site_url": str(folder.get("site_url") or src.get("site_url") or self.site_url),
            "destino_sp": folder.get("caminho_sp") or "",
        }
        if src.get("tipo") == "unique_id":
            payload["unique_id"] = src.get("unique_id") or ""
        else:
            payload["caminho_sp"] = src.get("caminho_sp") or ""
            payload["nome_arquivo"] = src.get("nome_arquivo") or ""
        ack = self._send(payload)
        if ack.get("ok"):
            return SharePointResult(
                ok=True,
                message="Arquivo movido no SharePoint.",
                skipped=bool(ack.get("skipped")),
                remote_name=str(ack.get("name") or "").strip(),
            )
        return SharePointResult(
            ok=False,
            message=str(ack.get("error") or "Falha ao mover arquivo no SharePoint."),
        )


def baixar_varios_do_sharepoint(
    itens: list[SharePointBatchItem],
    pasta_destino: str | Path | None = None,
    progress: ProgressCb | None = None,
) -> SharePointBatchResult:
    """Baixa varios arquivos com 1 Connect-PnPOnline por site (WebLogin).

    Agrupa por site_url. Cada grupo gera um manifesto JSON e executa
    ``template_sp_download_batch.ps1`` uma unica vez.
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

        man_file = None
        res_file = None
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
            log = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
            logs.append(log)

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
                    f"Script em lote nao gerou resultado (rc={code}). {log[:300]}"
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
                        # fallback: procura pelo nome pedido
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
        except Exception as exc:
            errors["_batch_"] = f"Falha ao executar lote: {exc}"
        finally:
            for tmp in (man_file, res_file):
                if tmp:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

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


def _path_from_sucesso_log(log: str) -> Path | None:
    for line in reversed((log or "").splitlines()):
        text = line.strip()
        if not text.upper().startswith("SUCESSO:"):
            continue
        rest = text.split(":", 1)[1].strip()
        if rest.endswith(")") and "(" in rest:
            rest = rest[: rest.rfind("(")].strip()
        found = Path(rest)
        if found.is_file():
            return found
    return None


def _resolve_downloaded_path(
    pasta_final: str,
    nome_final: str,
    log: str,
) -> Path | None:
    pasta = Path(pasta_final)
    if nome_final:
        candidate = pasta / nome_final
        if candidate.is_file():
            return candidate
        return _path_from_sucesso_log(log)
    found = _path_from_sucesso_log(log)
    if found is not None:
        return found
    try:
        files = [p for p in pasta.iterdir() if p.is_file()]
    except OSError:
        return None
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def baixar_do_sharepoint(
    link: str,
    pasta_destino: str | Path | None = None,
    nome_arquivo: str | None = None,
    progress: ProgressCb | None = None,
    session: PnPWebLoginSession | None = None,
) -> SharePointResult:
    """Baixa um arquivo do SharePoint via template PowerShell (PnP + WebLogin).

    Aceita:
    - links /:u:/r/... (caminho)
    - links .../_layouts/15/download.aspx?UniqueId=...
    """
    try:
        info = parsear_link_sharepoint(link)
    except ValueError as exc:
        return SharePointResult(ok=False, message=str(exc))

    site_url = info["site_url"]
    pasta_final = str(pasta_destino or config.DOWNLOADS_DIR)
    if nome_arquivo:
        nome_final = Path(str(nome_arquivo).replace("\\", "/")).name
    else:
        remoto = info.get("nome_arquivo")
        nome_final = Path(str(remoto).replace("\\", "/")).name if remoto else ""
    if not nome_final and info.get("tipo") != "unique_id":
        nome_final = "download.bin"

    if progress:
        rotulo = nome_final or "arquivo do UniqueId"
        progress(0.05, f"Preparando download: {rotulo}")

    if session is not None:
        result = session.download(info, pasta_final, nome_final)
        if result.ok and result.path and result.path.is_file():
            if progress:
                progress(1.0, "Download concluido")
            tamanho_kb = result.path.stat().st_size / 1024
            return SharePointResult(
                ok=True,
                path=result.path,
                message=f"Download concluido ({tamanho_kb:.1f} KB).",
            )
        return result

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
                return SharePointResult(ok=False, message="Caminho SharePoint nao determinado.")
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

    log = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    caminho_completo = _resolve_downloaded_path(pasta_final, nome_final, log)

    if caminho_completo is not None and caminho_completo.is_file():
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
    session: PnPWebLoginSession | None = None,
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

    if session is not None:
        result = session.upload_folder(arquivo, info, nome_final)
        if result.ok and progress:
            progress(1.0, "Upload concluido")
        return result

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


def enviar_por_unique_id(
    arquivo_local: str | Path,
    *,
    site_url: str,
    unique_id: str,
    progress: ProgressCb | None = None,
    session: PnPWebLoginSession | None = None,
) -> SharePointResult:
    """Sobrescreve o arquivo do UniqueId (catalog.json) via PnP WebLogin."""
    arquivo = Path(arquivo_local)
    if not arquivo.exists():
        return SharePointResult(ok=False, message=f"Arquivo local nao encontrado: {arquivo}")
    if not site_url or not unique_id:
        return SharePointResult(ok=False, message="UniqueId ou site_url ausente.")
    if progress:
        progress(0.05, "Preparando envio do catalog.json...")
    if session is not None:
        result = session.upload_unique_id(arquivo, site_url=site_url, unique_id=unique_id)
        if result.ok and progress:
            progress(1.0, "Upload concluido")
        return result
    try:
        code, stdout, stderr = _run_templated_ps1(
            _template_upload_by_id(),
            {
                "{{SITE_URL}}": site_url,
                "{{ARQUIVO_LOCAL}}": str(arquivo.resolve()),
                "{{UNIQUE_ID}}": unique_id,
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
        return SharePointResult(ok=True, path=arquivo, message="Upload concluido.", stdout=log)
    return SharePointResult(
        ok=False,
        message=f"Falha no upload. {log or f'returncode={code}'}",
        stdout=log,
    )


def listar_pastas_sharepoint(
    folder_url: str,
    progress: ProgressCb | None = None,
) -> tuple[list[str], str]:
    """Lista pastas imediatas sob o link de pasta (PnP WebLogin)."""
    url = (folder_url or "").strip()
    if not url:
        return [], "publish.folder_url nao configurado no settings.json."
    try:
        info = parsear_link_pasta_sharepoint(url)
    except ValueError as exc:
        return [], str(exc)
    site_url = info.get("site_url") or ""
    caminho_sp = info.get("caminho_sp") or ""
    if not site_url or not caminho_sp:
        return [], "Pasta raiz do SharePoint nao determinada."
    out_fd, out_file = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    try:
        code, stdout, stderr = _run_templated_ps1(
            _template_list_folders(),
            {
                "{{SITE_URL}}": site_url,
                "{{CAMINHO_SP}}": caminho_sp,
                "{{OUT_FILE}}": out_file,
            },
            progress=progress,
        )
    except FileNotFoundError as exc:
        try:
            os.unlink(out_file)
        except OSError:
            pass
        return [], str(exc)
    except Exception as exc:
        try:
            os.unlink(out_file)
        except OSError:
            pass
        return [], f"Falha ao listar pastas: {exc}"
    log = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part)
    names: list[str] = []
    try:
        raw = Path(out_file).read_text(encoding="utf-8-sig")
        data = json.loads(raw) if raw.strip() else {}
        folders = data.get("folders") if isinstance(data, dict) else data
        if isinstance(folders, list):
            seen: set[str] = set()
            for item in folders:
                name = str(item).strip()
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
        elif isinstance(folders, str) and folders.strip():
            names.append(folders.strip())
    except (OSError, json.JSONDecodeError):
        names = []
    try:
        os.unlink(out_file)
    except OSError:
        pass
    if code != 0 and not names:
        return [], log or f"Falha ao listar pastas (returncode={code})."
    return names, ""
