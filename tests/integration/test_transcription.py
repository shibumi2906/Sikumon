from __future__ import annotations

import threading
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

from sikumon.application.transcription_service import (
    AudioMissingForTranscription,
    ModelUnavailableForTranscription,
    TranscriptionAlreadyRunning,
    TranscriptionOperationError,
    TranscriptionService,
)
from sikumon.domain.enums import TranscriptionStatus
from sikumon.services.transcription.faster_whisper_ivrit import (
    TranscriptionCancelled,
    TranscriptionProviderError,
)
from sikumon.services.transcription.model_manager import ModelAvailability
from sikumon.services.transcription.provider import ProviderProgress, ProviderSegment


class FakeModelManager:
    def __init__(self, availability: ModelAvailability = ModelAvailability.AVAILABLE) -> None:
        self.availability = availability


class FakeProvider:
    def __init__(
        self,
        segments: tuple[ProviderSegment, ...] = (
            ProviderSegment(2_000, 4_000, "בוקר טוב"),
            ProviderSegment(5_000, 8_000, "מתחילים את הפגישה"),
        ),
        error: Exception | None = None,
    ) -> None:
        self.segments = segments
        self.error = error

    def transcribe(self, audio_path: Path, cancellation, progress_callback=None):
        if self.error is not None:
            raise self.error
        if cancellation.is_set():
            raise TranscriptionCancelled
        if progress_callback is not None:
            for segment in self.segments:
                progress_callback(ProviderProgress(segment.end_time_ms))
        return self.segments


def create_service(phase2_app, provider=None, availability=ModelAvailability.AVAILABLE):
    _, repository, _, _ = phase2_app
    return TranscriptionService(
        repository,
        FakeModelManager(availability),
        provider or FakeProvider(),
    )


def test_success_persists_order_ids_timestamps_status_and_revision(
    phase2_app, make_wav
) -> None:
    _, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("hebrew.wav", 10), "עברית")
    service = create_service(phase2_app)
    prepared = service.prepare(meeting.id)

    assert repository.get(meeting.id).transcription_status == TranscriptionStatus.RUNNING
    result = service.execute(prepared, threading.Event())
    reloaded = repository.get(meeting.id)

    assert result.transcript_revision == 1
    assert reloaded.transcription_status == TranscriptionStatus.COMPLETED
    assert reloaded.transcript_revision == 1
    assert reloaded.transcript_created_at is not None
    assert reloaded.transcript_updated_at is not None
    assert [item.position for item in reloaded.transcript_segments] == [0, 1]
    assert [item.start_time_ms for item in reloaded.transcript_segments] == [2_000, 5_000]
    ids = [item.id for item in reloaded.transcript_segments]
    assert len(set(ids)) == 2
    assert [item.id for item in repository.get(meeting.id).transcript_segments] == ids


def test_successful_replacement_increments_once_and_preserves_created_at(
    phase2_app, make_wav
) -> None:
    _, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("replace.wav"), "החלפה")
    first = create_service(phase2_app)
    first.execute(first.prepare(meeting.id), threading.Event())
    before = repository.get(meeting.id)
    old_ids = [segment.id for segment in before.transcript_segments]

    second = create_service(
        phase2_app, FakeProvider((ProviderSegment(0, 1_000, "תמלול חדש"),))
    )
    second.execute(second.prepare(meeting.id), threading.Event())
    after = repository.get(meeting.id)

    assert after.transcript_revision == 2
    assert after.transcript_created_at == before.transcript_created_at
    assert after.transcript_updated_at >= before.transcript_updated_at
    assert [segment.text for segment in after.transcript_segments] == ["תמלול חדש"]
    assert [segment.id for segment in after.transcript_segments] != old_ids


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (TranscriptionProviderError("כשל"), TranscriptionStatus.FAILED),
        (TranscriptionCancelled(), TranscriptionStatus.COMPLETED),
    ],
)
def test_failed_or_cancelled_replacement_preserves_previous_transcript_and_revision(
    phase2_app, make_wav, error: Exception, expected_status: TranscriptionStatus
) -> None:
    _, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("preserve.wav"), "שימור")
    first = create_service(phase2_app)
    first.execute(first.prepare(meeting.id), threading.Event())
    before = repository.get(meeting.id)
    snapshot = [(item.id, item.text) for item in before.transcript_segments]
    replacement = create_service(phase2_app, FakeProvider(error=error))

    with pytest.raises(type(error)):
        replacement.execute(replacement.prepare(meeting.id), threading.Event())
    after = repository.get(meeting.id)

    assert after.transcript_revision == 1
    assert [(item.id, item.text) for item in after.transcript_segments] == snapshot
    assert after.transcription_status == expected_status


def test_cancel_without_previous_transcript_returns_to_not_started(
    phase2_app, make_wav
) -> None:
    _, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("cancel.wav"), "ביטול")
    service = create_service(phase2_app, FakeProvider(error=TranscriptionCancelled()))

    with pytest.raises(TranscriptionCancelled):
        service.execute(service.prepare(meeting.id), threading.Event())

    reloaded = repository.get(meeting.id)
    assert reloaded.transcription_status == TranscriptionStatus.NOT_STARTED
    assert reloaded.transcript_revision == 0
    assert reloaded.transcript_segments == []


def test_guards_model_audio_and_duplicate_start(phase2_app, make_wav) -> None:
    paths, _, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("guards.wav"), "בדיקות")
    unavailable = create_service(phase2_app, availability=ModelAvailability.MISSING)
    with pytest.raises(ModelUnavailableForTranscription):
        unavailable.prepare(meeting.id)

    Path(meeting.audio_path).unlink()
    with pytest.raises(AudioMissingForTranscription):
        create_service(phase2_app).prepare(meeting.id)

    restored = paths.meetings / meeting.id / "source_audio.wav"
    restored.write_bytes(b"audio")
    repository_meeting = phase2_app[1].get(meeting.id)
    repository_meeting.audio_path = str(restored)
    phase2_app[1].save(repository_meeting)
    service = create_service(phase2_app)
    prepared = service.prepare(meeting.id)
    with pytest.raises(TranscriptionAlreadyRunning):
        service.prepare(meeting.id)
    service.abort_prepared(prepared)


def test_database_failure_rolls_back_replacement_and_revision(
    phase2_app, make_wav, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("db.wav"), "מסד")
    service = create_service(phase2_app)
    service.execute(service.prepare(meeting.id), threading.Event())
    before = repository.get(meeting.id)
    snapshot = [(item.id, item.text) for item in before.transcript_segments]

    def fail_replace(*args, **kwargs):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(repository, "replace_transcript", fail_replace)
    replacement = create_service(
        phase2_app, FakeProvider((ProviderSegment(0, 1_000, "לא יישמר"),))
    )
    with pytest.raises(TranscriptionOperationError):
        replacement.execute(replacement.prepare(meeting.id), threading.Event())

    after = repository.get(meeting.id)
    assert after.transcript_revision == 1
    assert [(item.id, item.text) for item in after.transcript_segments] == snapshot
    assert after.transcription_status == TranscriptionStatus.FAILED
