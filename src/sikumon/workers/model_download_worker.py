"""Qt worker for model download and expensive local verification."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal, Slot

from sikumon.services.transcription.model_manager import (
    ModelDownloadCancelled,
    ModelManagementError,
    ModelManager,
)


class ModelDownloadWorker(QObject):
    state_changed = Signal(object)
    progress_changed = Signal(object)
    succeeded = Signal(object)
    cancelled = Signal()
    failed = Signal(object)
    finished = Signal()

    def __init__(self, manager: ModelManager, replace_existing: bool = False) -> None:
        super().__init__()
        self._manager = manager
        self._replace_existing = replace_existing

    @Slot()
    def run(self) -> None:
        try:
            marker = self._manager.download_and_verify(
                state_callback=self.state_changed.emit,
                progress_callback=self.progress_changed.emit,
                replace_existing=self._replace_existing,
            )
            self.succeeded.emit(marker)
        except ModelDownloadCancelled:
            self.cancelled.emit()
        except ModelManagementError as error:
            self.failed.emit(error)
        except Exception as error:
            logging.getLogger("sikumon.workers.model_download").exception(
                "Unexpected model download worker failure"
            )
            self.failed.emit(self._manager.normalize_unexpected_failure(error))
        finally:
            self.finished.emit()
