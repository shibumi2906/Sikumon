"""Safe, staged management of the required local Ivrit.ai model."""

from __future__ import annotations

import gc
import json
import logging
import os
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from sikumon.config.constants import (
    IVRIT_MODEL_ID,
    IVRIT_MODEL_REVISION,
    TRANSCRIPTION_COMPUTE_TYPE,
    TRANSCRIPTION_DEVICE,
)
from sikumon.storage.paths import ApplicationPaths

MODEL_DIRECTORY_NAME = "ivrit-whisper"
DOWNLOADS_DIRECTORY_NAME = ".downloads"
CANDIDATE_DIRECTORY_NAME = "ivrit-whisper-candidate"
CACHE_DIRECTORY_NAME = "huggingface-cache"
BACKUP_DIRECTORY_NAME = ".ivrit-whisper-previous"
MODEL_INFO_FILENAME = "model_info.json"
REQUIRED_MODEL_FILES = ("config.json", "model.bin", "tokenizer.json")


class ModelAvailability(StrEnum):
    MISSING = "MISSING"
    DOWNLOADING = "DOWNLOADING"
    VERIFYING = "VERIFYING"
    AVAILABLE = "AVAILABLE"
    FAILED = "FAILED"


class ModelManagementError(RuntimeError):
    def __init__(self, user_message: str, *, technical_message: str | None = None) -> None:
        super().__init__(technical_message or user_message)
        self.user_message = user_message


class ModelDownloadCancelled(ModelManagementError):
    def __init__(self) -> None:
        super().__init__("הורדת מודל התמלול בוטלה.")


class ModelVerificationError(ModelManagementError):
    def __init__(self, technical_message: str) -> None:
        super().__init__(
            "לא ניתן לאמת את מודל התמלול שהורד. אפשר לנסות להוריד אותו שוב.",
            technical_message=technical_message,
        )


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository_id: str
    requested_revision: str | None
    resolved_revision: str
    verified_at: datetime
    faster_whisper_version: str
    ctranslate2_version: str
    device: str
    compute_type: str


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    completed_files: int
    total_files: int
    current_file: str | None = None


@dataclass(frozen=True, slots=True)
class DownloadResult:
    resolved_revision: str
    file_count: int


@dataclass(frozen=True, slots=True)
class VerificationVersions:
    faster_whisper: str
    ctranslate2: str


ProgressCallback = Callable[[DownloadProgress], None]
StateCallback = Callable[[ModelAvailability], None]


class ModelDownloader(Protocol):
    def download(
        self,
        repository_id: str,
        revision: str | None,
        destination: Path,
        cache_directory: Path,
        cancellation: threading.Event,
        progress: ProgressCallback | None,
    ) -> DownloadResult: ...


class ModelVerifier(Protocol):
    def verify(self, model_directory: Path) -> VerificationVersions: ...


class HuggingFaceModelDownloader:
    """Use the official Hub cache, with cancellation between repository files."""

    def download(
        self,
        repository_id: str,
        revision: str | None,
        destination: Path,
        cache_directory: Path,
        cancellation: threading.Event,
        progress: ProgressCallback | None,
    ) -> DownloadResult:
        try:
            from huggingface_hub import HfApi, hf_hub_download
        except ImportError as error:
            raise ModelManagementError(
                "רכיב הורדת המודל אינו מותקן. יש להתקין מחדש את Sikumon.",
                technical_message="huggingface_hub is not installed",
            ) from error

        try:
            info = HfApi().model_info(repository_id, revision=revision, files_metadata=True)
            resolved_revision = str(info.sha or "")
            if not resolved_revision:
                raise ModelManagementError(
                    "לא ניתן לזהות את גרסת מודל התמלול להורדה.",
                    technical_message="Hugging Face returned no resolved model revision",
                )
            filenames = sorted(
                sibling.rfilename
                for sibling in (info.siblings or [])
                if sibling.rfilename and not sibling.rfilename.endswith("/")
            )
            if not filenames:
                raise ModelManagementError(
                    "מאגר מודל התמלול אינו מכיל קבצים להורדה.",
                    technical_message="Hugging Face model repository has no files",
                )
            destination.mkdir(parents=True, exist_ok=True)
            cache_directory.mkdir(parents=True, exist_ok=True)
            destination_root = destination.resolve()
            total = len(filenames)
            for index, filename in enumerate(filenames):
                if cancellation.is_set():
                    raise ModelDownloadCancelled
                target = (destination / filename).resolve()
                if destination_root not in target.parents:
                    raise ModelManagementError(
                        "מאגר מודל התמלול מכיל נתיב קובץ לא תקין.",
                        technical_message=f"Unsafe repository filename: {filename!r}",
                    )
                if progress is not None:
                    progress(DownloadProgress(index, total, filename))
                cached_file = hf_hub_download(
                    repo_id=repository_id,
                    filename=filename,
                    revision=resolved_revision,
                    cache_dir=cache_directory,
                )
                if cancellation.is_set():
                    raise ModelDownloadCancelled
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cached_file, target)
                if progress is not None:
                    progress(DownloadProgress(index + 1, total, filename))
            return DownloadResult(resolved_revision=resolved_revision, file_count=total)
        except ModelManagementError:
            raise
        except OSError as error:
            raise ModelManagementError(
                "לא ניתן לשמור את מודל התמלול. יש לבדוק מקום פנוי והרשאות כתיבה.",
                technical_message=f"Model download storage failure: {error}",
            ) from error
        except Exception as error:
            raise ModelManagementError(
                "הורדת מודל התמלול נכשלה. יש לבדוק את החיבור לאינטרנט ולנסות שוב.",
                technical_message=f"Hugging Face download failure: {type(error).__name__}: {error}",
            ) from error


