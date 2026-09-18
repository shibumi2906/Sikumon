"""Frozen-safe access to Sikumon's packaged visual resources."""

from __future__ import annotations

import sys
from pathlib import Path


def asset_path(name: str) -> Path:
    """Return an absolute asset path in source and PyInstaller runtimes."""

    if getattr(sys, "frozen", False):
        frozen_root = vars(sys).get("_MEIPASS")
        if not isinstance(frozen_root, str):
            raise RuntimeError("PyInstaller resource root is unavailable")
        return Path(frozen_root) / "sikumon" / "ui" / "assets" / name
    return Path(__file__).resolve().parent / "assets" / name
