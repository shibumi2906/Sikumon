"""Application-level Qt coordination for STT model management."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from sikumon.services.transcription.model_manager import (
    DownloadProgress,
    ModelAvailability,
    ModelManagementError,
    ModelManager,
)
from sikumon.workers.model_download_worker import ModelDownloadWorker


class ModelManagementController(QObject):
    state_changed = Signal(object)
    progress_changed = Signal(object)
    error_changed = Signal(str)
    operation_finished = Signal()

    def __init__(self, manager: ModelManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._thread: QThread | None = None
        self._worker: ModelDownloadWorker | None = None

    @property
    def availability(self) -> ModelAvailability:
        return self._manager.availability

    @property
    def model_directory(self) -> str:
        return str(self._manager.model_directory)

    @property
    def error_message(self) -> str | None:
        error = self._manager.last_error
        return error.user_message if error is not None else None

    @property
    def is_active(self) -> bool:
        return self._thread is not None

    @Slot()
    def start_download(self) -> None:
        if self._thread is not None:
            return
        self.error_changed.emit("")
        thread = QThread(self)
        worker = ModelDownloadWorker(self._manager)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.state_changed.connect(self._forward_state)
        worker.progress_changed.connect(self._forward_progress)
        worker.failed.connect(self._on_failure)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        try:
            thread.start()
        except RuntimeError as error:
            self._thread = None
            self._worker = None
            controlled = self._manager.normalize_unexpected_failure(error)
            self.error_changed.emit(controlled.user_message)
            self.operation_finished.emit()

    @Slot()
    def cancel_download(self) -> None:
        if self._thread is not None:
            self._manager.request_cancellation()

    @Slot(object)
    def _forward_state(self, state: ModelAvailability) -> None:
        self.state_changed.emit(state)

    @Slot(object)
    def _forward_progress(self, progress: DownloadProgress) -> None:
        self.progress_changed.emit(progress)

    @Slot(object)
    def _on_failure(self, error: ModelManagementError) -> None:
        self.error_changed.emit(error.user_message)

    @Slot()
    def _on_cancelled(self) -> None:
        self.error_changed.emit("ההורדה בוטלה. אפשר להתחיל אותה מחדש.")

    @Slot()
    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.operation_finished.emit()
