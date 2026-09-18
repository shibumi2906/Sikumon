"""Runtime settings supplied to application infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    """Overrides that make infrastructure deterministic and testable."""

    data_root: Path | None = None
    ffprobe_path: Path | None = None
    log_level: int = 20
