from unittest.mock import Mock
from uuid import uuid4

from sikumon.application.analysis_presentation import (
    build_analysis_presentation,
    format_evidence_preview,
)
from sikumon.database.orm_models import (
    ActionItemORM,
    DecisionORM,
    EvidenceReferenceORM,
    MeetingAnalysisORM,
    MeetingORM,
    TranscriptSegmentORM,
)


def analysis_meeting() -> tuple[MeetingORM, str, str]:
    meeting = MeetingORM(
        id=str(uuid4()),
        title="פגישה",
        original_filename="meeting.wav",
        audio_path="meeting.wav",
        transcript_revision=2,
    )
    first_id = str(uuid4())
    second_id = str(uuid4())
    meeting.transcript_segments = [
        TranscriptSegmentORM(
            id=first_id,
            meeting_id=meeting.id,
            position=0,
            start_time_ms=65_000,
            end_time_ms=66_000,
            text="  הוחלט   להתקדם עם התוכנית  ",
        ),
        TranscriptSegmentORM(
            id=second_id,
            meeting_id=meeting.id,
            position=1,
            start_time_ms=125_000,
            end_time_ms=126_000,
            text="דנה תשלח את המסמך ביום ראשון",
        ),
    ]
    analysis = MeetingAnalysisORM(
        id=str(uuid4()),
        meeting_id=meeting.id,
        provider="openai",
        model="model",
        prompt_version="1",
        schema_version="1",
        source_transcript_revision=1,
        summary="סיכום בעברית",
    )
    decision = DecisionORM(
        id=str(uuid4()),
        analysis_id=analysis.id,
        position=0,
        title="להתקדם",
        description=None,
    )
    task = ActionItemORM(
        id=str(uuid4()),
        analysis_id=analysis.id,
        position=0,
        title="לשלוח מסמך",
        description="המסמך המעודכן",
        assignee="דנה",
        deadline="יום ראשון",
    )
    analysis.decisions = [decision]
    analysis.action_items = [task]
    analysis.evidence_references = [
        EvidenceReferenceORM(
            analysis_id=analysis.id,
            decision_id=decision.id,
            transcript_segment_id=first_id,
            position=0,
        ),
        EvidenceReferenceORM(
            analysis_id=analysis.id,
            action_item_id=task.id,
            transcript_segment_id=first_id,
            position=0,
        ),
        EvidenceReferenceORM(
            analysis_id=analysis.id,
            action_item_id=task.id,
            transcript_segment_id=second_id,
            position=1,
        ),
    ]
    meeting.current_analysis = analysis
    meeting.current_analysis_id = analysis.id
    return meeting, first_id, second_id


def test_evidence_preview_normalizes_and_truncates() -> None:
    assert format_evidence_preview("  שלום\n  עולם ") == "שלום עולם"
    assert format_evidence_preview("abcdefgh", 5) == "abcd…"


def test_persisted_analysis_maps_ordered_evidence_optional_fields_and_freshness() -> None:
    meeting, first_id, second_id = analysis_meeting()
    result = build_analysis_presentation(meeting)

    assert result is not None
    assert result.summary == "סיכום בעברית"
    assert result.is_outdated
    assert result.decisions[0].description is None
    assert result.decisions[0].evidence[0].segment_id == first_id
    assert result.decisions[0].evidence[0].start_time_ms == 65_000
    assert result.action_items[0].assignee == "דנה"
    assert result.action_items[0].deadline == "יום ראשון"
    assert [evidence.segment_id for evidence in result.action_items[0].evidence] == [
        first_id,
        second_id,
    ]

    meeting.transcript_revision = 1
    current = build_analysis_presentation(meeting)
    assert current is not None
    assert not current.is_outdated


def test_missing_evidence_is_unavailable_and_logged() -> None:
    meeting, _, _ = analysis_meeting()
    missing_id = str(uuid4())
    meeting.current_analysis.evidence_references[0].transcript_segment_id = missing_id
    logger = Mock()

    result = build_analysis_presentation(meeting, logger)

    assert result is not None
    evidence = result.decisions[0].evidence[0]
    assert evidence.segment_id == missing_id
    assert not evidence.available
    assert evidence.preview == "המקור אינו זמין"
    logger.warning.assert_called_once()
