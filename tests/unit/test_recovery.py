from sikumon.application.startup_recovery import recover_stale_operations
from sikumon.database.orm_models import MeetingORM
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus


def test_recovery_normalizes_only_running_states(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    stale = repository.create(
        MeetingORM(
            title="פגישה שנקטעה",
            original_filename="meeting.wav",
            audio_path="C:/data/meeting.wav",
            transcription_status=TranscriptionStatus.RUNNING,
            analysis_operation_status=AnalysisOperationStatus.RUNNING,
        )
    )
    completed = repository.create(
        MeetingORM(
            title="פגישה תקינה",
            original_filename="done.wav",
            audio_path="C:/data/done.wav",
            transcription_status=TranscriptionStatus.COMPLETED,
            analysis_operation_status=AnalysisOperationStatus.COMPLETED,
        )
    )

    result = recover_stale_operations(session_factory)

    assert result.transcription_failures == 1
    assert result.analysis_failures == 1
    assert repository.get(stale.id).transcription_status == TranscriptionStatus.FAILED
    assert repository.get(stale.id).analysis_operation_status == AnalysisOperationStatus.FAILED
    assert repository.get(stale.id).transcript_revision == 0
    assert repository.get(stale.id).transcript_segments == []
    assert repository.get(completed.id).transcription_status == TranscriptionStatus.COMPLETED