class FasterWhisperModelVerifier:
    """Perform the required real local CPU/int8 construction check."""

    def verify(self, model_directory: Path) -> VerificationVersions:
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]

            model = WhisperModel(
                str(model_directory),
                device=TRANSCRIPTION_DEVICE,
                compute_type=TRANSCRIPTION_COMPUTE_TYPE,
            )
            del model
            gc.collect()
            return VerificationVersions(
                faster_whisper=_package_version("faster-whisper"),
                ctranslate2=_package_version("ctranslate2"),
            )
        except Exception as error:
            raise ModelVerificationError(
                "faster-whisper could not construct local model: "
                f"{type(error).__name__}: {error}"
            ) from error


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


class ModelManager:
    """Own model availability, staged download, verification, and recovery."""

    def __init__(
        self,
        paths: ApplicationPaths,
        downloader: ModelDownloader | None = None,
        verifier: ModelVerifier | None = None,
        logger: logging.Logger | None = None,
        *,
        repository_id: str = IVRIT_MODEL_ID,
        revision: str | None = IVRIT_MODEL_REVISION,
    ) -> None:
        self.repository_id = repository_id
        self.revision = revision
        self.model_directory = paths.models / MODEL_DIRECTORY_NAME
        self.downloads_directory = paths.models / DOWNLOADS_DIRECTORY_NAME
        self.candidate_directory = self.downloads_directory / CANDIDATE_DIRECTORY_NAME
        self.cache_directory = self.downloads_directory / CACHE_DIRECTORY_NAME
        self.backup_directory = paths.models / BACKUP_DIRECTORY_NAME
        self._downloader = downloader or HuggingFaceModelDownloader()
        self._verifier = verifier or FasterWhisperModelVerifier()
        self._logger = logger or logging.getLogger(__name__)
        self._state_lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._cancellation = threading.Event()
        self._availability = ModelAvailability.MISSING
        self._last_error: ModelManagementError | None = None
        self._initialize()

    @property
    def availability(self) -> ModelAvailability:
        with self._state_lock:
            return self._availability

    @property
    def last_error(self) -> ModelManagementError | None:
        with self._state_lock:
            return self._last_error

    def refresh(self) -> ModelAvailability:
        with self._state_lock:
            valid, reason, _ = self._lightweight_check(self.model_directory)
            if valid:
                self._availability = ModelAvailability.AVAILABLE
                self._last_error = None
            elif self.model_directory.exists():
                self._availability = ModelAvailability.FAILED
                self._last_error = ModelManagementError(
                    "מודל התמלול המקומי אינו תקין. אפשר להוריד אותו מחדש.",
                    technical_message=reason,
                )
            else:
                self._availability = ModelAvailability.MISSING
                self._last_error = None
            self._logger.info(
                "Model discovery state=%s repository=%s requested_revision=%s path=%s",
                self._availability,
                self.repository_id,
                self.revision or "UNRESOLVED",
                self.model_directory,
            )
            return self._availability

    def request_cancellation(self) -> None:
        self._cancellation.set()

    def normalize_unexpected_failure(self, error: Exception) -> ModelManagementError:
        """Restore a deterministic state if an exception escapes the worker operation."""

        try:
            self._discard_candidate()
        except OSError:
            self._logger.exception("Failed cleaning model candidate after worker failure")
        wrapped = ModelManagementError(
            "התקנת מודל התמלול נכשלה. אפשר לנסות שוב.",
            technical_message=f"Unexpected model worker failure: {type(error).__name__}: {error}",
        )
        self._last_error = wrapped
        fallback = (
            ModelAvailability.AVAILABLE
            if self._is_valid(self.model_directory)
            else ModelAvailability.FAILED
        )
        self._set_state(fallback, None)
        self._logger.exception("Unexpected model worker failure")
        return wrapped
        self._logger.info("Model download cancellation requested")

    def download_and_verify(
        self,
        *,
        state_callback: StateCallback | None = None,
        progress_callback: ProgressCallback | None = None,
        replace_existing: bool = False,
    ) -> ModelInfo:
        if not self._operation_lock.acquire(blocking=False):
            raise ModelManagementError("הורדת מודל כבר מתבצעת.")
        try:
            if self._is_valid(self.model_directory) and not replace_existing:
                marker = self._read_marker(self.model_directory)
                assert marker is not None
                self._set_state(ModelAvailability.AVAILABLE, state_callback)
                return marker

            self._last_error = None
            self._cancellation.clear()
            self._prepare_candidate()
            self._set_state(ModelAvailability.DOWNLOADING, state_callback)
            self._logger.info(
                "Model download started repository=%s requested_revision=%s",
                self.repository_id,
                self.revision or "UNRESOLVED",
            )
            result = self._downloader.download(
                self.repository_id,
                self.revision,
                self.candidate_directory,
                self.cache_directory,
                self._cancellation,
                progress_callback,
            )
            self._raise_if_cancelled()
            self._logger.info(
                "Model download completed files=%d resolved_revision=%s",
                result.file_count,
                result.resolved_revision,
            )
            self._validate_candidate_files()
            self._set_state(ModelAvailability.VERIFYING, state_callback)
            self._logger.info("Model verification started path=%s", self.candidate_directory)
            versions = self._verifier.verify(self.candidate_directory)
            self._raise_if_cancelled()
            marker = ModelInfo(
                repository_id=self.repository_id,
                requested_revision=self.revision,
                resolved_revision=result.resolved_revision,
                verified_at=datetime.now(UTC),
                faster_whisper_version=versions.faster_whisper,
                ctranslate2_version=versions.ctranslate2,
                device=TRANSCRIPTION_DEVICE,
                compute_type=TRANSCRIPTION_COMPUTE_TYPE,
            )
            self._write_marker(self.candidate_directory, marker)
            valid, reason, _ = self._lightweight_check(self.candidate_directory)
            if not valid:
                raise ModelVerificationError(reason)
            self._finalize_candidate()
            self._logger.info(
                "Model verification completed resolved_revision=%s final_path=%s",
                marker.resolved_revision,
                self.model_directory,
            )
            self._set_state(ModelAvailability.AVAILABLE, state_callback)
            return marker
        except ModelDownloadCancelled as error:
            self._discard_candidate()
            self._last_error = error
            fallback = (
                ModelAvailability.AVAILABLE
                if self._is_valid(self.model_directory)
                else ModelAvailability.MISSING
            )
            self._set_state(fallback, state_callback)
            self._logger.info("Model download cancelled")
            raise
        except ModelManagementError as error:
            self._discard_candidate()
            self._last_error = error
            self._set_state(ModelAvailability.FAILED, state_callback)
            self._logger.exception("Model management operation failed")
            raise
        except (OSError, ValidationError, ValueError) as error:
            self._discard_candidate()
            wrapped = ModelManagementError(
                "התקנת מודל התמלול נכשלה. אפשר לנסות שוב.",
                technical_message=f"Model management failure: {type(error).__name__}: {error}",
            )
            self._last_error = wrapped
            self._set_state(ModelAvailability.FAILED, state_callback)
            self._logger.exception("Model management operation failed")
            raise wrapped from error
        finally:
            self._operation_lock.release()

    def _initialize(self) -> None:
        try:
            self.downloads_directory.mkdir(parents=True, exist_ok=True)
            self._recover_interrupted_finalization()
            self.refresh()
        except OSError as error:
            self._availability = ModelAvailability.FAILED
            self._last_error = ModelManagementError(
                "לא ניתן לגשת לתיקיית מודל התמלול.",
                technical_message=f"Model directory initialization failure: {error}",
            )
            self._logger.exception("Model manager initialization failed")

    def _recover_interrupted_finalization(self) -> None:
        final_valid = self._is_valid(self.model_directory)
        backup_valid = self._is_valid(self.backup_directory)
        candidate_valid = self._is_valid(self.candidate_directory)
        if final_valid:
            self._remove_directory(self.backup_directory)
            self._discard_candidate()
            return
        if backup_valid:
            self._remove_directory(self.model_directory)
            os.replace(self.backup_directory, self.model_directory)
            self._discard_candidate()
            self._logger.info("Recovered verified model from interrupted finalization backup")
            return
        self._remove_directory(self.backup_directory)
        if candidate_valid:
            self._remove_directory(self.model_directory)
            os.replace(self.candidate_directory, self.model_directory)
            self._logger.info("Recovered verified candidate after interrupted finalization")
        else:
            self._discard_candidate()

    def _prepare_candidate(self) -> None:
        self.downloads_directory.mkdir(parents=True, exist_ok=True)
        self.cache_directory.mkdir(parents=True, exist_ok=True)
        self._discard_candidate()
        self.candidate_directory.mkdir(parents=True, exist_ok=False)

    def _validate_candidate_files(self) -> None:
        for filename in REQUIRED_MODEL_FILES:
            path = self.candidate_directory / filename
            try:
                with path.open("rb") as stream:
                    if not stream.read(1):
                        raise ModelVerificationError(f"Required model file is empty: {filename}")
            except FileNotFoundError as error:
                raise ModelVerificationError(f"Required model file is missing: {filename}") from error
            except OSError as error:
                raise ModelVerificationError(
                    f"Required model file is unreadable: {filename}: {error}"
                ) from error

    def _finalize_candidate(self) -> None:
        self._remove_directory(self.backup_directory)
        moved_existing = False
        if self.model_directory.exists():
            os.replace(self.model_directory, self.backup_directory)
            moved_existing = True
        try:
            os.replace(self.candidate_directory, self.model_directory)
        except OSError:
            if moved_existing and not self.model_directory.exists():
                os.replace(self.backup_directory, self.model_directory)
            raise
        self._remove_directory(self.backup_directory)

    def _lightweight_check(self, directory: Path) -> tuple[bool, str, ModelInfo | None]:
        if not directory.is_dir():
            return False, "Verified model directory is missing", None
        try:
            for filename in REQUIRED_MODEL_FILES:
                path = directory / filename
                if not path.is_file():
                    return False, f"Required model file is missing: {filename}", None
                with path.open("rb") as stream:
                    if not stream.read(1):
                        return False, f"Required model file is empty: {filename}", None
            marker = self._read_marker(directory)
            if marker is None:
                return False, "Verification marker is missing or invalid", None
            if marker.repository_id != self.repository_id:
                return False, "Verification marker repository does not match configuration", marker
            if marker.requested_revision != self.revision:
                return False, "Verification marker requested revision does not match configuration", marker
            if not marker.resolved_revision.strip():
                return False, "Verification marker has no resolved revision", marker
            if marker.device != TRANSCRIPTION_DEVICE:
                return False, "Verification marker device does not match configuration", marker
            if marker.compute_type != TRANSCRIPTION_COMPUTE_TYPE:
                return False, "Verification marker compute type does not match configuration", marker
            return True, "", marker
        except OSError as error:
            return False, f"Model files are unreadable: {error}", None

    def _is_valid(self, directory: Path) -> bool:
        return self._lightweight_check(directory)[0]

    def _read_marker(self, directory: Path) -> ModelInfo | None:
        try:
            return ModelInfo.model_validate_json(
                (directory / MODEL_INFO_FILENAME).read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError):
            return None

    def _write_marker(self, directory: Path, marker: ModelInfo) -> None:
        marker_path = directory / MODEL_INFO_FILENAME
        temporary_path = directory / f".{MODEL_INFO_FILENAME}.tmp"
        payload = json.dumps(marker.model_dump(mode="json"), ensure_ascii=False, indent=2)
        with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, marker_path)

    def _raise_if_cancelled(self) -> None:
        if self._cancellation.is_set():
            raise ModelDownloadCancelled

    def _discard_candidate(self) -> None:
        self._remove_directory(self.candidate_directory)

    @staticmethod
    def _remove_directory(path: Path) -> None:
        if path.exists():
            shutil.rmtree(path)

    def _set_state(
        self,
        state: ModelAvailability,
        callback: StateCallback | None,
    ) -> None:
        with self._state_lock:
            self._availability = state
        if callback is not None:
            callback(state)
