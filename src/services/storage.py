"""Gerenciamento de pastas locais e do manifesto de aplicativos instalados."""
from __future__ import annotations

import json
from pathlib import Path

import config
from models import InstallState, InstallStatus


class Storage:
    """Persiste o estado de instalacao dos apps em ``installed.json``."""

    def __init__(
        self,
        downloads_dir: Path | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self.downloads_dir = downloads_dir or config.DOWNLOADS_DIR
        self.manifest_path = manifest_path or config.INSTALLED_MANIFEST
        self._ensure_dirs()
        self._states: dict[str, InstallState] = self._load_manifest()

    # ------------------------------------------------------------------
    def _ensure_dirs(self) -> None:
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    def app_dir(self, app_id: str) -> Path:
        path = self.downloads_dir / app_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    def _load_manifest(self) -> dict[str, InstallState]:
        if not self.manifest_path.exists():
            return {}
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        states: dict[str, InstallState] = {}
        for app_id, data in raw.items():
            try:
                states[app_id] = InstallState.from_dict(app_id, data)
            except (ValueError, TypeError):
                continue
        return states

    def _save_manifest(self) -> None:
        data = {app_id: st.to_dict() for app_id, st in self._states.items()}
        self.manifest_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    def get_state(self, app_id: str) -> InstallState:
        state = self._states.get(app_id)
        if state is None:
            return InstallState(app_id=app_id, status=InstallStatus.NOT_INSTALLED)
        # valida se o arquivo ainda existe
        if state.status == InstallStatus.INSTALLED and (
            not state.local_path or not Path(state.local_path).exists()
        ):
            return InstallState(app_id=app_id, status=InstallStatus.NOT_INSTALLED)
        return state

    def set_installed(self, app_id: str, local_path: Path, versao: str | None) -> InstallState:
        state = InstallState(
            app_id=app_id,
            status=InstallStatus.INSTALLED,
            local_path=str(local_path),
            versao=versao,
        )
        self._states[app_id] = state
        self._save_manifest()
        return state

    def clear(self, app_id: str) -> None:
        self._states.pop(app_id, None)
        self._save_manifest()
