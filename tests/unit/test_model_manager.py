from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sikumon.config.constants import IVRIT_MODEL_REVISION
from sikumon.services.transcription.model_manager import (
    MODEL_INFO_FILENAME,
    REQUIRED_MODEL_FILES,
    DownloadProgress,
    DownloadResult,
    ModelAvailability,
    ModelDownloadCancelled,
    ModelInfo,
    ModelManagementError,
    ModelManager,
    ModelVerificationError,
    VerificationVersions,
)
from sikumon.storage.paths import ApplicationPaths


class SuccessfulDownloader:
    def __init__(self, resolved_revision: str = "resolved-commit") -> None:
        self.resolved_revision = resolved_revision
        self.calls = 0

    def download(
        self,
        repository_id: str,
        revision: str | None,
        destination: Path,
        cache_directory: Path,
        cancellation: threading.Event,
        progress,
    ) -> DownloadResult:
        self.calls += 1
        for filename in REQUIRED_MODEL_FILES:
            path = destination / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"model-data")
        if progress is not None:
            progress(DownloadProgress(3, 3, REQUIRED_MODEL_FILES[-1]))
        return DownloadResult(self.resolved_revision, 3)


class SuccessfulVerifier:
    def verify(self, model_directory: Path) -> VerificationVersions:
        assert all((model_directory / name).is_file() for name in REQUIRED_MODEL_FILES)
        return VerificationVersions("1.2.3", "4.5.6")


class FailingDownloader(SuccessfulDownloader):
    def download(self, *args, **kwargs) -> DownloadResult:
        raise ModelManagementError("שגיאת הורדה לבדיקה", technical_message="network down")


class CancellingDownloader(SuccessfulDownloader):
    def download(
        self,
        repository_id: str,
        revision: str | None,
        destination: Path,
        cache_directory: Path,
        cancellation: threading.Event,
        progress,
    ) -> DownloadResult:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / REQUIRED_MODEL_FILES[0]).write_bytes(b"partial")
        raise ModelDownloadCancelled


class FailingVerifier:
    def verify(self, model_directory: Path) -> VerificationVersions:
        raise ModelVerificationError("construction failed")


def make_paths(tmp_path: Path) -> ApplicationPaths:
    paths = ApplicationPaths.resolve(tmp_path / "data")
    paths.ensure_directories()
    return paths


