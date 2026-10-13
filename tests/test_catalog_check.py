"""Checagem automatica do catalogo: 10:00 em America/Sao_Paulo, uma vez por dia."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from catalog.provider import CatalogSyncResult
from main import SuiteApp
from models import AppInfo, CatalogData, SuiteUpdateInfo
from services import catalog_check
from services.catalog_check import (
    ZONE_NAME,
    ZoneUnavailable,
    already_checked_today,
    catalog_check_is_due,
    local_day,
    next_auto_check_at,
    sao_paulo_zone,
    seconds_until_auto_check,
    window_shows_catalog_notice,
    zone_source,
)
from services.preferences import PreferencesStore
from ui.progress_util import label as progress_label


def _at(hour: int, minute: int = 0, second: int = 0, day: int = 13) -> datetime:
    """Relogio de parede em America/Sao_Paulo (sem fuso: o modulo aplica a zona)."""
    return datetime(2026, 10, day, hour, minute, second)


def _sp(hour: int, minute: int = 0, second: int = 0, day: int = 13) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=sao_paulo_zone())


class ScheduleTests(unittest.TestCase):
    def test_before_ten_waits_until_today(self) -> None:
        now = _at(9, 59, 59)
        self.assertFalse(catalog_check_is_due("", now))
        self.assertEqual(seconds_until_auto_check("", now), 1.0)
        self.assertEqual(next_auto_check_at("", now), _sp(10, 0, 0))

    def test_exactly_ten_is_due(self) -> None:
        now = _at(10, 0, 0)
        self.assertTrue(catalog_check_is_due("", now))
        self.assertEqual(seconds_until_auto_check("", now), 0.0)

    def test_after_ten_without_a_check_is_the_catch_up(self) -> None:
        now = _at(15, 30)
        self.assertTrue(catalog_check_is_due("", now))
        self.assertTrue(catalog_check_is_due("2026-10-12", now))

    def test_same_local_day_does_not_run_again(self) -> None:
        now = _at(15, 30)
        last = local_day(now)
        self.assertTrue(already_checked_today(last, now))
        self.assertFalse(catalog_check_is_due(last, now))
        self.assertEqual(next_auto_check_at(last, now), _sp(10, day=14))

    def test_morning_after_yesterday_waits_for_today_at_ten(self) -> None:
        now = _at(9, 0)
        self.assertFalse(catalog_check_is_due("2026-10-12", now))
        self.assertEqual(next_auto_check_at("2026-10-12", now), _sp(10, 0, 0))

    def test_utc_and_other_zones_use_the_sao_paulo_day(self) -> None:
        # 10:00 UTC e 07:00 em Sao Paulo: ainda nao chegou a hora.
        utc_ten = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(local_day(utc_ten), "2026-10-13")
        self.assertFalse(catalog_check_is_due("", utc_ten))
        # 13:00 UTC e 10:00 em Sao Paulo (UTC-3, sem horario de verao).
        utc_thirteen = datetime(2026, 10, 13, 13, 0, tzinfo=timezone.utc)
        self.assertTrue(catalog_check_is_due("", utc_thirteen))
        self.assertEqual(seconds_until_auto_check("", utc_thirteen), 0.0)
        # 10:00 no Japao (UTC+9) ainda e 22:00 do dia anterior em Sao Paulo.
        japan = timezone(timedelta(hours=9))
        morning_japan = datetime(2026, 10, 13, 10, 0, tzinfo=japan)
        self.assertEqual(local_day(morning_japan), "2026-10-12")
        self.assertTrue(catalog_check_is_due("", morning_japan))
        self.assertFalse(catalog_check_is_due("2026-10-12", morning_japan))


class ZoneResolutionTests(unittest.TestCase):
    def test_zone_name_is_america_sao_paulo(self) -> None:
        zone = sao_paulo_zone()
        source = zone_source()
        self.assertIn(source, {"system", "tzdata"})
        self.assertEqual(getattr(zone, "key", None), ZONE_NAME)
        sample = datetime(2026, 10, 13, 12, 0, tzinfo=zone)
        self.assertEqual(sample.utcoffset(), timedelta(hours=-3))

    def test_fixed_brt_only_when_both_databases_are_missing(self) -> None:
        catalog_check.reset_zone_cache()
        try:
            with (
                patch.object(catalog_check, "_system_has_zone", return_value=False),
                patch.object(catalog_check, "_tzdata_package_available", return_value=False),
            ):
                zone, source = catalog_check._load_zone()
            self.assertEqual(source, "fixed-brt")
            self.assertIsNone(getattr(zone, "key", None))
            self.assertEqual(
                zone.utcoffset(datetime(2026, 6, 1, 12, 0)),
                timedelta(hours=-3),
            )
            wall = datetime(2026, 10, 13, 9, 30)
            with patch.object(catalog_check, "_resolved", (zone, source)):
                self.assertFalse(catalog_check_is_due("", wall))
                self.assertEqual(next_auto_check_at("", wall).hour, 10)
                self.assertEqual(local_day(wall), "2026-10-13")
        finally:
            catalog_check.reset_zone_cache()

    def test_tzdata_package_is_used_when_the_os_has_no_zone_file(self) -> None:
        catalog_check.reset_zone_cache()
        try:
            with (
                patch.object(catalog_check, "_system_has_zone", return_value=False),
                patch.object(catalog_check, "_tzdata_package_available", return_value=True),
                patch.object(catalog_check, "_zone_from_zoneinfo", return_value=timezone(timedelta(hours=-3))),
            ):
                _zone, source = catalog_check._load_zone()
            self.assertEqual(source, "tzdata")
        finally:
            catalog_check.reset_zone_cache()

    def test_broken_zoneinfo_falls_through_to_fixed_brt(self) -> None:
        catalog_check.reset_zone_cache()
        try:
            with (
                patch.object(catalog_check, "_system_has_zone", return_value=True),
                patch.object(catalog_check, "_tzdata_package_available", return_value=True),
                patch.object(
                    catalog_check,
                    "_zone_from_zoneinfo",
                    side_effect=ZoneUnavailable("missing"),
                ),
            ):
                _zone, source = catalog_check._load_zone()
            self.assertEqual(source, "fixed-brt")
        finally:
            catalog_check.reset_zone_cache()


class WindowNoticeTests(unittest.TestCase):
    def test_on_screen_shows_the_line(self) -> None:
        self.assertTrue(window_shows_catalog_notice(None))

        class Window:
            visible = True
            minimized = False

        self.assertTrue(window_shows_catalog_notice(Window()))

    def test_taskbar_and_tray_skip_the_line(self) -> None:
        class Minimized:
            visible = True
            minimized = True

        class Tray:
            visible = False
            minimized = True

        self.assertFalse(window_shows_catalog_notice(Minimized()))
        self.assertFalse(window_shows_catalog_notice(Tray()))


class PreferencesDateTests(unittest.TestCase):
    def test_date_roundtrip_keeps_other_prefs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            store = PreferencesStore(path)
            store.set_gerencia_id("ops")
            store.set_last_auto_catalog_check("2026-10-13")
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["gerencia_id"], "ops")
            self.assertEqual(raw["last_auto_catalog_check"], "2026-10-13")
            again = PreferencesStore(path)
            self.assertEqual(again.get_last_auto_catalog_check(), "2026-10-13")
            self.assertEqual(again.get_gerencia_id(), "ops")
            fresh = PreferencesStore(Path(tmp) / "empty.json")
            self.assertEqual(fresh.get_last_auto_catalog_check(), "")


class _Window:
    def __init__(self) -> None:
        self.visible = True
        self.minimized = False


class _Page:
    def __init__(self) -> None:
        self.window = _Window()
        self.threads: list = []

    def update(self) -> None:
        pass

    def run_thread(self, fn) -> None:
        self.threads.append(fn)


class _Holder:
    def __init__(self) -> None:
        self.content = None


class _Form:
    def __init__(self, message: str) -> None:
        self.message = message
        self.notice = ""


def _app(prefs: PreferencesStore) -> SuiteApp:
    app = SuiteApp.__new__(SuiteApp)
    app.page = _Page()
    app.preferences = prefs
    app.catalog = CatalogData(
        apps=[AppInfo(id="atual", nome="Atual")],
        suite=SuiteUpdateInfo(versao="9.0.0", download_url="https://sharepoint.example/suite.exe"),
    )
    app.selected_gerencia_id = ""
    app.sync_message = ""
    app.sync_notice = ""
    app._sync_notice_gen = 0
    app.sync_busy = False
    app.sync_progress = None
    app.sync_status = ""
    app._catalog_sync_lock = threading.Lock()
    app._sync_screen_visible = False
    app._auto_check_day = ""
    app._exiting = False
    app._catalog_shell = None
    app.content_holder = _Holder()
    app.publish_form = _Form("publico")
    app.structure = _Form("estrutura")
    app.selected_id = "atual"
    app.selected_setor = None
    app.show_favorites = False
    app.downloads: list[str] = []
    app.renders = 0
    app._render = lambda: setattr(app, "renders", app.renders + 1)
    app._download_suite_update = lambda: app.downloads.append("suite")
    return app


class _Provider:
    def __init__(self, result: CatalogSyncResult) -> None:
        self.result = result

    def sync(self, progress=None):
        if progress is not None:
            progress(1.0, "Catalogo sincronizado.")
        return self.result


class AutomaticSyncTests(unittest.TestCase):
    def _prefs(self, tmp: str) -> PreferencesStore:
        return PreferencesStore(Path(tmp) / "preferences.json")

    def test_success_shows_the_sidebar_line_and_does_not_download_suite(self) -> None:
        incoming = CatalogData(
            apps=[AppInfo(id="novo", nome="Novo", versao="2")],
            suite=SuiteUpdateInfo(versao="9.9.9", download_url="https://sharepoint.example/suite.exe"),
        )
        result = CatalogSyncResult(catalog=incoming, message="", ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(self._prefs(tmp))
            provider = _Provider(result)
            with (
                patch("main.SharePointCatalogProvider", return_value=provider),
                patch("main.sao_paulo_now", return_value=_at(10, 5)),
                patch("main.baixar_do_sharepoint") as download,
            ):
                SuiteApp._sync_catalog_worker(app, False, automatic=True)
            self.assertIs(app.catalog, incoming)
            self.assertEqual(
                app.sync_notice,
                progress_label(1.0, "Catalogo sincronizado."),
            )
            self.assertEqual(app.preferences.get_last_auto_catalog_check(), "2026-10-13")
            self.assertEqual(app.publish_form.message, "publico")
            self.assertEqual(app.structure.message, "estrutura")
            self.assertEqual(app.downloads, [])
            download.assert_not_called()
            self.assertEqual(len(app.page.threads), 1)

    def test_hidden_window_still_syncs_without_the_line(self) -> None:
        incoming = CatalogData(apps=[AppInfo(id="novo", nome="Novo")])
        result = CatalogSyncResult(catalog=incoming, ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(self._prefs(tmp))
            app.page.window.visible = False
            with (
                patch("main.SharePointCatalogProvider", return_value=_Provider(result)),
                patch("main.sao_paulo_now", return_value=_at(10, 5)),
            ):
                SuiteApp._sync_catalog_worker(app, False, automatic=True)
            self.assertIs(app.catalog, incoming)
            self.assertEqual(app.sync_notice, "")
            self.assertEqual(app.preferences.get_last_auto_catalog_check(), "2026-10-13")
            self.assertEqual(app.page.threads, [])

    def test_failure_keeps_the_catalog_and_a_short_message(self) -> None:
        current_apps = [AppInfo(id="atual", nome="Atual")]
        incoming = CatalogData(apps=[AppInfo(id="remoto", nome="Remoto")])
        result = CatalogSyncResult(
            catalog=incoming,
            message="Falha ao sincronizar catalogo (powershell dump enorme). Usando cache.",
            ok=False,
            from_cache=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(self._prefs(tmp))
            kept = app.catalog
            kept.apps = current_apps
            with (
                patch("main.SharePointCatalogProvider", return_value=_Provider(result)),
                patch("main.sao_paulo_now", return_value=_at(11, 0)),
                patch("main.baixar_do_sharepoint") as download,
            ):
                SuiteApp._sync_catalog_worker(app, False, automatic=True)
            self.assertIs(app.catalog, kept)
            self.assertEqual(app.catalog.apps[0].id, "atual")
            self.assertEqual(app.sync_message, "Falha ao buscar atualizacoes.")
            self.assertNotIn("powershell", app.sync_message.lower())
            self.assertEqual(app.sync_notice, "")
            self.assertEqual(app.publish_form.message, "publico")
            self.assertEqual(app.structure.message, "estrutura")
            self.assertEqual(app.preferences.get_last_auto_catalog_check(), "2026-10-13")
            self.assertEqual(app.downloads, [])
            download.assert_not_called()

    def test_exception_keeps_the_catalog_and_marks_the_day(self) -> None:
        class Boom:
            def sync(self, progress=None):
                raise RuntimeError("powershell traceback enorme")

        with tempfile.TemporaryDirectory() as tmp:
            app = _app(self._prefs(tmp))
            kept = app.catalog
            with (
                patch("main.SharePointCatalogProvider", return_value=Boom()),
                patch("main.sao_paulo_now", return_value=_at(10, 5)),
                patch("main.baixar_do_sharepoint") as download,
            ):
                SuiteApp._sync_catalog_worker(app, False, automatic=True)
            self.assertIs(app.catalog, kept)
            self.assertEqual(app.sync_message, "Falha ao buscar atualizacoes.")
            self.assertNotIn("powershell", app.sync_message.lower())
            self.assertEqual(app.sync_notice, "")
            self.assertEqual(app.publish_form.message, "publico")
            self.assertEqual(app.structure.message, "estrutura")
            self.assertEqual(app.preferences.get_last_auto_catalog_check(), "2026-10-13")
            self.assertFalse(app.sync_busy)
            self.assertEqual(app.downloads, [])
            download.assert_not_called()

    def test_manual_failure_is_unchanged_and_does_not_mark_the_day(self) -> None:
        incoming = CatalogData(apps=[AppInfo(id="remoto", nome="Remoto")])
        result = CatalogSyncResult(
            catalog=incoming,
            message="Falha ao sincronizar catalogo (detalhe). Usando cache.",
            ok=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(self._prefs(tmp))
            kept = app.catalog
            with patch("main.SharePointCatalogProvider", return_value=_Provider(result)):
                SuiteApp._sync_catalog_worker(app, False, automatic=False)
            self.assertIs(app.catalog, kept)
            self.assertIn("detalhe", app.sync_message)
            self.assertEqual(app.preferences.get_last_auto_catalog_check(), "")

    def test_progress_does_not_write_the_line_onto_the_catalog_shell(self) -> None:
        import flet as ft

        shell = ft.Column(
            controls=[ft.Text("Catalogo"), ft.Text("abas"), ft.Text("corpo")],
        )
        other = ft.Column(
            controls=[
                ft.ProgressBar(),
                ft.Text("meio"),
                ft.Text("antes"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(self._prefs(tmp))
            app._catalog_shell = shell
            app.content_holder.content = shell
            body = shell.controls[2]
            app._sync_screen_visible = True
            SuiteApp._on_sync_progress(app, 1.0, "Catalogo sincronizado.")
            self.assertIs(shell.controls[2], body)
            self.assertEqual(body.value, "corpo")
            app.content_holder.content = other
            app._sync_screen_visible = False
            SuiteApp._on_sync_progress(app, 1.0, "Catalogo sincronizado.")
            self.assertEqual(other.controls[2].value, "antes")
            self.assertEqual(app.publish_form.message, "publico")
            self.assertEqual(app.structure.message, "estrutura")


class ConsiderTests(unittest.TestCase):
    def test_due_starts_the_button_sync_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(PreferencesStore(Path(tmp) / "preferences.json"))
            calls: list[bool] = []

            def start(*, automatic: bool) -> bool:
                calls.append(automatic)
                app.sync_busy = True
                return True

            app._start_catalog_sync = start  # type: ignore[method-assign]
            self.assertEqual(SuiteApp._consider_auto_catalog_check(app, _at(9, 0)), "wait")
            self.assertEqual(calls, [])
            self.assertEqual(SuiteApp._consider_auto_catalog_check(app, _at(10, 0)), "started")
            self.assertEqual(calls, [True])
            app.sync_busy = True
            self.assertEqual(SuiteApp._consider_auto_catalog_check(app, _at(10, 1)), "busy")
            app.sync_busy = False
            app.preferences.set_last_auto_catalog_check("2026-10-13")
            self.assertEqual(SuiteApp._consider_auto_catalog_check(app, _at(18, 0)), "wait")
            self.assertEqual(calls, [True])

    def test_start_refuses_a_second_sync_and_never_downloads_the_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = _app(PreferencesStore(Path(tmp) / "preferences.json"))
            self.assertTrue(SuiteApp._start_catalog_sync(app, automatic=True))
            self.assertTrue(app.sync_busy)
            self.assertFalse(SuiteApp._start_catalog_sync(app, automatic=True))
            self.assertEqual(len(app.page.threads), 1)
            self.assertEqual(app.downloads, [])


if __name__ == "__main__":
    unittest.main()
