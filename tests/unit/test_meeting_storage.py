from pathlib import Path
from uuid import uuid4

import pytest

from sikumon.application.meeting_service import (
    MeetingDeletionBlockedError,
    default_meeting_title,
)
from sikumon.database.orm_models import MeetingORM
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus


def test_default_title_uses_trimmed_filename_stem() -> None:
    assert default_meeting_title(Path("weekly   planning.wav")) == "weekly planning"


def test_meeting_storage_paths_are_uuid_scoped(phase2_app) -> None:
    paths, _, storage, _ = phase2_app
    meeting_id = uuid4()

    assert storage.meeting_directory(meeting_id) == paths.meetings / str(meeting_id)
    assert storage.import_directory(meeting_id) == paths.meetings / ".imports" / str(meeting_id)
    assert storage.final_audio_path(meeting_id, ".wav") == (
        paths.meetings / str(meeting_id) / "source_audio.wav"
    )


@pytest.mark.parametrize(
    ("transcription_status", "analysis_status"),
    [
        (TranscriptionStatus.RUNNING, AnalysisOperationStatus.NOT_STARTED),
        (TranscriptionStatus.NOT_STARTED, AnalysisOperationStatus.RUNNING),
    ],
)
def test_deletion_is_guarded_for_running_operations(
    phase2_app,
    transcription_status: TranscriptionStatus,
    analysis_status: AnalysisOperationStatus,
) -> None:
    _, repository, _, service = phase2_app
    meeting = repository.create(
        MeetingORM(
            title="פעילה",
            original_filename="a.wav",
            audio_path="missing.wav",
            transcription_status=transcription_status,
            analysis_operation_status=analysis_status,
        )
    )

    with pytest.raises(MeetingDeletionBlockedError):
        service.delete_meeting(meeting.id)

    assert repository.get(meeting.id) is not None
