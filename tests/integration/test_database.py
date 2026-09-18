from uuid import uuid4

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from sikumon.config.constants import CURRENT_SCHEMA_VERSION
from sikumon.database.migrations import apply_migrations, get_schema_version
from sikumon.database.orm_models import (
    ActionItemORM,
    DecisionORM,
    EvidenceReferenceORM,
    MeetingAnalysisORM,
    MeetingORM,
    SchemaVersionORM,
    TranscriptSegmentORM,
)
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import TranscriptionStatus


def test_sqlite_initialization_and_schema_version(database) -> None:
    engine, session_factory = database
    table_names = set(inspect(engine).get_table_names())
    assert {
        "schema_version",
        "meetings",
        "transcript_segments",
        "meeting_analyses",
        "decisions",
        "action_items",
        "evidence_references",
    } <= table_names
    assert get_schema_version(engine) == CURRENT_SCHEMA_VERSION
    assert apply_migrations(engine) == CURRENT_SCHEMA_VERSION
    with session_factory() as session:
        assert session.get(SchemaVersionORM, 1).version == CURRENT_SCHEMA_VERSION


def test_foreign_keys_are_enabled_and_enforced_on_every_connection(database) -> None:
    engine, _ = database
    with engine.connect() as first, engine.connect() as second:
        assert first.scalar(text("PRAGMA foreign_keys")) == 1
        assert second.scalar(text("PRAGMA foreign_keys")) == 1
        with pytest.raises(IntegrityError):
            second.execute(
                text(
                    "INSERT INTO transcript_segments "
                    "(id, meeting_id, position, start_time_ms, end_time_ms, text, created_at, updated_at) "
                    "VALUES ('orphan', 'missing', 0, 0, 1, 'x', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )


def test_database_rejects_non_durable_status_values(database) -> None:
    _, session_factory = database
    meeting = MeetingRepository(session_factory).create(
        MeetingORM(title="סטטוס", original_filename="a.wav", audio_path="a.wav")
    )
    with session_factory() as session, pytest.raises(IntegrityError):
        session.execute(
            text("UPDATE meetings SET transcription_status = 'OUTDATED' WHERE id = :id"),
            {"id": meeting.id},
        )
        session.commit()


def test_meeting_and_transcript_revision_persist(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = repository.create(
        MeetingORM(
            title="פגישת מוצר",
            original_filename="product.wav",
            audio_path="C:/data/product.wav",
            audio_duration_seconds=42.5,
        )
    )

    with session_factory() as session, session.begin():
        stored = session.get(MeetingORM, meeting.id)
        stored.transcript_segments.append(
            TranscriptSegmentORM(
                position=0,
                start_time_ms=100,
                end_time_ms=2_500,
                text="בוקר טוב",
            )
        )
        stored.transcript_revision = 1
        stored.transcription_status = TranscriptionStatus.COMPLETED

    reloaded = repository.get(meeting.id)
    assert reloaded.audio_duration_seconds == 42.5
    assert reloaded.transcript_revision == 1
    assert reloaded.transcript_segments[0].text == "בוקר טוב"
    assert reloaded.created_at.tzinfo is not None


def test_meeting_list_survives_new_repository_instance(database) -> None:
    _, session_factory = database
    first = MeetingRepository(session_factory)
    first.create(MeetingORM(title="ראשונה", original_filename="a.wav", audio_path="a.wav"))
    first.create(MeetingORM(title="שנייה", original_filename="b.wav", audio_path="b.wav"))
    second = MeetingRepository(session_factory)
    assert {meeting.title for meeting in second.list()} == {"ראשונה", "שנייה"}


def test_current_analysis_graph_loads_and_cascades_on_meeting_delete(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    untouched = repository.create(
        MeetingORM(title="אחרת", original_filename="b.wav", audio_path="b.wav")
    )
    meeting = repository.create(
        MeetingORM(title="ניתוח", original_filename="a.wav", audio_path="a.wav")
    )
    with session_factory() as session, session.begin():
        stored = session.get(MeetingORM, meeting.id)
        segment = TranscriptSegmentORM(
            position=0, start_time_ms=0, end_time_ms=1_000, text="הוחלט להתקדם"
        )
        stored.transcript_segments.append(segment)
        stored.transcript_revision = 1
        analysis = MeetingAnalysisORM(
            provider="openai",
            model="test-model",
            prompt_version="1",
            schema_version="1",
            source_transcript_revision=1,
            summary="סיכום",
        )
        decision = DecisionORM(position=0, title="להתקדם")
        task = ActionItemORM(position=0, title="לשלוח מסמך")
        analysis.decisions.append(decision)
        analysis.action_items.append(task)
        stored.analyses.append(analysis)
        session.flush()
        analysis.evidence_references.extend(
            [
                EvidenceReferenceORM(
                    decision_id=decision.id,
                    transcript_segment_id=segment.id,
                    position=0,
                ),
                EvidenceReferenceORM(
                    action_item_id=task.id,
                    transcript_segment_id=segment.id,
                    position=0,
                ),
            ]
        )
        stored.current_analysis = analysis

    loaded = repository.get(meeting.id)
    assert loaded.current_analysis.summary == "סיכום"
    assert len(loaded.current_analysis.evidence_references) == 2
    assert repository.delete(meeting.id)

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MeetingORM)) == 1
        assert session.get(MeetingORM, untouched.id) is not None
        for entity in (
            TranscriptSegmentORM,
            MeetingAnalysisORM,
            DecisionORM,
            ActionItemORM,
            EvidenceReferenceORM,
        ):
            assert session.scalar(select(func.count()).select_from(entity)) == 0


def test_current_analysis_must_belong_to_the_same_meeting(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    first = repository.create(
        MeetingORM(title="ראשונה", original_filename="a.wav", audio_path="a.wav")
    )
    second = repository.create(
        MeetingORM(title="שנייה", original_filename="b.wav", audio_path="b.wav")
    )
    with session_factory() as session, session.begin():
        owner = session.get(MeetingORM, first.id)
        analysis = MeetingAnalysisORM(
            provider="openai",
            model="test-model",
            prompt_version="1",
            schema_version="1",
            source_transcript_revision=0,
            summary="סיכום",
        )
        owner.analyses.append(analysis)

    with session_factory() as session:
        other = session.get(MeetingORM, second.id)
        other.current_analysis_id = analysis.id
        with pytest.raises(IntegrityError):
            session.commit()


def test_evidence_owner_must_belong_to_its_declared_analysis(database) -> None:
    _, session_factory = database
    meeting = MeetingRepository(session_factory).create(
        MeetingORM(title="ראיות", original_filename="a.wav", audio_path="a.wav")
    )
    with session_factory() as session, session.begin():
        stored = session.get(MeetingORM, meeting.id)
        segment = TranscriptSegmentORM(
            position=0, start_time_ms=0, end_time_ms=500, text="ראיה"
        )
        first_analysis = MeetingAnalysisORM(
            provider="openai",
            model="test-model",
            prompt_version="1",
            schema_version="1",
            source_transcript_revision=0,
            summary="ראשון",
        )
        second_analysis = MeetingAnalysisORM(
            provider="openai",
            model="test-model",
            prompt_version="1",
            schema_version="1",
            source_transcript_revision=0,
            summary="שני",
        )
        decision = DecisionORM(position=0, title="החלטה")
        first_analysis.decisions.append(decision)
        stored.transcript_segments.append(segment)
        stored.analyses.extend([first_analysis, second_analysis])
        session.flush()
        second_analysis_id = second_analysis.id
        decision_id = decision.id
        segment_id = segment.id

    with session_factory() as session, pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO evidence_references "
                "(id, analysis_id, decision_id, action_item_id, transcript_segment_id, position) "
                "VALUES (:id, :analysis_id, :decision_id, NULL, :segment_id, 0)"
            ),
            {
                "id": str(uuid4()),
                "analysis_id": second_analysis_id,
                "decision_id": decision_id,
                "segment_id": segment_id,
            },
        )
