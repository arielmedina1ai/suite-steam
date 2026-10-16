"""UrlLauncher awaited a partir do clique, com fallback antigo."""
from __future__ import annotations

import asyncio
import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flet as ft

from services.url_launch import open_https_url


class _Page:
    def __init__(self) -> None:
        self.ran: list[tuple] = []

    def run_task(self, handler, *args, **kwargs):
        self.ran.append((handler, args))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            asyncio.run(handler(*args, **kwargs))
        self.warnings = [str(item.message) for item in caught]


class UrlLaunchTests(unittest.TestCase):
    def test_https_uses_url_launcher_and_awaits_it(self) -> None:
        opened: list[str] = []

        class Launcher:
            async def launch_url(self, url: str) -> None:
                opened.append(url)

        page = _Page()
        with patch.object(ft, "UrlLauncher", lambda: Launcher()):
            open_https_url(page, "https://exemplo.com/guia")
        self.assertEqual(opened, ["https://exemplo.com/guia"])
        self.assertEqual(page.warnings, [])

    def test_non_https_does_not_launch(self) -> None:
        page = _Page()
        open_https_url(page, "http://exemplo.com")
        open_https_url(page, "")
        self.assertEqual(page.ran, [])

    def test_missing_url_launcher_awaits_page_launch_url(self) -> None:
        opened: list[str] = []

        class Page(_Page):
            async def launch_url(self, url: str) -> None:
                opened.append(url)

        page = Page()
        with patch.object(ft, "UrlLauncher", None):
            open_https_url(page, "https://exemplo.com/antigo")
        self.assertEqual(opened, ["https://exemplo.com/antigo"])
        self.assertFalse(any("never awaited" in msg for msg in page.warnings))


if __name__ == "__main__":
    unittest.main()
