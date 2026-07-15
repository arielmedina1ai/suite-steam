"""Constantes de configuracao e textos institucionais da Suite Petrobras."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Suite Petrobras"
APP_VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Caminhos do projeto
# ---------------------------------------------------------------------------
SRC_DIR = Path(__file__).resolve().parent
ROOT_DIR = SRC_DIR.parent
ASSETS_DIR = ROOT_DIR / "assets"
DATA_DIR = ROOT_DIR / "data"
CATALOG_FILE = DATA_DIR / "catalog.json"

# ---------------------------------------------------------------------------
# Pasta de dados do usuario (downloads e manifesto de instalados)
# ---------------------------------------------------------------------------
def _user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "SuitePetrobras"


USER_DATA_DIR = _user_data_dir()
DOWNLOADS_DIR = USER_DATA_DIR / "apps"
INSTALLED_MANIFEST = USER_DATA_DIR / "installed.json"

# ---------------------------------------------------------------------------
# Catalogo remoto (SharePoint) - preparado para o futuro.
# Defina a URL de um catalog.json hospedado para habilitar o modo remoto.
# ---------------------------------------------------------------------------
REMOTE_CATALOG_URL: str | None = None

# ---------------------------------------------------------------------------
# Identidade visual (cores Petrobras)
# ---------------------------------------------------------------------------
COLOR_PRIMARY = "#008542"      # verde Petrobras
COLOR_PRIMARY_DARK = "#00522A"
COLOR_ACCENT = "#FFD000"       # amarelo
COLOR_BG = "#0E1512"           # fundo escuro
COLOR_SURFACE = "#16211C"      # superficie/cards
COLOR_TEXT = "#EAF3EE"

# ---------------------------------------------------------------------------
# Textos institucionais do setor (edite conforme necessario)
# ---------------------------------------------------------------------------
SECTOR_NAME = "Setor de Desenvolvimento de Solucoes"
SECTOR_TAGLINE = "Nossos aplicativos, em um so lugar."
SECTOR_DESCRIPTION = (
    "Bem-vindo a Suite Petrobras, o hub central dos programas desenvolvidos pelo "
    "nosso setor. Aqui voce encontra, baixa e executa as ferramentas internas de forma "
    "simples e centralizada - do mesmo jeito que uma loja de aplicativos, porem feita "
    "sob medida para as nossas necessidades.\n\n"
    "Navegue pelo menu lateral para conhecer os aplicativos disponiveis. Cada programa "
    "possui uma pagina com descricao, imagem e a opcao de download e execucao."
)
