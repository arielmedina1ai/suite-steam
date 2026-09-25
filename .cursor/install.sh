#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the SuiteApps hub.
#
# SuiteApps is a Flet (Python) desktop app. The production catalog is synced
# from SharePoint via Windows PowerShell + PnP, which is unavailable on Linux
# cloud VMs. This script prepares a fully working *offline* dev environment so
# the hub UI can be run and inspected (in web mode) without SharePoint.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# --- System dependency: python venv module -------------------------------
if ! dpkg -s python3-venv >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y python3-venv
fi

# --- Python virtualenv + dependencies -------------------------------------
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# --- Local dev settings (gitignored) --------------------------------------
# Copy settings.example.json but blank catalog.remote_url so the hub renders
# the bundled sample catalog offline instead of failing on a SharePoint sync.
if [ ! -f settings.json ]; then
  .venv/bin/python - <<'PY'
import json, pathlib
ex = json.loads(pathlib.Path("settings.example.json").read_text(encoding="utf-8"))
ex.setdefault("app", {})["company"] = ex.get("app", {}).get("company") or "Demo Corp"
sec = ex.setdefault("sector", {})
sec["name"] = "Central de Aplicativos"
sec["description"] = (
    "Ambiente de demonstracao do SuiteApps. Este hub reune os aplicativos "
    "internos por gerencia e setor. Selecione uma gerencia na barra lateral "
    "para filtrar, ou navegue por setores."
)
ex.setdefault("catalog", {})["remote_url"] = ""
pathlib.Path("settings.json").write_text(
    json.dumps(ex, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("Wrote dev settings.json (offline sample catalog)")
PY
fi

# --- Local branding (gitignored) ------------------------------------------
# Promote the *.example.png assets to their production names so the sidebar
# logo and home hero render.
for name in logo hero window_icon; do
  if [ -f "assets/branding/${name}.example.png" ] && [ ! -f "assets/branding/${name}.png" ]; then
    cp "assets/branding/${name}.example.png" "assets/branding/${name}.png"
  fi
done

# --- Seed the offline catalog cache ---------------------------------------
# Write the sample catalog into the user data dir the app reads from, with the
# SharePoint media URLs blanked (they can't be fetched here) so app cards use
# the built-in type icons cleanly.
.venv/bin/python - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "src")
import config  # noqa: E402
cache = config.CATALOG_CACHE_FILE
cache.parent.mkdir(parents=True, exist_ok=True)
config.CATALOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
if not cache.exists():
    data = json.loads(pathlib.Path("catalog.example.json").read_text(encoding="utf-8"))
    for app in data.get("apps", []):
        app["imagem"] = ""
        app["icone"] = ""
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Seeded offline catalog cache at {cache}")
else:
    print(f"Catalog cache already present at {cache}")
PY

echo "SuiteApps environment ready."