def install_marker(
    directory: Path,
    *,
    repository_id: str = "ivrit-ai/whisper-large-v3-turbo-ct2",
    requested_revision: str | None = IVRIT_MODEL_REVISION,
    resolved_revision: str = "resolved-commit",
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename in REQUIRED_MODEL_FILES:
        (directory / filename).write_bytes(b"model-data")
    marker = ModelInfo(
        repository_id=repository_id,
        requested_revision=requested_revision,
        resolved_revision=resolved_revision,
        verified_at=datetime.now(UTC),
        faster_whisper_version="1.2.3",
        ctranslate2_version="4.5.6",
        device="cpu",
        compute_type="int8",
    )
    (directory / MODEL_INFO_FILENAME).write_text(
        json.dumps(marker.model_dump(mode="json")), encoding="utf-8"
    )


def test_initial_state_is_missing(tmp_path: Path) -> None:
    manager = ModelManager(make_paths(tmp_path), SuccessfulDownloader(), SuccessfulVerifier())

    assert manager.availability == ModelAvailability.MISSING


def test_verified_model_is_detected_without_expensive_verification(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    install_marker(paths.models / "ivrit-whisper")

    class MustNotRunVerifier:
        def verify(self, model_directory: Path) -> VerificationVersions:
            raise AssertionError("startup must remain lightweight")

    manager = ModelManager(paths, SuccessfulDownloader(), MustNotRunVerifier())

    assert manager.availability == ModelAvailability.AVAILABLE


@pytest.mark.parametrize("defect", ["missing-file", "missing-marker", "invalid-marker"])
def test_incomplete_or_invalid_install_is_not_available(tmp_path: Path, defect: str) -> None:
    paths = make_paths(tmp_path)
    directory = paths.models / "ivrit-whisper"
    install_marker(directory)
    if defect == "missing-file":
        (directory / REQUIRED_MODEL_FILES[0]).unlink()
    elif defect == "missing-marker":
        (directory / MODEL_INFO_FILENAME).unlink()
    else:
        (directory / MODEL_INFO_FILENAME).write_text("not-json", encoding="utf-8")

    manager = ModelManager(paths, SuccessfulDownloader(), SuccessfulVerifier())

    assert manager.availability == ModelAvailability.FAILED


def test_successful_state_transitions_and_marker_persistence(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    manager = ModelManager(paths, SuccessfulDownloader(), SuccessfulVerifier())
    states: list[ModelAvailability] = []

    marker = manager.download_and_verify(state_callback=states.append)

    assert states == [
        ModelAvailability.DOWNLOADING,
        ModelAvailability.VERIFYING,
        ModelAvailability.AVAILABLE,
    ]
    assert manager.availability == ModelAvailability.AVAILABLE
    assert marker.resolved_revision == "resolved-commit"
    assert (manager.model_directory / MODEL_INFO_FILENAME).is_file()
    assert not manager.candidate_directory.exists()


def test_download_and_verification_failures_are_failed(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    download_failure = ModelManager(paths, FailingDownloader(), SuccessfulVerifier())
    with pytest.raises(ModelManagementError):
        download_failure.download_and_verify()
    assert download_failure.availability == ModelAvailability.FAILED

    verification_failure = ModelManager(paths, SuccessfulDownloader(), FailingVerifier())
    with pytest.raises(ModelVerificationError):
        verification_failure.download_and_verify()
    assert verification_failure.availability == ModelAvailability.FAILED
    assert not verification_failure.model_directory.exists()


def test_cancellation_never_installs_partial_candidate(tmp_path: Path) -> None:
    manager = ModelManager(make_paths(tmp_path), CancellingDownloader(), SuccessfulVerifier())

    with pytest.raises(ModelDownloadCancelled):
        manager.download_and_verify()

    assert manager.availability == ModelAvailability.MISSING
    assert not manager.model_directory.exists()
    assert not manager.candidate_directory.exists()


def test_retry_after_failure_succeeds(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    manager = ModelManager(paths, FailingDownloader(), SuccessfulVerifier())
    with pytest.raises(ModelManagementError):
        manager.download_and_verify()
    manager._downloader = SuccessfulDownloader()

    manager.download_and_verify()

    assert manager.availability == ModelAvailability.AVAILABLE


def test_failed_replacement_preserves_existing_verified_model(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    final_directory = paths.models / "ivrit-whisper"
    install_marker(final_directory, resolved_revision="old-good")
    original = (final_directory / MODEL_INFO_FILENAME).read_bytes()
    manager = ModelManager(paths, SuccessfulDownloader("new-bad"), FailingVerifier())

    with pytest.raises(ModelVerificationError):
        manager.download_and_verify(replace_existing=True)

    assert (final_directory / MODEL_INFO_FILENAME).read_bytes() == original
    restarted = ModelManager(paths, SuccessfulDownloader(), SuccessfulVerifier())
    assert restarted.availability == ModelAvailability.AVAILABLE


@pytest.mark.parametrize(
    ("repository_id", "requested_revision"),
    [("another/repository", None), ("ivrit-ai/whisper-large-v3-turbo-ct2", "wrong")],
)
def test_repository_or_revision_mismatch_is_detected(
    tmp_path: Path, repository_id: str, requested_revision: str | None
) -> None:
    paths = make_paths(tmp_path)
    install_marker(
        paths.models / "ivrit-whisper",
        repository_id=repository_id,
        requested_revision=requested_revision,
    )

    manager = ModelManager(paths, SuccessfulDownloader(), SuccessfulVerifier())

    assert manager.availability == ModelAvailability.FAILED


def test_interrupted_unverified_candidate_is_cleaned_but_cache_is_reused(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    candidate = paths.models / ".downloads" / "ivrit-whisper-candidate"
    cache_file = paths.models / ".downloads" / "huggingface-cache" / "cached-piece"
    candidate.mkdir(parents=True)
    (candidate / "model.bin").write_bytes(b"partial")
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"complete-cache-piece")

    manager = ModelManager(paths, SuccessfulDownloader(), SuccessfulVerifier())

    assert manager.availability == ModelAvailability.MISSING
    assert not candidate.exists()
    assert cache_file.is_file()
