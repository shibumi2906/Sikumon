"""Editable, ordered Hebrew transcript with local deterministic dirty state."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from sikumon.application.transcript_export import ExportSegment
from sikumon.domain.transcript import TranscriptSegment
from sikumon.ui.presentation import format_timestamp_ms


class TranscriptView(QWidget):
    dirty_changed = Signal(bool)
    save_requested = Signal()
    copy_requested = Signal()
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._persisted_texts: dict[str, str] = {}
        self._source_revision = 0
        self._editing_blocked = False
        self._save_blocked = False
        self._save_in_progress = False
        self._dirty = False
        self._highlighted_segment_id: str | None = None
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        self.actions_bar = QWidget()
        self.actions_bar.setObjectName("transcriptActionsBar")
        actions = QHBoxLayout(self.actions_bar)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.copy_button = QPushButton("העתק תמלול")
        self.copy_button.setObjectName("copyTranscriptButton")
        self.copy_button.clicked.connect(self.copy_requested.emit)
        self.export_button = QPushButton("ייצוא תמלול")
        self.export_button.setObjectName("exportTranscriptButton")
        self.export_button.clicked.connect(self.export_requested.emit)
        actions.addStretch()
        actions.addWidget(self.copy_button)
        actions.addWidget(self.export_button)
        layout.addWidget(self.actions_bar)

        self.save_bar = QWidget()
        self.save_bar.setObjectName("transcriptSaveBar")
        toolbar = QHBoxLayout(self.save_bar)
        toolbar.setContentsMargins(12, 8, 12, 8)
        toolbar.setSpacing(8)
        self.unsaved_label = QLabel("יש שינויים שלא נשמרו")
        self.unsaved_label.setObjectName("transcriptUnsavedLabel")
        self.unsaved_label.setVisible(False)
        self.save_button = QPushButton("שמור")
        self.save_button.setObjectName("saveTranscriptButton")
        self.save_button.setProperty("buttonRole", "primary")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_requested)
        toolbar.addWidget(self.unsaved_label)
        toolbar.addStretch()
        toolbar.addWidget(self.save_button)
        layout.addWidget(self.save_bar)
        self.save_bar.setVisible(False)

        self.empty_label = QLabel("התמלול יוצג כאן לאחר עיבוד ההקלטה")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.segment_container = QWidget()
        self.segment_layout = QVBoxLayout(self.segment_container)
        self.segment_layout.setContentsMargins(8, 0, 8, 8)
        self.segment_layout.setSpacing(0)
        self.segment_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.segment_container)
        layout.addWidget(self.scroll_area, 1)
        self.segment_editors: list[QPlainTextEdit] = []
        self.segment_editors_by_id: dict[str, QPlainTextEdit] = {}
        self.segment_cards_by_id: dict[str, QWidget] = {}
        self.timestamp_labels: list[QLabel] = []
        self.set_segments(())

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def source_revision(self) -> int:
        return self._source_revision

    @property
    def highlighted_segment_id(self) -> str | None:
        return self._highlighted_segment_id

    def set_segments(
        self,
        segments: Sequence[TranscriptSegment],
        revision: int = 0,
        *,
        editing_blocked: bool = False,
        save_blocked: bool = False,
    ) -> None:
        while self.segment_layout.count():
            item = self.segment_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.segment_editors.clear()
        self.segment_editors_by_id.clear()
        self.segment_cards_by_id.clear()
        self.timestamp_labels.clear()
        self._persisted_texts.clear()
        self._source_revision = revision
        self._editing_blocked = editing_blocked
        self._save_blocked = save_blocked
        self._save_in_progress = False
        self._highlighted_segment_id = None
        ordered = sorted(segments, key=lambda segment: segment.position)
        self._export_metadata = {
            str(segment.id): (segment.start_time_ms, segment.end_time_ms)
            for segment in ordered
        }
        for segment in ordered:
            segment_id = str(segment.id)
            card = QWidget()
            card.setObjectName("transcriptSegment")
            card.setProperty("evidenceTarget", False)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 11, 10, 11)
            card_layout.setSpacing(4)
            timestamp = QLabel(format_timestamp_ms(segment.start_time_ms))
            timestamp.setObjectName("transcriptTimestamp")
            timestamp.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            timestamp.setAlignment(Qt.AlignmentFlag.AlignLeft)
            timestamp.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text = QPlainTextEdit()
            text.setObjectName("transcriptTextEditor")
            text.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            text.setPlainText(segment.text)
            text.setReadOnly(editing_blocked)
            text.setMinimumHeight(58)
            text.setTabChangesFocus(True)
            text.textChanged.connect(self._update_dirty_state)
            card_layout.addWidget(timestamp)
            card_layout.addWidget(text)
            self.segment_layout.addWidget(card)
            self.timestamp_labels.append(timestamp)
            self.segment_editors.append(text)
            self.segment_editors_by_id[segment_id] = text
            self.segment_cards_by_id[segment_id] = card
            self._persisted_texts[segment_id] = segment.text
        self.empty_label.setVisible(not ordered)
        self.scroll_area.setVisible(bool(ordered))
        self.actions_bar.setVisible(bool(ordered))
        self._set_dirty(False)
        self._update_save_enabled()

    def current_texts(self) -> dict[str, str]:
        return {
            segment_id: editor.toPlainText()
            for segment_id, editor in self.segment_editors_by_id.items()
        }

    def export_segments(self) -> tuple[ExportSegment, ...]:
        return tuple(
            ExportSegment(
                start_time_ms=self._export_metadata[segment_id][0],
                end_time_ms=self._export_metadata[segment_id][1],
                text=editor.toPlainText(),
            )
            for segment_id, editor in self.segment_editors_by_id.items()
        )

    def discard_changes(self) -> None:
        for segment_id, editor in self.segment_editors_by_id.items():
            editor.blockSignals(True)
            editor.setPlainText(self._persisted_texts[segment_id])
            editor.blockSignals(False)
        self._set_dirty(False)

    def set_editing_blocked(self, blocked: bool) -> None:
        self._editing_blocked = blocked
        for editor in self.segment_editors:
            editor.setReadOnly(blocked)
        self._update_save_enabled()

    def set_save_blocked(self, blocked: bool) -> None:
        self._save_blocked = blocked
        self._update_save_enabled()

    def set_save_in_progress(self, active: bool) -> None:
        self._save_in_progress = active
        self._update_save_enabled()

    def editor_for_segment(self, segment_id: str) -> QPlainTextEdit | None:
        return self.segment_editors_by_id.get(segment_id)

    def focus_segment(self, segment_id: str) -> bool:
        editor = self.segment_editors_by_id.get(segment_id)
        card = self.segment_cards_by_id.get(segment_id)
        if editor is None or card is None:
            return False
        if self._highlighted_segment_id is not None:
            previous = self.segment_cards_by_id.get(self._highlighted_segment_id)
            if previous is not None:
                previous.setProperty("evidenceTarget", False)
                previous.style().unpolish(previous)
                previous.style().polish(previous)
        card.setProperty("evidenceTarget", True)
        card.style().unpolish(card)
        card.style().polish(card)
        self._highlighted_segment_id = segment_id
        self.scroll_area.ensureWidgetVisible(card)
        editor.setFocus()
        return True

    def _update_dirty_state(self) -> None:
        current = self.current_texts()
        self._set_dirty(current != self._persisted_texts)

    def _set_dirty(self, dirty: bool) -> None:
        if self._dirty != dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)
        self.unsaved_label.setVisible(dirty)
        self.save_bar.setVisible(dirty)
        self._update_save_enabled()

    def _update_save_enabled(self) -> None:
        self.save_button.setEnabled(
            bool(self._persisted_texts)
            and self._dirty
            and not self._editing_blocked
            and not self._save_blocked
            and not self._save_in_progress
        )
