"""O download instala o arquivo que o SharePoint devolveu."""
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
from services.runner import launch_file
from services.sharepoint_manager import SharePointResult
from services.storage import Storage


def _app(**kwargs) -> AppInfo:
    base = dict(
        id="planejador",
        nome="Planejador Operacoes",
        download_url="https://x/Planejador.exe",
        versao="2.4.0",
    )
    base.update(kwargs)
    return AppInfo(**base)


class DownloadRestauradoTests(unittest.TestCase):
    def _baixar(self, storage: Storage, app: AppInfo, payload: bytes):
        nomes: list[str] = []

        def fake(link, pasta_destino, nome_arquivo, progress=None):
            nomes.append(nome_arquivo)
            path = Path(pasta_destino) / nome_arquivo
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            return SharePointResult(ok=True, path=path, message="Download concluido.")

        with (
            patch("services.download_manager.baixar_do_sharepoint", fake),
            patch("services.download_manager.webbrowser.open") as browser,
        ):
            result = DownloadManager(storage).download(app)
        return result, browser, nomes

    def test_exe_sem_mz_e_instalado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "apps", root / "installed.json")
            app = _app()
            corpo = b"<html><body>Faca login</body></html>"
            result, browser, nomes = self._baixar(storage, app, corpo)
            destino = root / "apps" / app.id / "planejador.exe"
            self.assertEqual(nomes, ["planejador.exe"])
            self.assertEqual(result.outcome, DownloadOutcome.SUCCESS)
            self.assertEqual(result.local_path, destino)
            self.assertEqual(destino.read_bytes(), corpo)
            self.assertIn("Download concluido.", result.message)
            state = storage.get_state(app.id)
            self.assertEqual(state.status, InstallStatus.INSTALLED)
            self.assertEqual(state.versao, "2.4.0")
            self.assertEqual(state.local_path, str(destino))
            browser.assert_not_called()

    def test_novo_download_substitui_o_arquivo_anterior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = Storage(root / "apps", root / "installed.json")
            app = _app()
            destino = storage.app_dir(app.id) / "planejador.exe"
            destino.write_bytes(b"exe anterior")
            storage.set_installed(app.id, destino, "2.3.0")
            novo = b"<html>arquivo novo</html>"
            result, browser, _nomes = self._baixar(storage, app, novo)
            self.assertEqual(result.outcome, DownloadOutcome.SUCCESS)
            self.assertEqual(destino.read_bytes(), novo)
            state = storage.get_state(app.id)
            self.assertEqual(state.status, InstallStatus.INSTALLED)
            self.assertEqual(state.versao, "2.4.0")
            self.assertEqual(state.local_path, str(destino))
            self.assertEqual([item.name for item in destino.parent.iterdir()], ["planejador.exe"])
            browser.assert_not_called()

    def test_abrir_exe_sem_mz_segue_para_o_processo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Planejador Operacoes.exe"
            path.write_bytes(b"<html>nao e exe</html>")
            proc = type("Proc", (), {"poll": lambda self: None, "wait": lambda self: 0})()
            with (
                patch("services.runner.sys.platform", "win32"),
                patch("services.runner.subprocess.Popen", return_value=proc) as popen,
            ):
                running = launch_file(path, app_id="planejador", app_name="Planejador Operacoes")
            popen.assert_called_once_with([str(path)], cwd=str(path.parent))
            self.assertEqual(running.app_id, "planejador")
            self.assertEqual(running.app_name, "Planejador Operacoes")

    def test_planilha_continua_instalando(self) -> None:
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
            result, _browser, nomes = self._baixar(storage, app, corpo)
            destino = root / "apps" / app.id / "relatorio.xlsm"
            self.assertEqual(nomes, ["relatorio.xlsm"])
            self.assertEqual(result.outcome, DownloadOutcome.SUCCESS)
            self.assertEqual(destino.read_bytes(), corpo)
            self.assertEqual(storage.get_state(app.id).status, InstallStatus.INSTALLED)


if __name__ == "__main__":
    unittest.main()
