import shutil
from pathlib import Path

import pytest


def test_deletion_removes_database_and_meeting_owned_files(phase2_app, make_wav) -> None:
    paths, repository, storage, service = phase2_app
    first = service.import_meeting(make_wav("first.wav"), "ראשונה")
    second_source = make_wav("second.wav")
    second = service.import_meeting(second_source, "שנייה")
    cache = storage.meeting_cache_directory(first.id)
    cache.mkdir(parents=True)
    (cache / "artifact.tmp").write_bytes(b"cache")

    result = service.delete_meeting(first.id)

    assert not result.undeleted_paths
    assert repository.get(first.id) is None
    assert not (paths.meetings / first.id).exists()
    assert not cache.exists()
    assert repository.get(second.id) is not None
    assert Path(repository.get(second.id).audio_path).is_file()


def test_deletion_succeeds_when_meeting_directory_is_already_missing(
    phase2_app, make_wav
) -> None:
    _, repository, storage, service = phase2_app
    imported = service.import_meeting(make_wav(), "ללא תיקייה")
    storage.delete_meeting_files(imported.id)

    result = service.delete_meeting(imported.id)

    assert not result.undeleted_paths
    assert repository.get(imported.id) is None


def test_filesystem_deletion_failure_does_not_prevent_database_cleanup(
    phase2_app, make_wav, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, repository, _, service = phase2_app
    imported = service.import_meeting(make_wav(), "קבצים נעולים")
    meeting_directory = paths.meetings / imported.id
    real_rmtree = shutil.rmtree

    def fail_meeting_only(path: str | Path, *args: object, **kwargs: object) -> None:
        if Path(path) == meeting_directory:
            raise PermissionError("simulated locked recording")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", fail_meeting_only)

    result = service.delete_meeting(imported.id)

    assert repository.get(imported.id) is None
    assert result.undeleted_paths == (meeting_directory,)
    assert meeting_directory.is_dir()
