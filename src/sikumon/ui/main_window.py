"""Main native desktop application window."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from sikumon.application.analysis_controller import AnalysisController
from sikumon.application.meeting_service import (
    MeetingDeletionBlockedError,
    MeetingDeletionError,
    MeetingNotFoundError,
    MeetingService,
)
from sikumon.application.model_management import ModelManagementController
from sikumon.application.transcript_edit_service import TranscriptEditService
from sikumon.application.transcription_controller import TranscriptionController
from sikumon.config.constants import APP_NAME
from sikumon.security.credentials import CredentialStore
from sikumon.storage.paths import ApplicationPaths
from sikumon.ui.meeting_list import MeetingListWidget
from sikumon.ui.meeting_view import MeetingView
from sikumon.ui.new_meeting_dialog import NewMeetingDialog
from sikumon.ui.settings_dialog import SettingsDialog
from sikumon.ui.theme import APP_STYLESHEET


class MainWindow(QMainWindow):
    def __init__(
        self,
        meeting_service: MeetingService,
        paths: ApplicationPaths,
        model_controller: ModelManagementController,
        transcription_controller: TranscriptionController,
        transcript_edit_service: TranscriptEditService,
        analysis_controller: AnalysisController | None = None,
        credential_store: CredentialStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths = paths
        self._meeting_service = meeting_service
        self._model_controller = model_controller
        self._transcription_controller = transcription_controller
        self._transcript_edit_service = transcript_edit_service
        self._analysis_controller = analysis_controller
        self._credential_store = credential_store
        self._shutdown_requested = False
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setMinimumSize(980, 640)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        self.meeting_list = MeetingListWidget(meeting_service)
        self.meeting_view = MeetingView(
            meeting_service,
            model_controller,
            transcription_controller,
            transcript_edit_service,
            analysis_controller,
            credential_store,
        )
        splitter.addWidget(self.meeting_list)
        splitter.addWidget(self.meeting_view)
        self.meeting_list.setMinimumWidth(250)
        self.meeting_list.setMaximumWidth(290)
        splitter.setSizes([272, 1008])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        outer.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self.meeting_list.meeting_selected.connect(self._select_meeting)
        self.meeting_list.new_meeting_requested.connect(self._open_new_meeting)
        self.meeting_list.settings_requested.connect(self._open_settings)
        self.meeting_view.new_meeting_requested.connect(self._open_new_meeting)
        self.meeting_view.delete_requested.connect(self._delete_meeting)
        transcription_controller.operation_finished.connect(self._transcription_finished)
        model_controller.operation_finished.connect(self._background_operation_finished)
        if analysis_controller is not None:
            analysis_controller.operation_finished.connect(self._analysis_finished)
        self._apply_style()

    def load_meetings(self) -> None:
        self.meeting_list.reload()

    def _open_settings(self) -> None:
        SettingsDialog(
            self._paths,
            self._model_controller,
            self._credential_store,
            self,
        ).exec()
        self.meeting_view.refresh_credentials()

    def _open_new_meeting(self) -> None:
        dialog = NewMeetingDialog(self._meeting_service, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.imported_meeting_id:
            self.meeting_list.reload(dialog.imported_meeting_id)

    def _select_meeting(self, meeting_id: str) -> None:
        previous_id = self.meeting_view.current_meeting_id
        if meeting_id == previous_id:
            return
        if self.meeting_view.resolve_unsaved_changes():
            self.meeting_view.show_meeting(meeting_id)
        else:
            self.meeting_list.select_meeting(previous_id)

    def _transcription_finished(self, meeting_id: str) -> None:
        self.meeting_list.reload(meeting_id)
        self._background_operation_finished()

    def _analysis_finished(self, meeting_id: str) -> None:
        self.meeting_list.reload(meeting_id)
        self._background_operation_finished()

    def closeEvent(self, event: QCloseEvent) -> None:
        active = self._active_operations()
        if active:
            if not self._shutdown_requested:
                if not self._confirm_active_shutdown(active):
                    event.ignore()
                    return
                self._shutdown_requested = True
                if self._model_controller.is_active:
                    self._model_controller.cancel_download()
                if self._transcription_controller.active_meeting_id is not None:
                    self._transcription_controller.cancel_transcription()
                if (
                    self._analysis_controller is not None
                    and self._analysis_controller.active_meeting_id is not None
                ):
                    self._analysis_controller.cancel_analysis()
            event.ignore()
            return
        if not self.meeting_view.resolve_unsaved_changes():
            event.ignore()
            return
        event.accept()

    def _active_operations(self) -> tuple[str, ...]:
        active: list[str] = []
        if self._model_controller.is_active:
            active.append("הורדת מודל")
        if self._transcription_controller.active_meeting_id is not None:
            active.append("תמלול")
        if (
            self._analysis_controller is not None
            and self._analysis_controller.active_meeting_id is not None
        ):
            active.append("ניתוח")
        return tuple(active)

    def _confirm_active_shutdown(self, active: tuple[str, ...]) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("סגירת Sikumon")
        dialog.setText("פעולה עדיין מתבצעת: " + ", ".join(active))
        dialog.setInformativeText(
            "הסגירה תבקש לעצור את הפעולה בבטחה ותושלם לאחר שהעובד יסיים. "
            "הנתונים שכבר נשמרו לא יימחקו."
        )
        close_button = dialog.addButton("עצור וסגור", QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton("ביטול", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        return dialog.clickedButton() is close_button

    def _background_operation_finished(self) -> None:
        if self._shutdown_requested and not self._active_operations():
            self.close()

    def _delete_meeting(self, meeting_id: str) -> None:
        if not self._confirm_deletion():
            return
        try:
            result = self._meeting_service.delete_meeting(meeting_id)
        except (
            MeetingDeletionBlockedError,
            MeetingDeletionError,
            MeetingNotFoundError,
        ) as error:
            QMessageBox.warning(self, "מחיקת פגישה", error.user_message)
            return
        self.meeting_view.clear()
        self.meeting_list.reload()
        if result.undeleted_paths:
            QMessageBox.warning(
                self,
                "הפגישה נמחקה",
                "נתוני הפגישה נמחקו, אך לא ניתן להסיר חלק מהקבצים המקומיים. "
                "פרטים נוספים נשמרו ביומן היישום.",
            )

    def _confirm_deletion(self) -> bool:
        meeting = (
            self._meeting_service.get_meeting(self.meeting_view.current_meeting_id)
            if self.meeting_view.current_meeting_id is not None
            else None
        )
        meeting_title = meeting.title if meeting is not None else "הפגישה שנבחרה"
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("מחיקת פגישה")
        dialog.setText(f"למחוק את „{meeting_title}“?")
        dialog.setInformativeText(
            "ההקלטה, התמלול והניתוח השמורים ב-Sikumon יימחקו לצמיתות."
        )
        delete_button = dialog.addButton("מחק", QMessageBox.ButtonRole.DestructiveRole)
        delete_button.setProperty("buttonRole", "danger")
        dialog.addButton("ביטול", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        return dialog.clickedButton() is delete_button

    def _apply_style(self) -> None:
        self.setStyleSheet(APP_STYLESHEET)
