"""Headless/web launcher for the SuiteApps hub (Cloud Agent dev preview).

The production entry point (``src/main.py``) opens a native desktop window via
Flet. Cloud Agent VMs are headless, so this helper boots the exact same
``SuiteApp`` UI as a Flutter *web* app that can be opened in a browser.

It does not modify application behaviour: it imports ``main`` from ``src`` and
runs it with the same assets directory, only switching the Flet view to
``WEB_BROWSER``. Set ``FLET_FORCE_WEB_SERVER=true`` to keep it as a pure server
(no auto-launched browser), which is the intended cloud usage.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import flet as ft  # noqa: E402
import config  # noqa: E402
from main import main  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("SUITEAPPS_WEB_PORT", "8550"))
    host = os.environ.get("SUITEAPPS_WEB_HOST", "0.0.0.0")
    ft.run(
        main,
        assets_dir=str(config.ASSETS_DIR),
        view=ft.AppView.WEB_BROWSER,
        host=host,
        port=port,
    )
