"""Hebrew-first settings and local transcription model controls."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sikumon.application.model_management import ModelManagementController
from sikumon.config.constants import (
    APP_VERSION,
    DEFAULT_ANALYSIS_MODEL,
    IVRIT_MODEL_ID,
    IVRIT_MODEL_REVISION,
    TRANSCRIPTION_COMPUTE_TYPE,
)
from sikumon.security.credentials import CredentialStore, CredentialStoreError
from sikumon.services.transcription.model_manager import DownloadProgress, ModelAvailability
from sikumon.storage.paths import ApplicationPaths


class SettingsDialog(QDialog):
    def __init__(
        self,
        paths: ApplicationPaths,
        model_controller: ModelManagementController,
        credential_store: CredentialStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model_controller = model_controller
        self._credential_store = credential_store
        self.setWindowTitle("הגדרות")
        self.resize(700, 720)
        self.setMinimumSize(620, 580)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        heading = QLabel("הגדרות")
        heading.setObjectName("dialogHeading")
        heading.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(2, 2, 8, 2)
        body_layout.setSpacing(12)

        def section(title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
            frame = QFrame()
            frame.setObjectName("settingsSection")
            section_layout = QVBoxLayout(frame)
            section_layout.setContentsMargins(18, 16, 18, 17)
            section_layout.setSpacing(10)
            title_label = QLabel(title)
            title_label.setObjectName("settingsSectionTitle")
            title_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            section_layout.addWidget(title_label)
            description_label = QLabel(description)
            description_label.setObjectName("sectionDescription")
            description_label.setWordWrap(True)
            description_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            section_layout.addWidget(description_label)
            return frame, section_layout

        general_group, general_layout = section(
            "כללי", "פרטי היישום והמיקום המקומי שבו נשמרים הנתונים."
        )
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("גרסת היישום", self._ltr_label(APP_VERSION))
        form.addRow("תיקיית נתונים", self._ltr_label(str(paths.root)))
        form.addRow("תיקיית יומנים", self._ltr_label(str(paths.logs)))
        general_layout.addLayout(form)
        body_layout.addWidget(general_group)

        model_group, model_layout = section(
            "תמלול מקומי בעברית",
            "ההקלטה נשארת במחשב ומעובדת מקומית באמצעות מודל התמלול המותקן.",
        )
        model_form = QFormLayout()
        model_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        model_form.addRow("מאגר", self._ltr_label(IVRIT_MODEL_ID))
        revision_text = IVRIT_MODEL_REVISION or "לא נעולה — נדרשת נעילה לפני הפצה"
        revision_label = self._ltr_label(revision_text) if IVRIT_MODEL_REVISION else QLabel(revision_text)
        model_form.addRow("גרסה", revision_label)
        model_form.addRow("מיקום", self._ltr_label(model_controller.model_directory))
        model_form.addRow("סוג חישוב", self._ltr_label(TRANSCRIPTION_COMPUTE_TYPE))
        model_layout.addLayout(model_form)

        self.model_status_label = QLabel()
        self.model_status_label.setObjectName("modelStatusLabel")
        self.model_status_label.setWordWrap(True)
        self.model_status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        model_layout.addWidget(self.model_status_label)

        self.model_error_label = QLabel()
        self.model_error_label.setObjectName("modelErrorLabel")
        self.model_error_label.setProperty("messageType", "error")
        self.model_error_label.setWordWrap(True)
        self.model_error_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        model_layout.addWidget(self.model_error_label)

        self.model_progress = QProgressBar()
        self.model_progress.setTextVisible(True)
        self.model_progress.setRange(0, 0)
        model_layout.addWidget(self.model_progress)

        actions = QHBoxLayout()
        self.model_action_button = QPushButton()
        self.model_action_button.setObjectName("modelActionButton")
        self.model_action_button.setProperty("buttonRole", "primary")
        self.model_action_button.clicked.connect(model_controller.start_download)
        self.model_cancel_button = QPushButton("בטל הורדה")
        self.model_cancel_button.setObjectName("modelCancelButton")
        self.model_cancel_button.setProperty("buttonRole", "ghost")
        self.model_cancel_button.clicked.connect(model_controller.cancel_download)
        actions.addWidget(self.model_action_button)
        actions.addWidget(self.model_cancel_button)
        actions.addStretch()
        model_layout.addLayout(actions)
        body_layout.addWidget(model_group)

        analysis_group, analysis_layout = section(
            "ניתוח AI",
            "רק טקסט התמלול נשלח ל-OpenAI. מפתח הגישה נשמר במנהל האישורים של Windows.",
        )
        analysis_form = QFormLayout()
        analysis_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        analysis_form.addRow("מודל", self._ltr_label(DEFAULT_ANALYSIS_MODEL))
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setObjectName("openaiApiKeyEdit")
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("הזינו מפתח חדש כדי לשמור או להחליף")
        self.api_key_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        analysis_form.addRow("מפתח API", self.api_key_edit)
        analysis_layout.addLayout(analysis_form)
        self.credential_status_label = QLabel()
        self.credential_status_label.setObjectName("credentialStatusLabel")
        self.credential_status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.credential_status_label.setWordWrap(True)
        analysis_layout.addWidget(self.credential_status_label)
        credential_actions = QHBoxLayout()
        self.save_api_key_button = QPushButton("שמור מפתח")
        self.save_api_key_button.setObjectName("saveOpenaiApiKeyButton")
        self.save_api_key_button.setProperty("buttonRole", "primary")
        self.save_api_key_button.clicked.connect(self._save_api_key)
        self.clear_api_key_button = QPushButton("הסר מפתח שמור")
        self.clear_api_key_button.setObjectName("clearOpenaiApiKeyButton")
        self.clear_api_key_button.setProperty("buttonRole", "danger")
        self.clear_api_key_button.clicked.connect(self._clear_api_key)
        credential_actions.addWidget(self.save_api_key_button)
        credential_actions.addWidget(self.clear_api_key_button)
        credential_actions.addStretch()
        analysis_layout.addLayout(credential_actions)
        body_layout.addWidget(analysis_group)
        body_layout.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        close_button.setText("סגירה")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        model_controller.state_changed.connect(self._show_model_state)
        model_controller.progress_changed.connect(self._show_progress)
        model_controller.error_changed.connect(self._show_error)
        self._show_model_state(model_controller.availability)
        self._show_error(model_controller.error_message or "")
        self._refresh_credentials()

    def _save_api_key(self) -> None:
        if self._credential_store is None:
            return
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            self._show_credential_message("יש להזין מפתח API לפני השמירה.", "error")
            return
        try:
            self._credential_store.set_api_key(api_key)
        except (CredentialStoreError, ValueError):
            self._show_credential_message(
                "לא ניתן לשמור את המפתח במנהל האישורים של Windows.", "error"
            )
            return
        self.api_key_edit.clear()
        self._refresh_credentials()

    def _clear_api_key(self) -> None:
        if self._credential_store is None:
            return
        try:
            self._credential_store.delete_api_key()
        except CredentialStoreError:
            self._show_credential_message(
                "לא ניתן להסיר את המפתח ממנהל האישורים של Windows.", "error"
            )
            return
        self.api_key_edit.clear()
        self._refresh_credentials()

    def _refresh_credentials(self) -> None:
        configured = False
        if self._credential_store is not None:
            try:
                configured = self._credential_store.get_api_key() is not None
            except CredentialStoreError:
                self._show_credential_message(
                    "לא ניתן לבדוק את מנהל האישורים של Windows.", "error"
                )
                self.save_api_key_button.setEnabled(False)
                self.clear_api_key_button.setEnabled(False)
                return
        self.save_api_key_button.setEnabled(self._credential_store is not None)
        self.clear_api_key_button.setEnabled(configured)
        if configured:
            self._show_credential_message(
                "מפתח OpenAI מוגדר ומאוחסן באופן מאובטח. המפתח המלא אינו מוצג.",
                "success",
            )
        else:
            self._show_credential_message("לא מוגדר מפתח OpenAI.", "neutral")

    def _show_model_state(self, state: ModelAvailability) -> None:
        self.model_progress.setVisible(
            state in (ModelAvailability.DOWNLOADING, ModelAvailability.VERIFYING)
        )
        self.model_cancel_button.setVisible(state == ModelAvailability.DOWNLOADING)
        self.model_action_button.setVisible(
            state in (ModelAvailability.MISSING, ModelAvailability.FAILED)
        )
        if state == ModelAvailability.MISSING:
            self.model_status_label.setText(
                "המודל אינו מותקן. תמלול מקומי יהיה זמין לאחר הורדתו."
            )
            self.model_action_button.setText("הורד מודל")
        elif state == ModelAvailability.DOWNLOADING:
            self.model_status_label.setText("מוריד את מודל התמלול…")
            self.model_progress.setRange(0, 0)
        elif state == ModelAvailability.VERIFYING:
            self.model_status_label.setText("מאמת את המודל המקומי…")
            self.model_progress.setRange(0, 0)
        elif state == ModelAvailability.AVAILABLE:
            self.model_status_label.setText("מודל התמלול מותקן ומאומת.")
        else:
            self.model_status_label.setText("התקנת מודל התמלול נכשלה.")
            self.model_action_button.setText("נסה שוב")

    def _show_progress(self, progress: DownloadProgress) -> None:
        if progress.total_files > 0:
            self.model_progress.setRange(0, progress.total_files)
            self.model_progress.setValue(progress.completed_files)
            self.model_progress.setFormat(
                f"{progress.completed_files} מתוך {progress.total_files} קבצים"
            )
        else:
            self.model_progress.setRange(0, 0)

    def _show_error(self, message: str) -> None:
        self.model_error_label.setText(message)
        self.model_error_label.setVisible(bool(message))

    def _show_credential_message(self, text: str, message_type: str) -> None:
        self.credential_status_label.setText(text)
        self.credential_status_label.setProperty("messageType", message_type)
        self.credential_status_label.style().unpolish(self.credential_status_label)
        self.credential_status_label.style().polish(self.credential_status_label)

    @staticmethod
    def _ltr_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("technicalValue")
        label.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setWordWrap(True)
        return label
