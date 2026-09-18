"""Selected-meeting work area."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sikumon.application.analysis_controller import AnalysisController
from sikumon.application.meeting_service import MeetingService
from sikumon.application.model_management import ModelManagementController
from sikumon.application.transcript_edit_service import (
    TranscriptEditService,
    TranscriptSaveError,
)
from sikumon.application.transcript_export import (
    format_plain_transcript,
    format_srt_transcript,
    safe_export_stem,
    write_export,
)
from sikumon.application.transcription_controller import TranscriptionController
from sikumon.application.transcription_service import TranscriptionProgress
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus
from sikumon.security.credentials import CredentialStore, CredentialStoreError
from sikumon.services.transcription.model_manager import ModelAvailability
from sikumon.ui.analysis_view import DecisionsView, SummaryView, TasksView
from sikumon.ui.presentation import STATUS_LABELS, format_duration
from sikumon.ui.resources import asset_path
from sikumon.ui.transcript_view import TranscriptView


class MeetingView(QWidget):
    delete_requested = Signal(str)
    new_meeting_requested = Signal()

    def __init__(
        self,
        meeting_service: MeetingService,
        model_controller: ModelManagementController,
        transcription_controller: TranscriptionController,
        transcript_edit_service: TranscriptEditService,
        analysis_controller: AnalysisController | None = None,
        credential_store: CredentialStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._meeting_service = meeting_service
        self._model_controller = model_controller
        self._transcription_controller = transcription_controller
        self._transcript_edit_service = transcript_edit_service
        self._analysis_controller = analysis_controller
        self._credential_store = credential_store
        self._meeting_id: str | None = None
        self._base_can_transcribe = False
        self._base_can_analyze = False
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setObjectName("meetingContent")
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack)

        self.empty_state = QWidget()
        self.empty_state.setObjectName("emptyHero")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(48, 48, 48, 48)
        empty_layout.setSpacing(13)
        empty_layout.addStretch(2)
        empty_mark = QLabel()
        empty_mark.setObjectName("emptyMark")
        empty_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_mark.setPixmap(
            QPixmap(str(asset_path("brand-mark.svg"))).scaled(
                64,
                64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        empty_layout.addWidget(empty_mark, 0, Qt.AlignmentFlag.AlignHCenter)
        self.empty_title = QLabel("הפגישות שלכם, מסודרות וברורות")
        self.empty_title.setObjectName("emptyHeroTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        empty_text = QLabel("ייבאו הקלטה בעברית, קבלו תמלול מקומי ותובנות שאפשר לחזור אליהן.")
        empty_text.setObjectName("emptyHeroText")
        empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_text.setWordWrap(True)
        empty_text.setMaximumWidth(520)
        empty_text.setMinimumHeight(46)
        empty_layout.addWidget(empty_text, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_button = QPushButton("פגישה חדשה")
        empty_button.setIcon(QIcon(str(asset_path("plus.svg"))))
        empty_button.setProperty("buttonRole", "primary")
        empty_button.clicked.connect(self.new_meeting_requested)
        empty_layout.addWidget(empty_button, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch(3)
        self.stack.addWidget(self.empty_state)

        self.content = QWidget()
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(28, 24, 28, 24)
        content_layout.setSpacing(14)
        self.stack.addWidget(self.content)

        header = QFrame()
        header.setObjectName("meetingHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 18, 22, 17)
        header_layout.setSpacing(12)
        title_row = QHBoxLayout()
        self.title_label = QLabel("בחרו פגישה כדי להציג את פרטיה")
        self.title_label.setObjectName("meetingTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        title_row.addWidget(self.title_label, 1)
        self.status_label = QLabel("—")
        self.status_label.setObjectName("statusBadge")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_row.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignTop)
        header_layout.addLayout(title_row)

        metadata = QWidget()
        metadata.setObjectName("meetingMetadata")
        metadata_layout = QHBoxLayout(metadata)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(18)
        self.original_filename_label = self._technical_label()
        self.duration_label = self._technical_label()
        self.created_label = self._technical_label()
        self.audio_path_label = self._technical_label()
        self.audio_path_label.setVisible(False)
        for caption, value in (
            ("קובץ", self.original_filename_label),
            ("משך", self.duration_label),
            ("יובאה", self.created_label),
        ):
            item = QWidget()
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(2)
            caption_label = QLabel(caption)
            caption_label.setObjectName("metadataCaption")
            item_layout.addWidget(caption_label)
            item_layout.addWidget(value)
            metadata_layout.addWidget(item)
        metadata_layout.addStretch()
        header_layout.addWidget(metadata)
        content_layout.addWidget(header)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.transcribe_button = QPushButton("תמלל הקלטה")
        self.transcribe_button.setEnabled(False)
        self.transcribe_button.clicked.connect(self._start_transcription)
        self.cancel_transcription_button = QPushButton("בטל תמלול")
        self.cancel_transcription_button.setVisible(False)
        self.cancel_transcription_button.clicked.connect(
            transcription_controller.cancel_transcription
        )
        self.analyze_button = QPushButton("נתח פגישה")
        self.analyze_button.setObjectName("analyzeMeetingButton")
        self.analyze_button.setProperty("buttonRole", "primary")
        self.analyze_button.setEnabled(False)
        self.analyze_button.clicked.connect(self._start_analysis)
        self.delete_button = QPushButton("מחיקת הפגישה")
        self.delete_button.setIcon(QIcon(str(asset_path("delete.svg"))))
        self.delete_button.setProperty("buttonRole", "danger")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._request_delete)
        actions.addWidget(self.transcribe_button)
        actions.addWidget(self.cancel_transcription_button)
        actions.addWidget(self.analyze_button)
        actions.addStretch()
        actions.addWidget(self.delete_button)
        content_layout.addLayout(actions)

        self.transcription_progress = QProgressBar()
        self.transcription_progress.setVisible(False)
        self.transcription_progress.setRange(0, 0)
        content_layout.addWidget(self.transcription_progress)
        self.transcription_message = QLabel()
        self.transcription_message.setWordWrap(True)
        self.transcription_message.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.transcription_message.setVisible(False)
        content_layout.addWidget(self.transcription_message)

        self.analysis_progress = QProgressBar()
        self.analysis_progress.setObjectName("analysisProgress")
        self.analysis_progress.setRange(0, 0)
        self.analysis_progress.setFormat("מנתח את הפגישה…")
        self.analysis_progress.setVisible(False)
        content_layout.addWidget(self.analysis_progress)
        self.analysis_message = QLabel()
        self.analysis_message.setObjectName("analysisMessage")
        self.analysis_message.setWordWrap(True)
        self.analysis_message.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.analysis_message.setVisible(False)
        content_layout.addWidget(self.analysis_message)

        self.outdated_banner = QWidget()
        self.outdated_banner.setObjectName("outdatedAnalysisBanner")
        outdated_layout = QHBoxLayout(self.outdated_banner)
        outdated_layout.setContentsMargins(14, 10, 14, 10)
        self.outdated_label = QLabel(
            "התמלול השתנה מאז יצירת הניתוח. יש לנתח מחדש כדי לעדכן את התוצאות."
        )
        self.outdated_label.setWordWrap(True)
        self.outdated_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.reanalyze_button = QPushButton("נתח מחדש")
        self.reanalyze_button.setObjectName("reanalyzeMeetingButton")
        self.reanalyze_button.clicked.connect(self._start_analysis)
        outdated_layout.addWidget(self.outdated_label, 1)
        outdated_layout.addWidget(self.reanalyze_button)
        self.outdated_banner.setVisible(False)
        content_layout.addWidget(self.outdated_banner)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.transcript_view = TranscriptView()
        self.transcript_view.save_requested.connect(self.save_transcript)
        self.transcript_view.copy_requested.connect(self._copy_transcript)
        self.transcript_view.export_requested.connect(self._export_transcript)
        self.transcript_view.dirty_changed.connect(self._dirty_state_changed)
        self.tabs.addTab(
            self.transcript_view, QIcon(str(asset_path("transcript.svg"))), "תמלול"
        )
        self.summary_view = SummaryView()
        self.decisions_view = DecisionsView()
        self.tasks_view = TasksView()
        self.decisions_view.evidence_selected.connect(self._navigate_to_evidence)
        self.tasks_view.evidence_selected.connect(self._navigate_to_evidence)
        self.tabs.addTab(self.summary_view, QIcon(str(asset_path("summary.svg"))), "סיכום")
        self.tabs.addTab(
            self.decisions_view, QIcon(str(asset_path("decisions.svg"))), "החלטות"
        )
        self.tabs.addTab(self.tasks_view, QIcon(str(asset_path("tasks.svg"))), "משימות")
        content_layout.addWidget(self.tabs, 1)
        self.stack.setCurrentWidget(self.empty_state)

        model_controller.state_changed.connect(self._model_state_changed)
        transcription_controller.state_changed.connect(self._transcription_state_changed)
        transcription_controller.progress_changed.connect(self._transcription_progress_changed)
        transcription_controller.failed.connect(self._transcription_failed)
        transcription_controller.cancelled.connect(self._transcription_cancelled)
        transcription_controller.operation_finished.connect(self._transcription_finished)
        if analysis_controller is not None:
            analysis_controller.state_changed.connect(self._analysis_state_changed)
            analysis_controller.succeeded.connect(self._analysis_succeeded)
            analysis_controller.failed.connect(self._analysis_failed)
            analysis_controller.cancelled.connect(self._analysis_cancelled)
            analysis_controller.operation_finished.connect(self._analysis_finished)

    @property
    def current_meeting_id(self) -> str | None:
        return self._meeting_id

    @property
    def has_unsaved_transcript(self) -> bool:
        return self.transcript_view.is_dirty

    def show_meeting(self, meeting_id: str, *, preserve_unsaved: bool = False) -> None:
        meeting = self._meeting_service.get_meeting(meeting_id)
        if meeting is None:
            self.clear()
            self.empty_title.setText("הפגישה לא נמצאה")
            return
        self.empty_title.setText("הפגישות שלכם, מסודרות וברורות")
        self.stack.setCurrentWidget(self.content)
        self._meeting_id = meeting.id
        self.title_label.setText(meeting.title)
        self.original_filename_label.setText(meeting.original_filename)
        self.duration_label.setText(format_duration(meeting.audio_duration_seconds))
        self.created_label.setText(meeting.created_at.astimezone().strftime("%d.%m.%Y  %H:%M"))
        self.status_label.setText(STATUS_LABELS[meeting.display_state])
        state_name = meeting.display_state.name
        badge_state = (
            "error"
            if state_name in {"ACTION_REQUIRED", "AUDIO_MISSING"}
            else "warning"
            if state_name in {"TRANSCRIBING", "ANALYZING", "ANALYSIS_OUTDATED"}
            else "success"
        )
        self.status_label.setProperty("state", badge_state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.audio_path_label.setText(meeting.audio_path)
        self.delete_button.setEnabled(meeting.can_delete)
        running = meeting.transcription_status == TranscriptionStatus.RUNNING
        analysis_running = (
            meeting.analysis_operation_status == AnalysisOperationStatus.RUNNING
        )
        keep_local_edits = (
            preserve_unsaved
            and self._meeting_id == meeting.id
            and self.transcript_view.is_dirty
        )
        if keep_local_edits:
            self.transcript_view.set_editing_blocked(running)
            self.transcript_view.set_save_blocked(analysis_running)
        else:
            self.transcript_view.set_segments(
                meeting.transcript_segments,
                meeting.transcript_revision,
                editing_blocked=running,
                save_blocked=analysis_running,
            )
        self._show_running(running)
        self._base_can_transcribe = (
            meeting.audio_exists
            and self._model_controller.availability == ModelAvailability.AVAILABLE
            and not running
            and self._transcription_controller.active_meeting_id is None
        )
        self.transcribe_button.setEnabled(self._base_can_transcribe)
        has_content = any(segment.text.strip() for segment in meeting.transcript_segments)
        self._base_can_analyze = (
            has_content
            and not running
            and not analysis_running
            and self._analysis_controller is not None
            and self._analysis_controller.active_meeting_id is None
            and self._credentials_available()
        )
        self.analyze_button.setEnabled(
            self._base_can_analyze and not self.transcript_view.is_dirty
        )
        self.analyze_button.setText("נתח מחדש" if meeting.analysis is not None else "נתח פגישה")
        self.summary_view.set_analysis(meeting.analysis, has_transcript=has_content)
        self.decisions_view.set_analysis(meeting.analysis, has_transcript=has_content)
        self.tasks_view.set_analysis(meeting.analysis, has_transcript=has_content)
        outdated = meeting.analysis is not None and meeting.analysis.is_outdated
        self.outdated_banner.setVisible(outdated)
        self.reanalyze_button.setEnabled(
            outdated and self._base_can_analyze and not self.transcript_view.is_dirty
        )
        self.analysis_progress.setVisible(analysis_running)
        if not self._credentials_available() and has_content and not analysis_running:
            self._present_message(
                self.analysis_message,
                "נדרש מפתח OpenAI. אפשר להגדיר אותו במסך ההגדרות.",
                "neutral",
            )
        elif not analysis_running:
            self.analysis_message.setVisible(False)

    def clear(self) -> None:
        self._meeting_id = None
        self.stack.setCurrentWidget(self.empty_state)
        self.title_label.setText("בחרו פגישה כדי להציג את פרטיה")
        for label in (
            self.original_filename_label,
            self.duration_label,
            self.created_label,
            self.status_label,
            self.audio_path_label,
        ):
            label.setText("—")
        self.delete_button.setEnabled(False)
        self.transcribe_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self._show_running(False)
        self.transcript_view.set_segments(())
        self._base_can_transcribe = False
        self._base_can_analyze = False
        self.analysis_progress.setVisible(False)
        self.analysis_message.setVisible(False)
        self.outdated_banner.setVisible(False)
        self.summary_view.set_analysis(None, has_transcript=False)
        self.decisions_view.set_analysis(None, has_transcript=False)
        self.tasks_view.set_analysis(None, has_transcript=False)

    def _start_transcription(self) -> None:
        if self._meeting_id is not None and self.resolve_unsaved_changes():
            self.transcription_message.setVisible(False)
            self._transcription_controller.start_transcription(self._meeting_id)

    def save_transcript(self) -> bool:
        if self._meeting_id is None or not self.transcript_view.is_dirty:
            return True
        self.transcript_view.set_save_in_progress(True)
        try:
            self._transcript_edit_service.save(
                self._meeting_id,
                self.transcript_view.source_revision,
                self.transcript_view.current_texts(),
            )
        except TranscriptSaveError as error:
            self._present_message(self.transcription_message, error.user_message, "error")
            return False
        finally:
            self.transcript_view.set_save_in_progress(False)
        self.transcription_message.setVisible(False)
        self.show_meeting(self._meeting_id)
        return True

    def refresh_credentials(self) -> None:
        if self._meeting_id is not None and not self.transcript_view.is_dirty:
            self.show_meeting(self._meeting_id)

    def _copy_transcript(self) -> None:
        content = format_plain_transcript(self.transcript_view.export_segments())
        if not content:
            return
        QApplication.clipboard().setText(content)
        self._present_message(
            self.transcription_message, "התמלול הועתק ללוח.", "success"
        )

    def _export_transcript(self) -> None:
        segments = self.transcript_view.export_segments()
        if not segments:
            return
        suggested = f"{safe_export_stem(self.title_label.text())}.txt"
        selected, selected_filter = QFileDialog.getSaveFileName(
            self,
            "ייצוא תמלול",
            suggested,
            "קובץ טקסט (*.txt);;כתוביות SubRip (*.srt)",
        )
        if not selected:
            return
        destination = Path(selected)
        wants_srt = destination.suffix.lower() == ".srt" or "SubRip" in selected_filter
        if destination.suffix.lower() not in {".txt", ".srt"}:
            destination = destination.with_suffix(".srt" if wants_srt else ".txt")
        content = (
            format_srt_transcript(segments)
            if destination.suffix.lower() == ".srt"
            else format_plain_transcript(segments)
        )
        try:
            write_export(destination, content)
        except OSError:
            self._present_message(
                self.transcription_message,
                "לא ניתן לשמור את קובץ התמלול. בחרו מיקום אחר ונסו שוב.",
                "error",
            )
            return
        self._present_message(
            self.transcription_message,
            f"התמלול נשמר: {destination.name}",
            "success",
        )

    def _start_analysis(self) -> None:
        if self._meeting_id is None or self._analysis_controller is None:
            return
        if self.transcript_view.is_dirty:
            self._present_message(
                self.analysis_message, "יש לשמור את שינויי התמלול לפני הניתוח.", "error"
            )
            return
        self.analysis_message.setVisible(False)
        self._analysis_controller.start_analysis(self._meeting_id)

    def resolve_unsaved_changes(self) -> bool:
        if not self.transcript_view.is_dirty:
            return True
        decision = self._ask_unsaved_changes()
        if decision == UnsavedTranscriptDecision.SAVE:
            return self.save_transcript()
        if decision == UnsavedTranscriptDecision.DISCARD:
            self.transcript_view.discard_changes()
            return True
        return False

    def _ask_unsaved_changes(self) -> UnsavedTranscriptDecision:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("שינויים שלא נשמרו")
        dialog.setText("יש שינויים בתמלול שעדיין לא נשמרו.")
        dialog.setInformativeText("לשמור את השינויים לפני שממשיכים?")
        save_button = dialog.addButton("שמור", QMessageBox.ButtonRole.AcceptRole)
        save_button.setProperty("buttonRole", "primary")
        discard_button = dialog.addButton(
            "אל תשמור", QMessageBox.ButtonRole.DestructiveRole
        )
        discard_button.setProperty("buttonRole", "danger")
        dialog.addButton("ביטול", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() is save_button:
            return UnsavedTranscriptDecision.SAVE
        if dialog.clickedButton() is discard_button:
            return UnsavedTranscriptDecision.DISCARD
        return UnsavedTranscriptDecision.CANCEL

    def _model_state_changed(self, state: ModelAvailability) -> None:
        if self._meeting_id is not None and not self.transcript_view.is_dirty:
            self.show_meeting(self._meeting_id)

    def _transcription_state_changed(
        self, meeting_id: str, status: TranscriptionStatus
    ) -> None:
        if meeting_id != self._meeting_id:
            return
        if status == TranscriptionStatus.RUNNING:
            self.status_label.setText("בתהליך תמלול")
            self.delete_button.setEnabled(False)
            self.transcribe_button.setEnabled(False)
            self.transcript_view.set_editing_blocked(True)
            self._show_running(True)
            self._present_message(
                self.transcription_message, "מתמלל את ההקלטה…", "neutral"
            )

    def _transcription_progress_changed(
        self, meeting_id: str, progress: TranscriptionProgress
    ) -> None:
        if meeting_id != self._meeting_id:
            return
        if progress.estimated_percent is None:
            self.transcription_progress.setRange(0, 0)
            self._present_message(
                self.transcription_message, "מתמלל את ההקלטה…", "neutral"
            )
        else:
            self.transcription_progress.setRange(0, 100)
            self.transcription_progress.setValue(progress.estimated_percent)
            self._present_message(
                self.transcription_message,
                f"מתמלל את ההקלטה… {progress.estimated_percent}%",
                "neutral",
            )

    def _transcription_failed(self, meeting_id: str, message: str) -> None:
        if meeting_id == self._meeting_id:
            self._present_message(self.transcription_message, message, "error")

    def _transcription_cancelled(self, meeting_id: str) -> None:
        if meeting_id == self._meeting_id:
            self._present_message(
                self.transcription_message, "התמלול בוטל. לא נשמר תמלול חלקי.", "neutral"
            )

    def _transcription_finished(self, meeting_id: str) -> None:
        if meeting_id == self._meeting_id:
            self.show_meeting(meeting_id, preserve_unsaved=True)

    def _analysis_state_changed(
        self, meeting_id: str, status: AnalysisOperationStatus
    ) -> None:
        if meeting_id != self._meeting_id:
            return
        if status == AnalysisOperationStatus.RUNNING:
            self.status_label.setText("בתהליך ניתוח")
            self.delete_button.setEnabled(False)
            self.analyze_button.setEnabled(False)
            self.reanalyze_button.setEnabled(False)
            self.transcript_view.set_save_blocked(True)
            self.analysis_progress.setVisible(True)
            self._present_message(
                self.analysis_message, "מנתח את הפגישה…", "neutral"
            )

    def _analysis_failed(self, meeting_id: str, message: str) -> None:
        if meeting_id == self._meeting_id:
            self._present_message(self.analysis_message, message, "error")

    def _analysis_succeeded(self, meeting_id: str) -> None:
        if meeting_id == self._meeting_id:
            self._present_message(
                self.analysis_message, "ניתוח הפגישה הושלם ונשמר.", "success"
            )

    def _analysis_cancelled(self, meeting_id: str) -> None:
        if meeting_id == self._meeting_id:
            self._present_message(
                self.analysis_message,
                "ניתוח הפגישה הופסק. הניתוח הקודם נשמר.",
                "neutral",
            )

    def _analysis_finished(self, meeting_id: str) -> None:
        if meeting_id == self._meeting_id:
            message = self.analysis_message.text()
            message_type = str(self.analysis_message.property("messageType") or "neutral")
            visible = self.analysis_message.isVisibleTo(self)
            self.show_meeting(meeting_id, preserve_unsaved=True)
            if visible:
                self._present_message(self.analysis_message, message, message_type)

    def _show_running(self, running: bool) -> None:
        self.cancel_transcription_button.setVisible(running)
        self.transcription_progress.setVisible(running)
        if running:
            self.transcription_progress.setRange(0, 0)

    def _dirty_state_changed(self, dirty: bool) -> None:
        self.transcribe_button.setEnabled(self._base_can_transcribe and not dirty)
        self.analyze_button.setEnabled(self._base_can_analyze and not dirty)
        self.reanalyze_button.setEnabled(
            self.outdated_banner.isVisible() and self._base_can_analyze and not dirty
        )

    def _navigate_to_evidence(self, segment_id: str) -> None:
        self.tabs.setCurrentWidget(self.transcript_view)
        if not self.transcript_view.focus_segment(segment_id):
            self._present_message(
                self.analysis_message, "לא ניתן למצוא את מקטע המקור בתמלול.", "error"
            )

    def _request_delete(self) -> None:
        if self._meeting_id is not None and self.resolve_unsaved_changes():
            self.delete_requested.emit(self._meeting_id)

    def _credentials_available(self) -> bool:
        if self._credential_store is None:
            return False
        try:
            return self._credential_store.get_api_key() is not None
        except CredentialStoreError:
            return False

    @staticmethod
    def _technical_label() -> QLabel:
        label = QLabel("—")
        label.setObjectName("technicalValue")
        label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def _present_message(label: QLabel, text: str, message_type: str) -> None:
        label.setText(text)
        label.setProperty("messageType", message_type)
        label.style().unpolish(label)
        label.style().polish(label)
        label.setVisible(True)


class UnsavedTranscriptDecision(StrEnum):
    SAVE = "SAVE"
    DISCARD = "DISCARD"
    CANCEL = "CANCEL"
