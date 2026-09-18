from sikumon.application.analysis_presentation import (
    ActionItemPresentation,
    AnalysisPresentation,
    DecisionPresentation,
    EvidencePresentation,
)
from sikumon.ui.analysis_view import DecisionsView, SummaryView, TasksView


def presentation(
    *,
    decisions: tuple[DecisionPresentation, ...] = (),
    tasks: tuple[ActionItemPresentation, ...] = (),
) -> AnalysisPresentation:
    return AnalysisPresentation("סיכום ברור", decisions, tasks, False)


def test_summary_and_intentional_empty_states_render_in_hebrew(qapp) -> None:
    summary = SummaryView()
    decisions = DecisionsView()
    tasks = TasksView()
    data = presentation()

    summary.set_analysis(data, has_transcript=True)
    decisions.set_analysis(data, has_transcript=True)
    tasks.set_analysis(data, has_transcript=True)

    assert summary.summary_label.text() == "סיכום ברור"
    assert "לא זוהו החלטות" in decisions.empty_label.text()
    assert "לא זוהו משימות" in tasks.empty_label.text()
    summary.set_analysis(None, has_transcript=False)
    assert "לתמלל" in summary.empty_label.text()


def test_tasks_render_optional_fields_timestamp_and_clickable_evidence(qapp) -> None:
    evidence = EvidencePresentation("segment-1", 65_000, "קטע מקור", True)
    task = ActionItemPresentation(
        "שליחת מסמך",
        None,
        None,
        None,
        (evidence,),
    )
    view = TasksView()
    selected: list[str] = []
    view.evidence_selected.connect(selected.append)
    view.set_analysis(presentation(tasks=(task,)), has_transcript=True)

    assert len(view.item_cards) == 1
    assert len(view.evidence_buttons) == 1
    assert "01:05" in view.evidence_buttons[0].text()
    assert not view.findChildren(type(view.empty_label), "analysisAssignee")
    assert not view.findChildren(type(view.empty_label), "analysisDeadline")
    view.evidence_buttons[0].click()
    assert selected == ["segment-1"]

    task_with_optional = ActionItemPresentation(
        "שליחת מסמך", None, "דנה", "יום ראשון", (evidence,)
    )
    view.set_analysis(presentation(tasks=(task_with_optional,)), has_transcript=True)
    assert view.findChild(type(view.empty_label), "analysisAssignee").text() == "אחראי: דנה"
    assert view.findChild(type(view.empty_label), "analysisDeadline").text() == "מועד: יום ראשון"


def test_unavailable_evidence_is_visible_but_not_clickable(qapp) -> None:
    decision = DecisionPresentation(
        "החלטה",
        None,
        (EvidencePresentation("missing", None, "המקור אינו זמין", False),),
    )
    view = DecisionsView()
    view.set_analysis(presentation(decisions=(decision,)), has_transcript=True)

    assert len(view.evidence_buttons) == 1
    assert view.evidence_buttons[0].text() == "המקור אינו זמין"
    assert not view.evidence_buttons[0].isEnabled()
