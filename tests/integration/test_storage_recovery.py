from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID, uuid4

from sikumon.application.meeting_service import MeetingDisplayState
from sikumon.application.startup_recovery import recover_meeting_storage
from sikumon.database.orm_models import MeetingAnalysisORM, MeetingORM
from sikumon.domain.enums import AnalysisOperationStatus
from sikumon.domain.transcript import TranscriptSegmentDraft
from sikumon.services.audio.metadata import AudioMetadataService


def test_committed_meeting_recovers_matching_staged_audio(phase2_app, make_wav) -> None:
    _, repository, storage, _ = phase2_app
    metadata_service = AudioMetadataService()
    source = make_wav()
    metadata = metadata_service.inspect(source)
    meeting_id = uuid4()
    staged_audio = storage.copy_to_staging(source, meeting_id, metadata.normalized_extension)
    final_audio = storage.final_audio_path(meeting_id, metadata.normalized_extension)
    repository.create(
        MeetingORM(
            id=str(meeting_id),
            title="התחייבה לפני שינוי שם",
            original_filename=source.name,
            audio_path=str(final_audio),
            audio_duration_seconds=metadata.duration_seconds,
        )
    )

    result = recover_meeting_storage(repository, storage, metadata_service)

    assert result.finalized_imports == 1
    assert not staged_audio.exists()
    assert final_audio.is_file()
    assert repository.get(str(meeting_id)) is not None


def test_uncommitted_staged_import_is_removed(phase2_app, make_wav) -> None:
    _, repository, storage, _ = phase2_app
    empty_id = uuid4()
    partial_id = uuid4()
    completed_id = uuid4()
    storage.prepare_import(empty_id)
    partial = storage.prepare_import(partial_id) / "source_audio.wav"
    partial.write_bytes(b"partial")
    storage.copy_to_staging(make_wav(), completed_id, ".wav")

    result = recover_meeting_storage(repository, storage, AudioMetadataService())

    assert result.removed_incomplete_imports == 3
    for meeting_id in (empty_id, partial_id, completed_id):
        assert not storage.import_directory(meeting_id).exists()
    assert not repository.list()


def test_valid_finalized_meeting_is_preserved_and_redundant_stage_is_removed(
    phase2_app, make_wav
) -> None:
    _, repository, storage, service = phase2_app
    imported = service.import_meeting(make_wav(), "תקינה")
    meeting_id = UUID(imported.id)
    final_audio = Path(imported.audio_path)
    staging = storage.prepare_import(meeting_id)
    shutil.copy2(final_audio, staging / final_audio.name)

    result = recover_meeting_storage(repository, storage, AudioMetadataService())

    assert result.removed_incomplete_imports == 1
    assert final_audio.is_file()
    assert not staging.exists()
    assert repository.get(imported.id) is not None


def test_finalized_uuid_orphan_without_database_row_is_removed(
    phase2_app, make_wav
) -> None:
    paths, repository, storage, _ = phase2_app
    meeting_id = uuid4()
    directory = storage.meeting_directory(meeting_id)
    directory.mkdir(parents=True)
    shutil.copy2(make_wav(), directory / "source_audio.wav")
    unrelated = paths.meetings / "manual-notes"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("not Sikumon meeting storage", encoding="utf-8")

    result = recover_meeting_storage(repository, storage, AudioMetadataService())

    assert result.removed_orphan_directories == 1
    assert not directory.exists()
    assert unrelated.is_dir()


def test_db_deleted_meeting_leftover_is_removed_on_startup(phase2_app, make_wav) -> None:
    _, repository, storage, service = phase2_app
    imported = service.import_meeting(make_wav(), "נמחקה")
    directory = storage.meeting_directory(imported.id)
    assert repository.delete(imported.id)
    assert directory.is_dir()

    result = recover_meeting_storage(repository, storage, AudioMetadataService())

    assert result.removed_orphan_directories == 1
    assert not directory.exists()
    assert repository.get(imported.id) is None


def test_missing_audio_meeting_remains_visible_with_warning_state(phase2_app) -> None:
    paths, repository, storage, service = phase2_app
    meeting_id = uuid4()
    missing_audio = paths.meetings / str(meeting_id) / "source_audio.wav"
    meeting = repository.create(
        MeetingORM(
            id=str(meeting_id),
            title="הקלטה חסרה",
            original_filename="missing.wav",
            audio_path=str(missing_audio),
            audio_duration_seconds=10.0,
        )
    )
    repository.replace_transcript(
        meeting.id,
        (TranscriptSegmentDraft(uuid4(), 0, 0, 1_000, "תמלול שנשמר"),),
    )
    with repository._session_factory() as session, session.begin():
        stored = session.get(MeetingORM, meeting.id)
        assert stored is not None
        analysis = MeetingAnalysisORM(
            meeting_id=stored.id,
            provider="openai",
            model="test-model",
            prompt_version="1",
            schema_version="1",
            source_transcript_revision=1,
            summary="סיכום שנשמר",
        )
        stored.analyses.append(analysis)
        stored.current_analysis = analysis
        stored.analysis_operation_status = AnalysisOperationStatus.COMPLETED

    recover_meeting_storage(repository, storage, AudioMetadataService())
    details = service.get_meeting(str(meeting_id))
    listed = service.list_meetings()

    assert details is not None
    assert not details.audio_exists
    assert details.display_state == MeetingDisplayState.AUDIO_MISSING
    assert listed[0].display_state == MeetingDisplayState.AUDIO_MISSING
    assert repository.get(str(meeting_id)) is not None
    assert [segment.text for segment in details.transcript_segments] == ["תמלול שנשמר"]
    assert details.analysis is not None
    assert details.analysis.summary == "סיכום שנשמר"
