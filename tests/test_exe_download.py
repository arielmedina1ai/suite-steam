"""Exe baixado so conta como instalado se tiver cabecalho MZ/PE."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import AppInfo, AppType, InstallStatus
from services.download_manager import DownloadManager, DownloadOutcome
from services.runner import RunError, launch_file
from services.sharepoint_manager import SharePointResult
from services.storage import Storage
from services.win_exe import INVALID_EXE_MESSAGE


def _pe_minimo() -> bytes:
    dados = bytearray(68)
    dados[0:2] = b"MZ"
    dados[0x3C:0x40] = (64).to_bytes(4, "little")
    dados[64:68] = b"PE\x00\x00"
    return bytes(dados)


def _app(**kwargs) -> AppInfo:
    base = dict(
        id="planejador",
        nome="Planejador Operacoes",
        download_url="https://x/Planejador.exe",
        versao="2.4.0",
    )
    base.update(kwargs)
    return AppInfo(**base)


class ExeDownloadTests(unittest.TestCase):
    def _baixar(self, storage: Storage, app: AppInfo, payload: bytes):
        def fake(link, pasta_destino, nome_arquivo, progress=None):
            path = Path(pasta_destino) / nome_arquivo
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            return SharePointResult(ok=True, path=path, message="Download concluido.")

        with (
            patch("services.download_manager.baixar_do_sharepoint", fake),
            patch("services.download_manager.webbrowser.open") as browser,
        ):
            result = DownloadManager(storage).download(app)
        return result, browser

    def test_html_nao_instala_e_nao_deixa_o_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "apps", root / "installed.json")
            app = _app()
            result, browser = self._baixar(
                storage,
                app,
                b"<html><body>Faca login</body></html>",
            )
            destino = root / "apps" / app.id / "planejador.exe"
            self.assertEqual(result.outcome, DownloadOutcome.ERROR)
            self.assertEqual(result.message, INVALID_EXE_MESSAGE)
            self.assertEqual(storage.get_state(app.id).status, InstallStatus.NOT_INSTALLED)
            self.assertFalse(destino.exists())
            self.assertEqual(list((root / "apps" / app.id).iterdir()), [])
            browser.assert_not_called()

    def test_bytes_sem_pe_nao_instalam(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "apps", root / "installed.json")
            app = _app()
            incompleto = b"MZ" + b"\x00" * 80
            result, browser = self._baixar(storage, app, incompleto)
            destino = root / "apps" / app.id / "planejador.exe"
            self.assertEqual(result.outcome, DownloadOutcome.ERROR)
            self.assertEqual(result.message, INVALID_EXE_MESSAGE)
            self.assertEqual(storage.get_state(app.id).status, InstallStatus.NOT_INSTALLED)
            self.assertFalse(destino.exists())
            self.assertFalse(any((root / "apps" / app.id).iterdir()))
            browser.assert_not_called()

    def test_download_invalido_nao_substitui_exe_instalado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "apps", root / "installed.json")
            app = _app()
            destino = storage.app_dir(app.id) / "planejador.exe"
            pe = _pe_minimo()
            destino.write_bytes(pe)
            storage.set_installed(app.id, destino, "2.3.0")
            result, browser = self._baixar(storage, app, b"<html>erro</html>")
            self.assertEqual(result.outcome, DownloadOutcome.ERROR)
            self.assertEqual(result.message, INVALID_EXE_MESSAGE)
            self.assertEqual(destino.read_bytes(), pe)
            state = storage.get_state(app.id)
            self.assertEqual(state.status, InstallStatus.INSTALLED)
            self.assertEqual(state.versao, "2.3.0")
            self.assertEqual(state.local_path, str(destino))
            self.assertEqual([item.name for item in destino.parent.iterdir()], ["planejador.exe"])
            browser.assert_not_called()

    def test_pe_minimo_instala_e_abre(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "apps", root / "installed.json")
            app = _app()
            pe = _pe_minimo()
            result, browser = self._baixar(storage, app, pe)
            destino = root / "apps" / app.id / "planejador.exe"
            self.assertEqual(result.outcome, DownloadOutcome.SUCCESS)
            self.assertEqual(result.local_path, destino)
            self.assertEqual(destino.read_bytes(), pe)
            self.assertIn("Download concluido.", result.message)
            state = storage.get_state(app.id)
            self.assertEqual(state.status, InstallStatus.INSTALLED)
            self.assertEqual(state.versao, "2.4.0")
            self.assertEqual([item.name for item in destino.parent.iterdir()], ["planejador.exe"])
            browser.assert_not_called()

            proc = type("Proc", (), {"poll": lambda self: None, "wait": lambda self: 0})()
            with (
                patch("services.runner.sys.platform", "win32"),
                patch("services.runner.subprocess.Popen", return_value=proc) as popen,
            ):
                running = launch_file(destino, app_id=app.id, app_name=app.nome)
            popen.assert_called_once_with([str(destino)], cwd=str(destino.parent))
            self.assertEqual(running.app_id, app.id)
            self.assertEqual(running.app_name, app.nome)

    def test_abrir_exe_invalido_nao_chama_o_processo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Planejador Operacoes.exe"
            path.write_bytes(b"<html>nao e exe</html>")
            with patch("services.runner.subprocess.Popen") as popen:
                with self.assertRaises(RunError) as ctx:
                    launch_file(path)
            self.assertEqual(str(ctx.exception), INVALID_EXE_MESSAGE)
            popen.assert_not_called()

    def test_planilha_sem_pe_continua_instalando(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "apps", root / "installed.json")
            app = _app(
                id="relatorio",
                nome="Relatorio",
                tipo=AppType.XLSM,
                download_url="https://x/app.xlsm",
                versao="1.2.0",
            )
            corpo = b"<html>planilha</html>"
            result, _browser = self._baixar(storage, app, corpo)
            destino = root / "apps" / app.id / "relatorio.xlsm"
            self.assertEqual(result.outcome, DownloadOutcome.SUCCESS)
            self.assertEqual(destino.read_bytes(), corpo)
            self.assertEqual(storage.get_state(app.id).status, InstallStatus.INSTALLED)


if __name__ == "__main__":
    unittest.main()
