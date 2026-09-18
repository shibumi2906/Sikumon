from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError

from sikumon.application.meeting_service import MeetingImportError


def test_valid_wav_import_persists_authoritative_local_copy(phase2_app, make_wav) -> None:
    paths, repository, _, service = phase2_app
    source = make_wav("ישיבת צוות.wav", 0.3)

    imported = service.import_meeting(source, "ישיבת צוות")
    source.rename(source.with_suffix(".moved"))
    reloaded = repository.get(imported.id)

    expected_directory = paths.meetings / imported.id
    assert reloaded is not None
    assert reloaded.original_filename == "ישיבת צוות.wav"
    assert reloaded.audio_duration_seconds == pytest.approx(0.3, abs=0.02)
    assert Path(reloaded.audio_path) == expected_directory / "source_audio.wav"
    assert Path(reloaded.audio_path).is_file()
    assert not (paths.meetings / ".imports" / imported.id).exists()


@pytest.mark.parametrize("extension", ["mp3", "m4a", "flac"])
def test_supported_compressed_media_imports_when_ffmpeg_is_available(
    phase2_app, make_wav, tmp_path: Path, extension: str
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe are unavailable")
    source_wav = make_wav("source.wav", 0.2)
    compressed = tmp_path / f"recording.{extension}"
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(source_wav), str(compressed)],
        check=True,
        capture_output=True,
    )
    _, repository, _, service = phase2_app

    imported = service.import_meeting(compressed, f"בדיקת {extension}")
    reloaded = repository.get(imported.id)

    assert reloaded is not None
    assert Path(reloaded.audio_path).suffix == f".{extension}"
    assert Path(reloaded.audio_path).is_file()
    assert reloaded.audio_duration_seconds is not None
    assert reloaded.audio_duration_seconds > 0


def test_failed_copy_leaves_no_database_record_or_completed_directory(
    phase2_app, make_wav, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, repository, storage, service = phase2_app
    source = make_wav()

    def fail_copy(source: Path, meeting_id: object, extension: str) -> Path:
        raise OSError("simulated copy failure")

    monkeypatch.setattr(storage, "copy_to_staging", fail_copy)

    with pytest.raises(MeetingImportError):
        service.import_meeting(source, "כישלון")

    assert not repository.list()
    assert not [item for item in paths.meetings.iterdir() if item.name != ".imports"]


def test_database_failure_after_staging_compensates_all_import_artifacts(
    phase2_app, make_wav, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, repository, _, service = phase2_app
    source = make_wav("db-failure.wav")

    def fail_create(meeting: object) -> object:
        raise SQLAlchemyError("simulated database failure")

    monkeypatch.setattr(repository, "create", fail_create)

    with pytest.raises(MeetingImportError):
        service.import_meeting(source, "כשל מסד")

    assert not repository.list()
    imports_root = paths.meetings / ".imports"
    assert not imports_root.exists() or not tuple(imports_root.iterdir())
    assert not [item for item in paths.meetings.iterdir() if item.name != ".imports"]
