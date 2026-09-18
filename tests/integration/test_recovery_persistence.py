from sikumon.application.startup_recovery import recover_stale_operations
from sikumon.database.orm_models import MeetingORM, TranscriptSegmentORM
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus


def test_startup_recovery_changes_are_committed(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = repository.create(
        MeetingORM(
            title="נקטעה",
            original_filename="a.wav",
            audio_path="a.wav",
            transcription_status=TranscriptionStatus.RUNNING,
            analysis_operation_status=AnalysisOperationStatus.RUNNING,
        )
    )
    with session_factory() as session, session.begin():
        stored = session.get(MeetingORM, meeting.id)
        assert stored is not None
        stored.transcript_segments.append(
            TranscriptSegmentORM(
                position=0,
                start_time_ms=0,
                end_time_ms=1_000,
                text="תמלול קודם",
            )
        )
        stored.transcript_revision = 1
    recover_stale_operations(session_factory)

    fresh_repository = MeetingRepository(session_factory)
    loaded = fresh_repository.get(meeting.id)
    assert loaded.transcription_status == TranscriptionStatus.FAILED
    assert loaded.analysis_operation_status == AnalysisOperationStatus.FAILED
    assert loaded.transcript_revision == 1
    assert [segment.text for segment in loaded.transcript_segments] == ["תמלול קודם"]
