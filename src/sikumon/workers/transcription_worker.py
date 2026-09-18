"""Qt worker for local model loading and transcription."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot

from sikumon.application.transcription_service import (
    PreparedTranscription,
    TranscriptionOperationError,
    TranscriptionService,
)
from sikumon.services.transcription.faster_whisper_ivrit import (
    TranscriptionCancelled,
    TranscriptionProviderError,
)


class TranscriptionWorker(QObject):
    progress_changed = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        service: TranscriptionService,
        prepared: PreparedTranscription,
        cancellation: threading.Event,
    ) -> None:
        super().__init__()
        self._service = service
        self._prepared = prepared
        self._cancellation = cancellation

    @Slot()
    def run(self) -> None:
        try:
            result = self._service.execute(
                self._prepared,
                self._cancellation,
                self.progress_changed.emit,
            )
            self.succeeded.emit(result)
        except TranscriptionCancelled:
            self.cancelled.emit()
        except (TranscriptionProviderError, TranscriptionOperationError) as error:
            self.failed.emit(error)
        except Exception as error:
            self._service.fail_prepared(self._prepared)
            logging.getLogger("sikumon.workers.transcription").exception(
                "Unexpected transcription worker failure meeting_id=%s",
                self._prepared.meeting_id,
            )
            self.failed.emit(
                TranscriptionOperationError(
                    "לא ניתן להשלים את התמלול. תמלול קודם, אם קיים, נשמר.",
                    technical_message=f"Unexpected transcription worker failure: {error}",
                )
            )
        finally:
            self.finished.emit()
