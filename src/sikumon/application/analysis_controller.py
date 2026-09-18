"""Qt-thread coordination for structured cloud analysis."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot

from sikumon.application.analysis_service import (
    AnalysisOperationError,
    CompletedAnalysis,
    MeetingAnalysisService,
    PreparedAnalysis,
)
from sikumon.domain.enums import AnalysisOperationStatus
from sikumon.workers.analysis_worker import AnalysisWorker


class AnalysisController(QObject):
    state_changed = Signal(str, object)
    succeeded = Signal(str)
    failed = Signal(str, str)
    cancelled = Signal(str)
    operation_finished = Signal(str)

    def __init__(
        self, service: MeetingAnalysisService, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._thread: QThread | None = None
        self._worker: AnalysisWorker | None = None
        self._prepared: PreparedAnalysis | None = None
        self._cancellation: threading.Event | None = None

    @property
    def active_meeting_id(self) -> str | None:
        return self._prepared.meeting_id if self._prepared is not None else None

    @Slot(str)
    def start_analysis(self, meeting_id: str) -> None:
        if self._thread is not None:
            self.failed.emit(meeting_id, "ניתוח פגישה אחר כבר מתבצע.")
            return
        try:
            prepared = self._service.prepare(meeting_id)
        except AnalysisOperationError as error:
            self.failed.emit(meeting_id, error.user_message)
            return

        cancellation = threading.Event()
        thread = QThread(self)
        worker = AnalysisWorker(self._service, prepared, cancellation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
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
        self.state_changed.emit(meeting_id, AnalysisOperationStatus.RUNNING)
        try:
            thread.start()
        except RuntimeError:
            self._service.abort_prepared(prepared)
            self._prepared = None
            self._cancellation = None
            self._thread = None
            self._worker = None
            self.failed.emit(meeting_id, "לא ניתן להפעיל את תהליך הניתוח.")

    @Slot()
    def cancel_analysis(self) -> None:
        if self._cancellation is not None:
            self._cancellation.set()

    @Slot(object)
    def _on_success(self, result: CompletedAnalysis) -> None:
        self.state_changed.emit(result.meeting_id, AnalysisOperationStatus.COMPLETED)
        self.succeeded.emit(result.meeting_id)

    @Slot(object)
    def _on_failure(self, error: AnalysisOperationError) -> None:
        if self._prepared is not None:
            meeting_id = self._prepared.meeting_id
            self.state_changed.emit(meeting_id, AnalysisOperationStatus.FAILED)
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
