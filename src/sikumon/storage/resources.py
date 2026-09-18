"""Resolve read-only resources shipped beside the application executable."""

from __future__ import annotations

import sys
from pathlib import Path


def application_bundle_root() -> Path:
    """Return PyInstaller's read-only resource root or the source project root."""

    if getattr(sys, "frozen", False):
        frozen_resources = getattr(sys, "_MEIPASS", None)
        if frozen_resources is not None:
            return Path(frozen_resources).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def bundled_tool_path(filename: str) -> Path | None:
    """Return a bundled media tool only when the expected file really exists."""

    candidate = application_bundle_root() / "tools" / filename
    return candidate if candidate.is_file() else None
