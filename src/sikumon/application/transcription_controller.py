"""Qt-thread coordination for the global local-transcription operation."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot

from sikumon.application.transcription_service import (
    CompletedTranscription,
    PreparedTranscription,
    TranscriptionOperationError,
    TranscriptionProgress,
    TranscriptionService,
)
from sikumon.domain.enums import TranscriptionStatus
from sikumon.workers.transcription_worker import TranscriptionWorker


class TranscriptionController(QObject):
    state_changed = Signal(str, object)
    progress_changed = Signal(str, object)
    succeeded = Signal(str)
    failed = Signal(str, str)
    cancelled = Signal(str)
    operation_finished = Signal(str)

    def __init__(self, service: TranscriptionService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._thread: QThread | None = None
        self._worker: TranscriptionWorker | None = None
        self._prepared: PreparedTranscription | None = None
        self._cancellation: threading.Event | None = None

    @property
    def active_meeting_id(self) -> str | None:
        return self._prepared.meeting_id if self._prepared is not None else None

    @Slot(str)
    def start_transcription(self, meeting_id: str) -> None:
        if self._thread is not None:
            self.failed.emit(meeting_id, "תמלול אחר כבר מתבצע.")
            return
        try:
            prepared = self._service.prepare(meeting_id)
        except TranscriptionOperationError as error:
            self.failed.emit(meeting_id, error.user_message)
            return

        cancellation = threading.Event()
        thread = QThread(self)
        worker = TranscriptionWorker(self._service, prepared, cancellation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._on_progress)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failure)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._prepared = prepared
        self._cancellation = cancellation
        self._thread = thread
        self._worker = worker
        self.state_changed.emit(meeting_id, TranscriptionStatus.RUNNING)
        try:
            thread.start()
        except RuntimeError:
            self._service.abort_prepared(prepared)
            self._prepared = None
            self._cancellation = None
            self._thread = None
            self._worker = None
            self.failed.emit(meeting_id, "לא ניתן להפעיל את תהליך התמלול.")

    @Slot()
    def cancel_transcription(self) -> None:
        if self._cancellation is not None:
            self._cancellation.set()

    @Slot(object)
    def _on_progress(self, progress: TranscriptionProgress) -> None:
        if self._prepared is not None:
            self.progress_changed.emit(self._prepared.meeting_id, progress)

    @Slot(object)
    def _on_success(self, result: CompletedTranscription) -> None:
        self.state_changed.emit(result.meeting_id, TranscriptionStatus.COMPLETED)
        self.succeeded.emit(result.meeting_id)

    @Slot(object)
    def _on_failure(self, error: TranscriptionOperationError) -> None:
        if self._prepared is not None:
            meeting_id = self._prepared.meeting_id
            self.state_changed.emit(meeting_id, TranscriptionStatus.FAILED)
            self.failed.emit(meeting_id, error.user_message)

    @Slot()
    def _on_cancelled(self) -> None:
        if self._prepared is not None:
            self.cancelled.emit(self._prepared.meeting_id)

    @Slot()
    def _on_thread_finished(self) -> None:
        meeting_id = self._prepared.meeting_id if self._prepared is not None else ""
        self._thread = None
        self._worker = None
        self._prepared = None
        self._cancellation = None
        if meeting_id:
            self.operation_finished.emit(meeting_id)
