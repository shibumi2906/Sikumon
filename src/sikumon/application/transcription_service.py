"""Transactional orchestration for local meeting transcription."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from sikumon.config.constants import (
    IVRIT_MODEL_ID,
    IVRIT_MODEL_REVISION,
    TRANSCRIPTION_COMPUTE_TYPE,
)
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import TranscriptionStatus
from sikumon.domain.transcript import TranscriptSegmentDraft
from sikumon.services.transcription.faster_whisper_ivrit import (
    EmptyTranscriptionError,
    TranscriptionCancelled,
    TranscriptionProviderError,
)
from sikumon.services.transcription.model_manager import ModelAvailability, ModelManager
from sikumon.services.transcription.provider import (
    ProviderProgress,
    ProviderSegment,
    TranscriptionProvider,
)


class TranscriptionOperationError(RuntimeError):
    def __init__(self, user_message: str, *, technical_message: str | None = None) -> None:
        super().__init__(technical_message or user_message)
        self.user_message = user_message


class MeetingNotFoundForTranscription(TranscriptionOperationError):
    def __init__(self) -> None:
        super().__init__("הפגישה לא נמצאה.")


class AudioMissingForTranscription(TranscriptionOperationError):
    def __init__(self) -> None:
        super().__init__("קובץ ההקלטה המקומי חסר. לא ניתן להתחיל תמלול.")


class ModelUnavailableForTranscription(TranscriptionOperationError):
    def __init__(self) -> None:
        super().__init__("מודל התמלול אינו זמין. אפשר להתקין או לתקן אותו בהגדרות.")


class TranscriptionAlreadyRunning(TranscriptionOperationError):
    def __init__(self) -> None:
        super().__init__("תמלול אחר כבר מתבצע. יש להמתין לסיומו או לבטל אותו.")


@dataclass(frozen=True, slots=True)
class PreparedTranscription:
    meeting_id: str
    audio_path: Path
    audio_duration_seconds: float | None
    had_previous_transcript: bool


@dataclass(frozen=True, slots=True)
class TranscriptionProgress:
    processed_time_ms: int
    audio_duration_ms: int | None
    estimated_percent: int | None


@dataclass(frozen=True, slots=True)
class CompletedTranscription:
    meeting_id: str
    segment_count: int
    transcript_revision: int
    duration_seconds: float


ProgressCallback = Callable[[TranscriptionProgress], None]


def calculate_transcription_progress(
    processed_time_ms: int, audio_duration_seconds: float | None
) -> TranscriptionProgress:
    processed = max(0, processed_time_ms)
    if audio_duration_seconds is None or audio_duration_seconds <= 0:
        return TranscriptionProgress(processed, None, None)
    duration_ms = max(1, round(audio_duration_seconds * 1000))
    estimated = min(100, max(0, round(processed / duration_ms * 100)))
    return TranscriptionProgress(processed, duration_ms, estimated)


def build_transcript_drafts(
    segments: tuple[ProviderSegment, ...],
) -> tuple[TranscriptSegmentDraft, ...]:
    drafts: list[TranscriptSegmentDraft] = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if segment.start_time_ms < 0 or segment.end_time_ms < segment.start_time_ms:
            raise TranscriptionOperationError(
                "התקבלו חותמות זמן לא תקינות ממנוע התמלול."
            )
        drafts.append(
            TranscriptSegmentDraft(
                id=uuid4(),
                position=len(drafts),
                start_time_ms=segment.start_time_ms,
                end_time_ms=segment.end_time_ms,
                text=text,
            )
        )
    if not drafts:
        raise EmptyTranscriptionError
    return tuple(drafts)


class TranscriptionService:
    """Reserve quickly on the UI thread, then execute provider work in a worker."""

    def __init__(
        self,
        repository: MeetingRepository,
        model_manager: ModelManager,
        provider: TranscriptionProvider,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repository = repository
        self._model_manager = model_manager
        self._provider = provider
        self._logger = logger or logging.getLogger("sikumon.application.transcription")
        self._active_lock = threading.Lock()
        self._active_meeting_id: str | None = None

    @property
    def active_meeting_id(self) -> str | None:
        with self._active_lock:
            return self._active_meeting_id

    def prepare(self, meeting_id: str) -> PreparedTranscription:
        with self._active_lock:
            if self._active_meeting_id is not None:
                raise TranscriptionAlreadyRunning
            meeting = self._repository.get(meeting_id)
            if meeting is None:
                raise MeetingNotFoundForTranscription
            audio_path = Path(meeting.audio_path)
            if not audio_path.is_file():
                raise AudioMissingForTranscription
            if self._model_manager.availability != ModelAvailability.AVAILABLE:
                raise ModelUnavailableForTranscription
            if meeting.transcription_status == TranscriptionStatus.RUNNING:
                raise TranscriptionAlreadyRunning
            try:
                if not self._repository.begin_transcription(meeting_id):
                    raise TranscriptionAlreadyRunning
            except KeyError as error:
                raise MeetingNotFoundForTranscription from error
            except SQLAlchemyError as error:
                raise TranscriptionOperationError(
                    "לא ניתן להתחיל את התמלול. אפשר לנסות שוב.",
                    technical_message=f"Failed reserving transcription: {error}",
                ) from error
            self._active_meeting_id = meeting_id
            prepared = PreparedTranscription(
                meeting_id=meeting_id,
                audio_path=audio_path,
                audio_duration_seconds=meeting.audio_duration_seconds,
                had_previous_transcript=(
                    meeting.transcript_revision > 0 and bool(meeting.transcript_segments)
                ),
            )
        self._logger.info(
            "Transcription started meeting_id=%s audio_duration=%s model_id=%s "
            "model_revision=%s compute_type=%s",
            meeting_id,
            prepared.audio_duration_seconds,
            IVRIT_MODEL_ID,
            IVRIT_MODEL_REVISION or "UNRESOLVED",
            TRANSCRIPTION_COMPUTE_TYPE,
        )
        return prepared

    def execute(
        self,
        prepared: PreparedTranscription,
        cancellation: threading.Event,
        progress_callback: ProgressCallback | None = None,
    ) -> CompletedTranscription:
        started = time.monotonic()

        def report(provider_progress: ProviderProgress) -> None:
            if progress_callback is not None:
                progress_callback(
                    calculate_transcription_progress(
                        provider_progress.processed_time_ms,
                        prepared.audio_duration_seconds,
                    )
                )

        try:
            segments = self._provider.transcribe(
                prepared.audio_path,
                cancellation,
                report,
            )
            if cancellation.is_set():
                raise TranscriptionCancelled
            drafts = build_transcript_drafts(segments)
            revision = self._repository.replace_transcript(prepared.meeting_id, drafts)
            elapsed = time.monotonic() - started
            result = CompletedTranscription(
                meeting_id=prepared.meeting_id,
                segment_count=len(drafts),
                transcript_revision=revision,
                duration_seconds=elapsed,
            )
            self._logger.info(
                "Transcription completed meeting_id=%s duration_seconds=%.3f "
                "segment_count=%s transcript_revision=%s",
                prepared.meeting_id,
                elapsed,
                len(drafts),
                revision,
            )
            return result
        except TranscriptionCancelled:
            self._normalize_after_cancellation(prepared)
            self._logger.info("Transcription cancelled meeting_id=%s", prepared.meeting_id)
            raise
        except (TranscriptionProviderError, TranscriptionOperationError) as error:
            self._normalize_after_failure(prepared.meeting_id)
            self._logger.warning(
                "Transcription failed meeting_id=%s error=%s",
                prepared.meeting_id,
                type(error).__name__,
                exc_info=True,
            )
            raise
        except Exception as error:
            self._normalize_after_failure(prepared.meeting_id)
            self._logger.exception(
                "Transcription failed meeting_id=%s error=%s",
                prepared.meeting_id,
                type(error).__name__,
            )
            raise TranscriptionOperationError(
                "לא ניתן להשלים את התמלול. תמלול קודם, אם קיים, נשמר.",
                technical_message=f"Transcription orchestration failure: {error}",
            ) from error
        finally:
            with self._active_lock:
                if self._active_meeting_id == prepared.meeting_id:
                    self._active_meeting_id = None

    def abort_prepared(self, prepared: PreparedTranscription) -> None:
        """Normalize a reservation if its worker could not be started."""

        self._normalize_after_cancellation(prepared)
        with self._active_lock:
            if self._active_meeting_id == prepared.meeting_id:
                self._active_meeting_id = None

    def fail_prepared(self, prepared: PreparedTranscription) -> None:
        """Normalize an unexpected worker-boundary failure without touching transcript data."""

        self._normalize_after_failure(prepared.meeting_id)
        with self._active_lock:
            if self._active_meeting_id == prepared.meeting_id:
                self._active_meeting_id = None

    def _normalize_after_cancellation(self, prepared: PreparedTranscription) -> None:
        status = (
            TranscriptionStatus.COMPLETED
            if prepared.had_previous_transcript
            else TranscriptionStatus.NOT_STARTED
        )
        self._safe_set_status(prepared.meeting_id, status)

    def _normalize_after_failure(self, meeting_id: str) -> None:
        self._safe_set_status(meeting_id, TranscriptionStatus.FAILED)

    def _safe_set_status(self, meeting_id: str, status: TranscriptionStatus) -> None:
        try:
            self._repository.set_transcription_status(meeting_id, status)
        except (KeyError, SQLAlchemyError):
            self._logger.exception(
                "Failed normalizing transcription status meeting_id=%s status=%s",
                meeting_id,
                status,
            )
