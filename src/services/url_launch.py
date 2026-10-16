"""Abre https no navegador a partir de um clique sincrono.

Flet 0.90 tornou ``Page.launch_url`` assincrono e obsoleto. O caminho
atual e ``UrlLauncher().launch_url()``, tambem assincrono. O clique
agenda isso com ``page.run_task`` e da await. Sem ``UrlLauncher``,
cai em ``page.launch_url`` e espera a coroutine se ela vier.
"""
from __future__ import annotations

import inspect
from typing import Any


def open_https_url(page: Any, url: str) -> None:
    """Clique sincrono. So https. Nao deixa coroutine solta."""
    raw = (url or "").strip()
    if not raw.lower().startswith("https://") or page is None:
        return
    run_task = getattr(page, "run_task", None)
    if not callable(run_task):
        return
    try:
        run_task(launch_https, page, raw)
    except Exception:
        return


async def launch_https(page: Any, url: str) -> None:
    raw = (url or "").strip()
    if not raw.lower().startswith("https://"):
        return
    try:
        result = _start_launch(page, raw)
        if inspect.iscoroutine(result):
            await result
    except Exception:
        return


def _start_launch(page: Any, url: str) -> Any:
    import flet as ft

    launcher_cls = getattr(ft, "UrlLauncher", None)
    if launcher_cls is not None:
        launch = getattr(launcher_cls(), "launch_url", None)
        if callable(launch):
            return launch(url)
    launch = getattr(page, "launch_url", None)
    if not callable(launch):
        return None
    return launch(url)
