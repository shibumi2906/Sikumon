from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from sikumon.application.meeting_service import (
    MeetingDisplayState,
    derive_display_state,
)
from sikumon.application.transcript_edit_service import (
    TranscriptEditService,
    TranscriptSaveBlockedError,
    TranscriptSaveConflictError,
    TranscriptSaveError,
)
from sikumon.database.db import create_session_factory, create_sqlite_engine
from sikumon.database.migrations import apply_migrations
from sikumon.database.orm_models import MeetingAnalysisORM, MeetingORM
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus
from sikumon.domain.transcript import TranscriptSegmentDraft


def create_transcript(repository: MeetingRepository) -> MeetingORM:
    meeting = repository.create(
        MeetingORM(title="עריכה", original_filename="he.mp3", audio_path="he.mp3")
    )
    repository.replace_transcript(
        meeting.id,
        (
            TranscriptSegmentDraft(uuid4(), 0, 500, 2_000, "טקסט ראשון"),
            TranscriptSegmentDraft(uuid4(), 1, 2_500, 4_000, "טקסט שני"),
        ),
    )
    loaded = repository.get(meeting.id)
    assert loaded is not None
    return loaded


def test_edit_save_reload_preserves_metadata_and_increments_once(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    before = create_transcript(repository)
    service = TranscriptEditService(repository)
    first, second = before.transcript_segments
    original = {
        item.id: (
            item.position,
            item.start_time_ms,
            item.end_time_ms,
            item.created_at,
            item.updated_at,
        )
        for item in before.transcript_segments
    }

    snapshot = service.save(
        before.id,
        1,
        {first.id: "תיקון ראשון", second.id: "תיקון שני"},
    )
    restarted = MeetingRepository(session_factory).get(before.id)
    assert restarted is not None

    assert snapshot.changed_segment_count == 2
    assert snapshot.revision == 2
    assert restarted.transcript_revision == 2
    assert restarted.transcription_status == TranscriptionStatus.COMPLETED
    assert [item.text for item in restarted.transcript_segments] == [
        "תיקון ראשון",
        "תיקון שני",
    ]
    for item in restarted.transcript_segments:
        position, start, end, created, updated = original[item.id]
        assert (item.position, item.start_time_ms, item.end_time_ms) == (
            position,
            start,
            end,
        )
        assert item.created_at == created
        assert item.updated_at > updated


def test_ids_survive_multiple_save_reload_cycles_and_engine_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "restart" / "sikumon.db"
    engine = create_sqlite_engine(database_path)
    apply_migrations(engine)
    repository = MeetingRepository(create_session_factory(engine))
    before = create_transcript(repository)
    original_metadata = {
        item.id: (
            item.position,
            item.start_time_ms,
            item.end_time_ms,
            item.created_at,
        )
        for item in before.transcript_segments
    }
    first, second = before.transcript_segments
    service = TranscriptEditService(repository)

    first_save = service.save(
        before.id,
        1,
        {first.id: "תיקון ראשון", second.id: second.text},
    )
    reloaded = repository.get(before.id)
    assert reloaded is not None
    second_save = service.save(
        before.id,
        reloaded.transcript_revision,
        {
            reloaded.transcript_segments[0].id: reloaded.transcript_segments[0].text,
            reloaded.transcript_segments[1].id: "תיקון שני",
        },
    )
    engine.dispose()

    restarted_engine = create_sqlite_engine(database_path)
    try:
        restarted = MeetingRepository(create_session_factory(restarted_engine)).get(before.id)
        assert restarted is not None
        assert first_save.revision == 2
        assert second_save.revision == 3
        assert restarted.transcript_revision == 3
        assert [item.text for item in restarted.transcript_segments] == [
            "תיקון ראשון",
            "תיקון שני",
        ]
        assert {
            item.id: (
                item.position,
                item.start_time_ms,
                item.end_time_ms,
                item.created_at,
            )
            for item in restarted.transcript_segments
        } == original_metadata
    finally:
        restarted_engine.dispose()


def test_noop_save_changes_no_revision_or_timestamps(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    before = create_transcript(repository)
    before_updated = before.transcript_updated_at
    segment_updates = {item.id: item.updated_at for item in before.transcript_segments}

    result = TranscriptEditService(repository).save(
        before.id,
        before.transcript_revision,
        {item.id: item.text for item in before.transcript_segments},
    )
    after = repository.get(before.id)
    assert after is not None

    assert result.changed_segment_count == 0
    assert after.transcript_revision == 1
    assert after.transcript_updated_at == before_updated
    assert {item.id: item.updated_at for item in after.transcript_segments} == segment_updates


def test_only_changed_segment_gets_new_updated_at(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    before = create_transcript(repository)
    first, second = before.transcript_segments

    TranscriptEditService(repository).save(
        before.id,
        1,
        {first.id: "השתנה", second.id: second.text},
    )
    after = repository.get(before.id)
    assert after is not None
    changed, unchanged = after.transcript_segments
    assert changed.updated_at > first.updated_at
    assert unchanged.updated_at == second.updated_at


def test_stale_revision_and_wrong_segment_set_do_not_overwrite(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    before = create_transcript(repository)
    first, second = before.transcript_segments
    service = TranscriptEditService(repository)
    service.save(before.id, 1, {first.id: "חדש", second.id: second.text})

    with pytest.raises(TranscriptSaveConflictError):
        service.save(before.id, 1, {first.id: "ישן", second.id: "דריסה"})
    with pytest.raises(TranscriptSaveConflictError):
        service.save(before.id, 2, {first.id: "חסר סגמנט"})

    after = repository.get(before.id)
    assert after is not None
    assert after.transcript_revision == 2
    assert [item.text for item in after.transcript_segments] == ["חדש", "טקסט שני"]


def test_database_failure_rolls_back_all_text_edits(database) -> None:
    engine, session_factory = database
    repository = MeetingRepository(session_factory)
    before = create_transcript(repository)
    first, second = before.transcript_segments
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER fail_second_segment BEFORE UPDATE OF text "
                "ON transcript_segments WHEN OLD.position = 1 "
                "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END"
            )
        )

    with pytest.raises(TranscriptSaveError):
        TranscriptEditService(repository).save(
            before.id,
            1,
            {first.id: "לא יישמר 1", second.id: "לא יישמר 2"},
        )
    after = repository.get(before.id)
    assert after is not None
    assert after.transcript_revision == 1
    assert [item.text for item in after.transcript_segments] == [
        "טקסט ראשון",
        "טקסט שני",
    ]


def test_analysis_remains_stored_and_becomes_derived_outdated(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    before = create_transcript(repository)
    with session_factory() as session, session.begin():
        meeting = session.get(MeetingORM, before.id)
        assert meeting is not None
        analysis = MeetingAnalysisORM(
            provider="fixture",
            model="fixture",
            prompt_version="1",
            schema_version="1",
            source_transcript_revision=1,
            summary="סיכום קודם",
        )
        meeting.analyses.append(analysis)
        session.flush()
        meeting.current_analysis = analysis
        analysis_id = analysis.id
    current = repository.get(before.id)
    assert current is not None
    first, second = current.transcript_segments

    TranscriptEditService(repository).save(
        before.id, 1, {first.id: "תיקון", second.id: second.text}
    )
    after = repository.get(before.id)
    assert after is not None

    assert after.current_analysis_id == analysis_id
    assert after.current_analysis is not None
    assert after.current_analysis.source_transcript_revision == 1
    assert after.transcript_revision == 2
    assert derive_display_state(after) == MeetingDisplayState.ANALYSIS_OUTDATED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("transcription_status", TranscriptionStatus.RUNNING),
        ("analysis_operation_status", AnalysisOperationStatus.RUNNING),
    ],
)
def test_save_is_blocked_during_conflicting_operation(database, field, value) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    before = create_transcript(repository)
    repository.update(before.id, **{field: value})

    with pytest.raises(TranscriptSaveBlockedError):
        TranscriptEditService(repository).save(
            before.id,
            1,
            {item.id: item.text + " שינוי" for item in before.transcript_segments},
        )
