"""Qt worker dedicated to potentially slow Phase 2 meeting imports."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from sikumon.application.meeting_service import (
    MeetingDetails,
    MeetingImportError,
    MeetingService,
)
from sikumon.services.audio.metadata import MediaValidationError


class MeetingImportWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(self, service: MeetingService, source: Path, title: str) -> None:
        super().__init__()
        self._service = service
        self._source = source
        self._title = title

    @Slot()
    def run(self) -> None:
        try:
            result: MeetingDetails = self._service.import_meeting(self._source, self._title)
            self.succeeded.emit(result)
        except (MediaValidationError, MeetingImportError, ValueError) as error:
            self.failed.emit(error)
        except Exception:
            logging.getLogger("sikumon.workers.meeting_import").exception(
                "Unexpected meeting import worker failure"
            )
            self.failed.emit(MeetingImportError())
        finally:
            self.finished.emit()
