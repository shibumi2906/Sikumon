"""Qt worker for cloud analysis outside the UI thread."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from sikumon.application.analysis_service import (
    AnalysisCancelled,
    AnalysisOperationError,
    MeetingAnalysisService,
    PreparedAnalysis,
)


class AnalysisWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        service: MeetingAnalysisService,
        prepared: PreparedAnalysis,
        cancellation: threading.Event,
    ) -> None:
        super().__init__()
        self._service = service
        self._prepared = prepared
        self._cancellation = cancellation

    @Slot()
    def run(self) -> None:
        try:
            result = self._service.execute(self._prepared, self._cancellation)
            self.succeeded.emit(result)
        except AnalysisCancelled:
            self.cancelled.emit()
        except AnalysisOperationError as error:
            self.failed.emit(error)
        except Exception as error:
            self._service.abort_prepared(self._prepared)
            logging.getLogger("sikumon.workers.analysis").exception(
                "Unexpected analysis worker failure meeting_id=%s",
                self._prepared.meeting_id,
            )
            self.failed.emit(
                AnalysisOperationError(
                    "לא ניתן להשלים את ניתוח הפגישה. התמלול והניתוח הקודם נשמרו.",
                    technical_message=f"Unexpected analysis worker failure: {error}",
                )
            )
        finally:
            self.finished.emit()
