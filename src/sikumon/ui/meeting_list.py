"""Database-backed meeting list widget."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sikumon.application.meeting_service import MeetingService
from sikumon.ui.presentation import STATUS_LABELS
from sikumon.ui.resources import asset_path


class MeetingListWidget(QWidget):
    meeting_selected = Signal(str)
    new_meeting_requested = Signal()
    settings_requested = Signal()

    def __init__(self, meeting_service: MeetingService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._meeting_service = meeting_service
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setObjectName("meetingSidebar")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(14)

        brand = QWidget()
        brand_layout = QHBoxLayout(brand)
        brand_layout.setContentsMargins(2, 0, 2, 4)
        brand_layout.setSpacing(10)
        mark = QLabel()
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setMinimumSize(42, 42)
        mark.setMaximumSize(42, 42)
        mark.setPixmap(
            QPixmap(str(asset_path("brand-mark.svg"))).scaled(
                42,
                42,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        wordmark = QLabel("SIKUMON")
        wordmark.setObjectName("brandWordmark")
        tagline = QLabel("פגישות. תובנות. פעולה.")
        tagline.setObjectName("brandTagline")
        brand_text.addWidget(wordmark)
        brand_text.addWidget(tagline)
        brand_layout.addLayout(brand_text, 1)
        brand_layout.addWidget(mark)
        layout.addWidget(brand)

        self.new_meeting_button = QPushButton("פגישה חדשה")
        self.new_meeting_button.setIcon(QIcon(str(asset_path("plus.svg"))))
        self.new_meeting_button.setObjectName("newMeetingButton")
        self.new_meeting_button.setProperty("buttonRole", "primary")
        self.new_meeting_button.setToolTip("ייבוא הקלטת פגישה חדשה")
        self.new_meeting_button.clicked.connect(self.new_meeting_requested)
        layout.addWidget(self.new_meeting_button)

        section_title = QLabel("הפגישות שלי")
        section_title.setObjectName("sidebarSectionTitle")
        section_title.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(section_title)

        self.list_widget = QListWidget()
        self.list_widget.setSpacing(4)
        self.list_widget.currentItemChanged.connect(self._emit_selection)
        layout.addWidget(self.list_widget, 1)

        self.empty_state = QFrame()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.addStretch()
        empty_title = QLabel("אין עדיין פגישות")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = QLabel("הפגישה הראשונה שלך תופיע כאן")
        empty_hint.setWordWrap(True)
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch()
        layout.addWidget(self.empty_state, 1)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("sidebarSeparator")
        layout.addWidget(separator)
        self.settings_button = QPushButton("הגדרות")
        self.settings_button.setIcon(QIcon(str(asset_path("settings.svg"))))
        self.settings_button.setObjectName("settingsButton")
        self.settings_button.setProperty("buttonRole", "ghost")
        self.settings_button.clicked.connect(self.settings_requested)
        layout.addWidget(self.settings_button)
        self.reload()

    def reload(self, select_meeting_id: str | None = None) -> None:
        self.list_widget.clear()
        meetings = self._meeting_service.list_meetings()
        selected_item: QListWidgetItem | None = None
        for meeting in meetings:
            created = meeting.created_at.astimezone().strftime("%d.%m.%Y  %H:%M")
            item = QListWidgetItem(
                f"{meeting.title}\n{created}  ·  {STATUS_LABELS[meeting.display_state]}"
            )
            item.setData(Qt.ItemDataRole.UserRole, meeting.id)
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
            item.setSizeHint(QSize(0, 64))
            self.list_widget.addItem(item)
            if meeting.id == select_meeting_id:
                selected_item = item
        has_meetings = bool(meetings)
        self.list_widget.setVisible(has_meetings)
        self.empty_state.setVisible(not has_meetings)
        if selected_item is not None:
            self.list_widget.setCurrentItem(selected_item)

    def select_meeting(self, meeting_id: str | None) -> None:
        blocker = QSignalBlocker(self.list_widget)
        try:
            if meeting_id is None:
                self.list_widget.setCurrentRow(-1)
                self.list_widget.clearSelection()
                return
            for index in range(self.list_widget.count()):
                item = self.list_widget.item(index)
                if str(item.data(Qt.ItemDataRole.UserRole)) == meeting_id:
                    self.list_widget.setCurrentItem(item)
                    return
        finally:
            del blocker

    def _emit_selection(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if current is not None:
            self.meeting_selected.emit(str(current.data(Qt.ItemDataRole.UserRole)))
