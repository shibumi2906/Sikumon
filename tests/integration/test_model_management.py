import threading
from pathlib import Path

import pytest

from sikumon.services.transcription.model_manager import (
    REQUIRED_MODEL_FILES,
    DownloadResult,
    ModelAvailability,
    ModelDownloadCancelled,
    ModelManager,
    ModelVerificationError,
    VerificationVersions,
)
from sikumon.storage.paths import ApplicationPaths


class SuccessfulDownloader:
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
        for filename in REQUIRED_MODEL_FILES:
            (destination / filename).write_bytes(b"model-data")
        return DownloadResult("resolved-commit", len(REQUIRED_MODEL_FILES))


class CancellingDownloader(SuccessfulDownloader):
    def download(self, *args, **kwargs) -> DownloadResult:
        raise ModelDownloadCancelled


class SuccessfulVerifier:
    def verify(self, model_directory: Path) -> VerificationVersions:
        return VerificationVersions("1.2.3", "4.5.6")


def make_paths(tmp_path: Path) -> ApplicationPaths:
    paths = ApplicationPaths.resolve(tmp_path / "data")
    paths.ensure_directories()
    return paths


def test_mocked_install_finalizes_and_is_reused_after_restart(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    manager = ModelManager(paths, SuccessfulDownloader(), SuccessfulVerifier())
    manager.download_and_verify()

    restarted = ModelManager(paths, SuccessfulDownloader(), SuccessfulVerifier())

    assert restarted.availability == ModelAvailability.AVAILABLE
    assert restarted.model_directory == paths.models / "ivrit-whisper"


def test_cancel_then_retry_and_failed_verification_do_not_false_install(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    manager = ModelManager(paths, CancellingDownloader(), SuccessfulVerifier())
    with pytest.raises(ModelDownloadCancelled):
        manager.download_and_verify()
    manager._downloader = SuccessfulDownloader()
    manager.download_and_verify()
    assert manager.availability == ModelAvailability.AVAILABLE

    replacement = ModelManager(paths, SuccessfulDownloader(), SuccessfulVerifier())
    replacement._verifier = type(
        "BadVerifier",
        (),
        {"verify": lambda self, model_directory: (_ for _ in ()).throw(
            ModelVerificationError("bad candidate")
        )},
    )()
    with pytest.raises(ModelVerificationError):
        replacement.download_and_verify(replace_existing=True)
    assert ModelManager(paths, SuccessfulDownloader(), SuccessfulVerifier()).availability == (
        ModelAvailability.AVAILABLE
    )
