#!/usr/bin/env bash
# Run the SuiteApps hub as a Flutter *web* app for the headless Cloud Agent VM.
# Open the printed URL (default http://localhost:8550) in a browser to inspect
# the same UI the native desktop build shows.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
  echo "Virtualenv missing. Run 'bash .cursor/install.sh' first." >&2
  exit 1
fi

# Server-only mode: do not try to auto-launch a browser on the headless VM.
export FLET_FORCE_WEB_SERVER=true
export SUITEAPPS_WEB_PORT="${SUITEAPPS_WEB_PORT:-8550}"

exec .venv/bin/python .cursor/web_entry.py
