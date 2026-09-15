"""Identidade do pack a partir de settings.json (app.name / app.exe_name)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_NAME = "SuiteApps"
DEFAULT_EXE = "SuiteApps"


def sanitize_exe_name(raw: str, default: str = DEFAULT_EXE) -> str:
    name = (raw or "").strip()
    for ch in ("/", "\\", ":", "*", "?", '"', "<", ">", "|"):
        name = name.replace(ch, "")
    name = name.strip().strip(".")
    if name.lower().endswith(".exe"):
        name = name[:-4]
    return name or default


def read_pack_identity(settings_path: Path) -> dict[str, str]:
    """Le o settings.json do operador. Nao inventa SuiteAPPs nem ignora chaves."""
    data: Any = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("settings.json raiz precisa ser um objeto JSON.")
    app = data.get("app") if isinstance(data.get("app"), dict) else {}

    name_raw = app.get("name")
    name = name_raw.strip() if isinstance(name_raw, str) and name_raw.strip() else DEFAULT_NAME

    exe_raw = app.get("exe_name")
    exe = sanitize_exe_name(
        str(exe_raw) if exe_raw is not None else "",
        DEFAULT_EXE,
    )

    version_raw = app.get("version")
    version = (
        str(version_raw).strip()
        if version_raw is not None and str(version_raw).strip()
        else "0.1.0"
    )

    company_raw = app.get("company")
    company = (
        company_raw.strip()
        if isinstance(company_raw, str) and company_raw.strip()
        else ""
    )

    return {
        "name": name,
        "exe_name": exe,
        "version": version,
        "company": company,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("uso: pack_identity.py <settings.json>", file=sys.stderr)
        return 2
    ident = read_pack_identity(Path(argv[1]))
    json.dump(ident, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
