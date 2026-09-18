"""Application-data path resolution and creation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sikumon.config.constants import (
    APP_DATA_FOLDER,
    CACHE_FOLDER,
    DATABASE_FILENAME,
    LOG_FOLDER,
    MEETINGS_FOLDER,
    MODELS_FOLDER,
)


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    root: Path
    database: Path
    models: Path
    meetings: Path
    logs: Path
    cache: Path

    @classmethod
    def resolve(cls, data_root: Path | None = None) -> ApplicationPaths:
        if data_root is None:
            local_app_data = os.environ.get("LOCALAPPDATA")
            if not local_app_data:
                raise RuntimeError("LOCALAPPDATA is not defined; an explicit data_root is required")
            root = Path(local_app_data) / APP_DATA_FOLDER
        else:
            root = Path(data_root)
        return cls(
            root=root,
            database=root / DATABASE_FILENAME,
            models=root / MODELS_FOLDER,
            meetings=root / MEETINGS_FOLDER,
            logs=root / LOG_FOLDER,
            cache=root / CACHE_FOLDER,
        )

    def ensure_directories(self) -> None:
        for directory in (self.root, self.models, self.meetings, self.logs, self.cache):
            directory.mkdir(parents=True, exist_ok=True)

