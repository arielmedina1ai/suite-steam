"""Configuracao da Suite.

Este arquivo e a "casca" publica: NAO contem dados internos. Todos os parametros
personalizaveis (textos do setor, cores, catalogo, links) sao lidos de um arquivo
``settings.json`` na raiz do projeto. Se ele nao existir, usamos ``settings.example.json``
(placeholders publicos), de forma que o projeto roda de imediato apos o clone.

Ordem de carga:
    1. settings.json          (LOCAL - nao versionado; valores reais Petrobras)
    2. settings.example.json  (PUBLICO - placeholders)

Consulte CONFIGURACAO.md para saber exatamente onde atribuir cada parametro.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Caminhos do projeto
# ---------------------------------------------------------------------------
SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
ASSETS_DIR = ROOT_DIR / "assets"
DATA_DIR = ROOT_DIR / "data"

SETTINGS_FILE = ROOT_DIR / "settings.json"
SETTINGS_EXAMPLE_FILE = ROOT_DIR / "settings.example.json"


def _load_settings() -> dict[str, Any]:
    """Le o primeiro arquivo de settings disponivel (local tem prioridade)."""
    for path in (SETTINGS_FILE, SETTINGS_EXAMPLE_FILE):
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
APP_VERSION = _app.get("version", "0.1.0")

# ---------------------------------------------------------------------------
# Textos institucionais do setor  ->  settings.json > "sector"
# (aparecem na tela inicial)
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
COLOR_PRIMARY = _theme.get("primary", "#008542")       # verde
COLOR_PRIMARY_DARK = _theme.get("primary_dark", "#00522A")
COLOR_ACCENT = _theme.get("accent", "#FFD000")         # amarelo
COLOR_BG = _theme.get("bg", "#0E1512")                 # fundo escuro
COLOR_SURFACE = _theme.get("surface", "#16211C")       # superficie/cards
COLOR_TEXT = _theme.get("text", "#EAF3EE")

# ---------------------------------------------------------------------------
# Catalogo de aplicativos  ->  settings.json > "catalog"
# ---------------------------------------------------------------------------
_local_file = _catalog.get("local_file", "data/catalog.json")
CATALOG_FILE = (ROOT_DIR / _local_file).resolve()
# URL de um catalog.json remoto (ex.: SharePoint). Deixe vazio/nulo para usar so o local.
REMOTE_CATALOG_URL: str | None = _catalog.get("remote_url") or None

# ---------------------------------------------------------------------------
# Pasta de dados do usuario (downloads e manifesto de instalados)
# ---------------------------------------------------------------------------
def _user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "SuitePetrobras"


USER_DATA_DIR = _user_data_dir()
DOWNLOADS_DIR = USER_DATA_DIR / "apps"
INSTALLED_MANIFEST = USER_DATA_DIR / "installed.json"
