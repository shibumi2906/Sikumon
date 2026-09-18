"""Hebrew-first native meeting import dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sikumon.application.meeting_service import (
    MeetingDetails,
    MeetingImportError,
    MeetingService,
    default_meeting_title,
)
from sikumon.services.audio.metadata import MediaValidationError
from sikumon.workers.meeting_import_worker import MeetingImportWorker


class NewMeetingDialog(QDialog):
    def __init__(self, meeting_service: MeetingService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._meeting_service = meeting_service
        self._source_path: Path | None = None
        self._thread: QThread | None = None
        self._worker: MeetingImportWorker | None = None
        self._pending_result: MeetingDetails | None = None
        self._pending_error: Exception | None = None
        self.imported_meeting_id: str | None = None

        self.setWindowTitle("פגישה חדשה")
        self.setMinimumWidth(640)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(14)

        heading = QLabel("ייבוא הקלטת פגישה")
        heading.setObjectName("dialogHeading")
        heading.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(heading)

        description = QLabel(
            "בחרו הקלטה בעברית. Sikumon ישמור עותק מקומי ויכין אותה לתמלול."
        )
        description.setObjectName("dialogDescription")
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(description)

        file_surface = QFrame()
        file_surface.setObjectName("filePickerSurface")
        file_layout = QVBoxLayout(file_surface)
        file_layout.setContentsMargins(16, 14, 16, 14)
        file_layout.setSpacing(8)
        self.choose_button = QPushButton("בחרו הקלטה")
        self.choose_button.clicked.connect(self._choose_recording)
        file_layout.addWidget(self.choose_button)

        self.path_label = QLabel("לא נבחר קובץ")
        self.path_label.setObjectName("technicalValue")
        self.path_label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.path_label.setWordWrap(True)
        file_layout.addWidget(self.path_label)
        layout.addWidget(file_surface)

        title_label = QLabel("שם הפגישה")
        title_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(title_label)
        self.title_edit = QLineEdit()
        self.title_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.title_edit.setMaxLength(500)
        self.title_edit.setPlaceholderText("הקלידו שם לפגישה")
        layout.addWidget(self.title_edit)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.state_label = QLabel("")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.state_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton("ביטול")
        self.cancel_button.setProperty("buttonRole", "ghost")
        self.cancel_button.clicked.connect(self.reject)
        self.import_button = QPushButton("ייבוא")
        self.import_button.setProperty("buttonRole", "primary")
        self.import_button.setDefault(True)
        self.import_button.clicked.connect(self._start_import)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.import_button)
        layout.addLayout(buttons)

    def set_source_path(self, source: Path) -> None:
        """Set a chosen file; also serves as a deterministic UI test hook."""

        self._source_path = Path(source)
        self.path_label.setText(str(self._source_path))
        self.path_label.setToolTip(str(self._source_path))
        if not self.title_edit.text().strip():
            self.title_edit.setText(default_meeting_title(self._source_path))

    def _choose_recording(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "בחרו הקלטה",
            "",
            "קובצי שמע (*.wav *.mp3 *.m4a *.flac *.aac *.mp4)",
        )
        if selected:
            self.set_source_path(Path(selected))

    def _start_import(self) -> None:
        if self._thread is not None:
            return
        if self._source_path is None:
            QMessageBox.warning(self, "פגישה חדשה", "יש לבחור קובץ הקלטה.")
            return
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "פגישה חדשה", "יש להזין שם לפגישה.")
            self.title_edit.setFocus()
            return

        self._set_busy(True)
        self._pending_result = None
        self._pending_error = None
        thread = QThread(self)
        worker = MeetingImportWorker(self._meeting_service, self._source_path, title)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._store_success)
        worker.failed.connect(self._store_failure)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finish_import)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        try:
            thread.start()
        except RuntimeError:
            self._thread = None
            self._worker = None
            self._pending_error = MeetingImportError()
            self._finish_import()

    def _store_success(self, result: object) -> None:
        if isinstance(result, MeetingDetails):
            self._pending_result = result

    def _store_failure(self, error: object) -> None:
        self._pending_error = error if isinstance(error, Exception) else MeetingImportError()

    def _finish_import(self) -> None:
        self._thread = None
        self._worker = None
        self._set_busy(False)
        if self._pending_result is not None:
            self.imported_meeting_id = self._pending_result.id
            self.accept()
            return
        error = self._pending_error
        if isinstance(error, (MediaValidationError, MeetingImportError)):
            message = error.user_message
        elif isinstance(error, ValueError):
            message = "יש להזין שם תקין לפגישה."
        else:
            message = MeetingImportError.user_message
        QMessageBox.warning(self, "ייבוא ההקלטה נכשל", message)

    def _set_busy(self, busy: bool) -> None:
        self.choose_button.setEnabled(not busy)
        self.title_edit.setEnabled(not busy)
        self.import_button.setEnabled(not busy)
        self.cancel_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.state_label.setText("מייבא את ההקלטה…" if busy else "")

    def reject(self) -> None:
        if self._thread is None:
            super().reject()
