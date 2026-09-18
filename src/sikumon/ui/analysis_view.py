"""Native Hebrew presentation widgets for persisted meeting analysis."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sikumon.application.analysis_presentation import (
    ActionItemPresentation,
    AnalysisPresentation,
    DecisionPresentation,
    EvidencePresentation,
)
from sikumon.ui.presentation import format_timestamp_ms


def _label(text: str, object_name: str = "analysisText") -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    label.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class SummaryView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        canvas = QWidget()
        canvas_layout = QHBoxLayout(canvas)
        canvas_layout.setContentsMargins(26, 24, 26, 24)
        canvas_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        canvas_layout.addStretch()
        surface = QFrame()
        surface.setObjectName("summarySurface")
        surface.setMaximumWidth(860)
        surface.setMinimumWidth(520)
        surface.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(30, 26, 30, 30)
        surface_layout.setSpacing(16)
        self.heading = _label("סיכום הפגישה", "analysisSectionTitle")
        self.summary_label = _label("", "analysisSummary")
        self.summary_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.empty_label = _label("", "analysisEmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setMinimumHeight(140)
        surface_layout.addWidget(self.heading)
        surface_layout.addWidget(self.summary_label)
        surface_layout.addWidget(self.empty_label)
        canvas_layout.addWidget(surface, 1, Qt.AlignmentFlag.AlignTop)
        canvas_layout.addStretch()
        scroll.setWidget(canvas)
        layout.addWidget(scroll)

    def set_analysis(
        self, analysis: AnalysisPresentation | None, *, has_transcript: bool
    ) -> None:
        if analysis is None:
            self.summary_label.clear()
            self.summary_label.setVisible(False)
            self.empty_label.setText(
                "טרם נוצר ניתוח לפגישה זו."
                if has_transcript
                else "יש לתמלל את הפגישה לפני יצירת ניתוח."
            )
            self.empty_label.setVisible(True)
            return
        self.summary_label.setText(analysis.summary)
        self.summary_label.setVisible(True)
        self.empty_label.setVisible(False)


class EvidenceButton(QPushButton):
    def __init__(self, evidence: EvidencePresentation, parent: QWidget | None = None) -> None:
        timestamp = (
            format_timestamp_ms(evidence.start_time_ms)
            if evidence.start_time_ms is not None
            else "—"
        )
        text = (
            f"\u200e{timestamp}\u200e    {evidence.preview}"
            if evidence.available
            else evidence.preview
        )
        super().__init__(text, parent)
        self.segment_id = evidence.segment_id
        self.setObjectName("evidenceButton" if evidence.available else "missingEvidence")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setEnabled(evidence.available)
        self.setToolTip("מעבר למקטע התמלול התומך" if evidence.available else evidence.preview)
        self.setAccessibleName(
            f"מקור בשעה {timestamp}: {evidence.preview}"
            if evidence.available
            else evidence.preview
        )


class AnalysisCollectionView(QWidget):
    evidence_selected = Signal(str)

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.container = QWidget()
        self.cards_layout = QVBoxLayout(self.container)
        self.cards_layout.setContentsMargins(28, 24, 28, 24)
        self.cards_layout.setSpacing(12)
        self.cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.container)
        layout.addWidget(self.scroll_area)
        self.empty_label = _label("", "analysisEmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cards_layout.addWidget(self.empty_label)
        self.item_cards: list[QFrame] = []
        self.evidence_buttons: list[EvidenceButton] = []

    def set_analysis(
        self, analysis: AnalysisPresentation | None, *, has_transcript: bool
    ) -> None:
        self._clear_cards()
        if analysis is None:
            self.empty_label.setText(
                "טרם נוצר ניתוח לפגישה זו."
                if has_transcript
                else "יש לתמלל את הפגישה לפני הצגת תוצאות ניתוח."
            )
            self.empty_label.setVisible(True)
            return
        items: Sequence[DecisionPresentation | ActionItemPresentation]
        if self._kind == "decisions":
            items = analysis.decisions
            empty_text = "לא זוהו החלטות בפגישה זו."
        else:
            items = analysis.action_items
            empty_text = "לא זוהו משימות לביצוע בפגישה זו."
        if not items:
            self.empty_label.setText(empty_text)
            self.empty_label.setVisible(True)
            return
        self.empty_label.setVisible(False)
        for item in items:
            self._add_card(item)
        self.cards_layout.addStretch()

    def _clear_cards(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None and widget is not self.empty_label:
                widget.deleteLater()
        self.cards_layout.addWidget(self.empty_label)
        self.item_cards.clear()
        self.evidence_buttons.clear()

    def _add_card(self, item: DecisionPresentation | ActionItemPresentation) -> None:
        card = QFrame()
        card.setObjectName("analysisCard")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setMaximumWidth(900)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(10)
        card_layout.addWidget(_label(item.title, "analysisItemTitle"))
        if item.description:
            card_layout.addWidget(_label(item.description, "analysisItemDescription"))
        if isinstance(item, ActionItemPresentation):
            if item.assignee:
                card_layout.addWidget(_label(f"אחראי: {item.assignee}", "analysisAssignee"))
            if item.deadline:
                card_layout.addWidget(_label(f"מועד: {item.deadline}", "analysisDeadline"))
        card_layout.addWidget(_label("מקור בתמלול", "analysisEvidenceTitle"))
        for evidence in item.evidence:
            button = EvidenceButton(evidence)
            button.clicked.connect(
                lambda checked=False, segment_id=evidence.segment_id: (
                    self.evidence_selected.emit(segment_id)
                )
            )
            card_layout.addWidget(button)
            self.evidence_buttons.append(button)
        self.cards_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        self.item_cards.append(card)


class DecisionsView(AnalysisCollectionView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("decisions", parent)


class TasksView(AnalysisCollectionView):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("tasks", parent)
