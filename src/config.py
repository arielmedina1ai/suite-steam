"""Configuracao da Suite.

Este arquivo e a "casca" publica: NAO contem dados internos. Textos/cores/URL do
catalogo remoto sao lidos de ``settings.json`` (local). Scripts SharePoint ficam
fixos no codigo (sempre PnP).

Ordem de carga:
    1. settings.json ao lado do .exe / raiz do repo (LOCAL)
    2. %LOCALAPPDATA%/SuitePetrobras/settings.json (fallback no .exe)
    3. settings.example.json (PUBLICO / embutido no bundle)

Consulte CONFIGURACAO.md para saber exatamente onde atribuir cada parametro.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _is_frozen() -> bool:
    """True quando empacotado (PyInstaller / flet pack)."""
    return bool(getattr(sys, "frozen", False))


# ---------------------------------------------------------------------------
# Caminhos do projeto
# ---------------------------------------------------------------------------
# Em modo congelado:
#   BUNDLE_DIR  = pasta extraida do bundle (sys._MEIPASS) — assets/scripts/exemplos
#   EXE_DIR     = pasta do .exe — settings.json editavel pelo usuario
# Em desenvolvimento: ambos apontam para a raiz do repositorio.
SRC_DIR = Path(__file__).resolve().parent
if _is_frozen():
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", SRC_DIR))
    EXE_DIR = Path(sys.executable).resolve().parent
    ROOT_DIR = EXE_DIR
else:
    BUNDLE_DIR = SRC_DIR.parent
    EXE_DIR = BUNDLE_DIR
    ROOT_DIR = BUNDLE_DIR

ASSETS_DIR = BUNDLE_DIR / "assets"
BRANDING_DIR = ASSETS_DIR / "branding"
BRANDING_LOGO = BRANDING_DIR / "logo.png"
BRANDING_HERO = BRANDING_DIR / "hero.png"
BRANDING_WINDOW_ICON_PNG = BRANDING_DIR / "window_icon.png"
BRANDING_WINDOW_ICON_ICO = BRANDING_DIR / "window_icon.ico"
# legado: alguns docs ainda citam window_icon.png como "icone da janela"
BRANDING_WINDOW_ICON = BRANDING_WINDOW_ICON_PNG
CATALOG_EXAMPLE_FILE = BUNDLE_DIR / "catalog.example.json"

SETTINGS_EXAMPLE_FILE = BUNDLE_DIR / "settings.example.json"
# Preferencia: ao lado do .exe (ou raiz do repo em dev)
SETTINGS_FILE = EXE_DIR / "settings.json"


def _user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "SuitePetrobras"


def _load_settings() -> dict[str, Any]:
    """Le o primeiro arquivo de settings disponivel (local tem prioridade)."""
    candidates: list[Path] = [SETTINGS_FILE]
    if _is_frozen():
        # Fallback se o usuario nao colocou settings ao lado do exe
        candidates.append(_user_data_dir() / "settings.json")
    candidates.append(SETTINGS_EXAMPLE_FILE)
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
    return {}


_S = _load_settings()
_app = _S.get("app", {}) if isinstance(_S.get("app"), dict) else {}
_sector = _S.get("sector", {}) if isinstance(_S.get("sector"), dict) else {}
_theme = _S.get("theme", {}) if isinstance(_S.get("theme"), dict) else {}
_catalog = _S.get("catalog", {}) if isinstance(_S.get("catalog"), dict) else {}

# ---------------------------------------------------------------------------
# Identificacao do app  ->  settings.json > "app"
# ---------------------------------------------------------------------------
APP_NAME = _app.get("name", "Suite")
APP_VERSION = str(_app.get("version", "0.1.0")).strip() or "0.1.0"

# ---------------------------------------------------------------------------
# Textos institucionais da home  ->  settings.json > "sector"
# ---------------------------------------------------------------------------
SECTOR_NAME = _sector.get("name", "Nome do Setor")
SECTOR_TAGLINE = _sector.get("tagline", "Nossos aplicativos, em um so lugar.")
SECTOR_DESCRIPTION = _sector.get(
    "description",
    "Edite a descricao do setor no arquivo settings.json (secao 'sector').",
)

# ---------------------------------------------------------------------------
# Identidade visual  ->  settings.json > "theme"
# ---------------------------------------------------------------------------
COLOR_PRIMARY = _theme.get("primary", "#008542")
COLOR_PRIMARY_DARK = _theme.get("primary_dark", "#00522A")
COLOR_ACCENT = _theme.get("accent", "#FFD000")
COLOR_BG = _theme.get("bg", "#0E1512")
COLOR_SURFACE = _theme.get("surface", "#16211C")
COLOR_TEXT = _theme.get("text", "#EAF3EE")

# ---------------------------------------------------------------------------
# Catalogo  ->  settings.json > "catalog.remote_url" (link SharePoint do catalog.json)
# ---------------------------------------------------------------------------
_remote = _catalog.get("remote_url")
REMOTE_CATALOG_URL: str | None = (
    _remote.strip() if isinstance(_remote, str) and _remote.strip() else None
)

# ---------------------------------------------------------------------------
# Pasta de dados do usuario
# ---------------------------------------------------------------------------
USER_DATA_DIR = _user_data_dir()
DOWNLOADS_DIR = USER_DATA_DIR / "apps"
INSTALLED_MANIFEST = USER_DATA_DIR / "installed.json"
FAVORITES_FILE = USER_DATA_DIR / "favorites.json"
CATALOG_CACHE_DIR = USER_DATA_DIR / "catalog"
CATALOG_CACHE_FILE = CATALOG_CACHE_DIR / "catalog.json"
CATALOG_IMAGES_DIR = CATALOG_CACHE_DIR / "images"
CATALOG_IMAGES_MANIFEST = CATALOG_CACHE_DIR / "images_manifest.json"


def user_downloads_dir() -> Path:
    """Pasta Downloads do usuario Windows (destino do update da Suite)."""
    home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    return home / "Downloads"

# ---------------------------------------------------------------------------
# SharePoint (sempre PnP) — caminhos fixos, nao vao no settings.json
# ---------------------------------------------------------------------------
SHAREPOINT_ENABLED = True
SHAREPOINT_SCRIPTS_DIR = BUNDLE_DIR / "scripts"
SHAREPOINT_DOWNLOAD_SCRIPT = "template_sp_download.ps1"
SHAREPOINT_DOWNLOAD_BATCH_SCRIPT = "template_sp_download_batch.ps1"
SHAREPOINT_UPLOAD_SCRIPT = "template_sp_upload.ps1"


def _png_to_ico(png_path: Path, ico_path: Path) -> None:
    """Gera .ico embutindo o PNG (formato aceito pelo Windows moderno / Flet)."""
    import struct

    png = png_path.read_bytes()
    if len(png) < 24 or png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Arquivo PNG invalido: {png_path}")
    width = struct.unpack(">I", png[16:20])[0]
    height = struct.unpack(">I", png[20:24])[0]
    # ICONDIRENTRY: 0 = dimensao 256
    w_byte = 0 if width >= 256 else width
    h_byte = 0 if height >= 256 else height
    offset = 6 + 16
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        w_byte,
        h_byte,
        0,
        0,
        1,
        32,
        len(png),
        offset,
    )
    ico_path.write_bytes(header + entry + png)


def resolve_window_icon() -> Path | None:
    """Caminho absoluto do .ico da janela (exigido pelo Flet no Windows).

    Usa ``window_icon.ico`` se existir; senao converte ``window_icon.png``.
    Em app congelado o bundle e so-leitura: o .ico gerado vai em USER_DATA_DIR.
    """
    ico = BRANDING_WINDOW_ICON_ICO
    png = BRANDING_WINDOW_ICON_PNG
    if ico.exists():
        return ico.resolve()
    if not png.exists():
        return None
    out = ico
    if _is_frozen():
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        out = USER_DATA_DIR / "window_icon.ico"
        if out.exists():
            return out.resolve()
    try:
        _png_to_ico(png, out)
    except (OSError, ValueError):
        return None
    return out.resolve() if out.exists() else None
