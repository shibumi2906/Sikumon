"""Meeting query, import, and deletion orchestration."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from sikumon.application.analysis_presentation import (
    AnalysisPresentation,
    build_analysis_presentation,
)
from sikumon.database.orm_models import MeetingORM
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.analysis import AnalysisRevision, analysis_is_outdated
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus
from sikumon.domain.transcript import TranscriptSegment
from sikumon.services.audio.metadata import AudioMetadataService, MediaValidationError
from sikumon.storage.file_storage import MeetingFileStorage


class MeetingDisplayState(StrEnum):
    CREATED = "CREATED"
    TRANSCRIBING = "TRANSCRIBING"
    TRANSCRIPT_READY = "TRANSCRIPT_READY"
    ANALYZING = "ANALYZING"
    ANALYSIS_READY = "ANALYSIS_READY"
    ANALYSIS_OUTDATED = "ANALYSIS_OUTDATED"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    AUDIO_MISSING = "AUDIO_MISSING"


@dataclass(frozen=True, slots=True)
class MeetingListItem:
    id: str
    title: str
    created_at: datetime
    display_state: MeetingDisplayState


@dataclass(frozen=True, slots=True)
class MeetingDetails:
    id: str
    title: str
    original_filename: str
    audio_path: str
    audio_duration_seconds: float | None
    created_at: datetime
    display_state: MeetingDisplayState
    audio_exists: bool
    can_delete: bool
    transcription_status: TranscriptionStatus
    analysis_operation_status: AnalysisOperationStatus
    transcript_revision: int
    transcript_segments: tuple[TranscriptSegment, ...]
    analysis: AnalysisPresentation | None


@dataclass(frozen=True, slots=True)
class MeetingDeletionResult:
    deleted_meeting_id: str
    undeleted_paths: tuple[Path, ...] = ()


class MeetingImportError(Exception):
    user_message = "לא ניתן לייבא את הפגישה. לא נשמרו נתונים חלקיים."


class MeetingNotFoundError(Exception):
    user_message = "הפגישה לא נמצאה."


class MeetingDeletionBlockedError(Exception):
    user_message = "לא ניתן למחוק פגישה בזמן שמתבצע תמלול או ניתוח."


class MeetingDeletionError(Exception):
    user_message = "לא ניתן למחוק את הפגישה. אפשר לנסות שוב."


def default_meeting_title(source: Path) -> str:
    title = " ".join(Path(source).stem.split())
    return title[:500] or "פגישה חדשה"


def derive_display_state(meeting: MeetingORM) -> MeetingDisplayState:
    if meeting.transcription_status == TranscriptionStatus.RUNNING:
        return MeetingDisplayState.TRANSCRIBING
    if meeting.analysis_operation_status == AnalysisOperationStatus.RUNNING:
        return MeetingDisplayState.ANALYZING
    if (
        meeting.transcription_status == TranscriptionStatus.FAILED
        or meeting.analysis_operation_status == AnalysisOperationStatus.FAILED
    ):
        return MeetingDisplayState.ACTION_REQUIRED
    current = meeting.current_analysis
    revision = (
        AnalysisRevision(id=current.id, source_transcript_revision=current.source_transcript_revision)
        if current is not None
        else None
    )
    if analysis_is_outdated(meeting.transcript_revision, revision):
        return MeetingDisplayState.ANALYSIS_OUTDATED
    if current is not None:
        return MeetingDisplayState.ANALYSIS_READY
    if meeting.transcription_status == TranscriptionStatus.COMPLETED:
        return MeetingDisplayState.TRANSCRIPT_READY
    return MeetingDisplayState.CREATED


class MeetingService:
    def __init__(
        self,
        repository: MeetingRepository,
        metadata_service: AudioMetadataService,
        file_storage: MeetingFileStorage,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repository = repository
        self._metadata_service = metadata_service
        self._file_storage = file_storage
        self._logger = logger or logging.getLogger("sikumon.application.meetings")

    def list_meetings(self) -> Sequence[MeetingListItem]:
        return tuple(
            MeetingListItem(
                id=meeting.id,
                title=meeting.title,
                created_at=meeting.created_at,
                display_state=(
                    derive_display_state(meeting)
                    if Path(meeting.audio_path).is_file()
                    else MeetingDisplayState.AUDIO_MISSING
                ),
            )
            for meeting in self._repository.list()
        )

    def get_meeting(self, meeting_id: str) -> MeetingDetails | None:
        meeting = self._repository.get(meeting_id)
        if meeting is None:
            return None
        return self._details(meeting)

    def import_meeting(self, source: Path, title: str) -> MeetingDetails:
        """Stage and verify files, commit DB metadata, then atomically expose storage.

        SQLite and the filesystem cannot share a transaction, so every exception after staging
        invokes deterministic compensation for both sides before a safe error escapes.
        """

        source = Path(source)
        normalized_title = " ".join(title.split())
        if not normalized_title:
            raise ValueError("Meeting title cannot be empty")
        if len(normalized_title) > 500:
            raise ValueError("Meeting title cannot exceed 500 characters")

        self._logger.info("Meeting import started source_filename=%s", source.name)
        try:
            metadata = self._metadata_service.inspect(source)
        except MediaValidationError:
            self._logger.warning("Meeting media validation failed source_filename=%s", source.name)
            raise

        meeting_id = uuid4()
        final_audio = self._file_storage.final_audio_path(
            meeting_id, metadata.normalized_extension
        )
        staged = False
        persisted = False
        finalized = False
        try:
            staged_audio = self._file_storage.copy_to_staging(
                source, meeting_id, metadata.normalized_extension
            )
            staged = True
            copied_metadata = self._metadata_service.inspect(staged_audio)
            meeting = MeetingORM(
                id=str(meeting_id),
                title=normalized_title,
                original_filename=source.name,
                audio_path=str(final_audio),
                audio_duration_seconds=copied_metadata.duration_seconds,
            )
            self._repository.create(meeting)
            persisted = True
            self._file_storage.finalize_import(meeting_id)
            finalized = True
            self._logger.info("Meeting created meeting_id=%s", meeting_id)
            reloaded = self._repository.get(str(meeting_id))
            if reloaded is None:
                raise RuntimeError("Meeting disappeared after import")
            return self._details(reloaded)
        except MediaValidationError:
            self._logger.warning("Copied media verification failed meeting_id=%s", meeting_id)
            self._compensate_failed_import(meeting_id, persisted, staged, finalized)
            raise
        except Exception as error:
            self._logger.exception(
                "Meeting import failed meeting_id=%s error=%s",
                meeting_id,
                type(error).__name__,
            )
            self._compensate_failed_import(meeting_id, persisted, staged, finalized)
            raise MeetingImportError() from error

    def delete_meeting(self, meeting_id: str) -> MeetingDeletionResult:
        """Delete the DB aggregate first, then best-effort meeting-owned filesystem paths.

        This guarantees that missing or undeletable local files never prevent database cleanup;
        filesystem leftovers are returned so the UI can warn the user.
        """

        meeting = self._repository.get(meeting_id)
        if meeting is None:
            raise MeetingNotFoundError(meeting_id)
        if (
            meeting.transcription_status == TranscriptionStatus.RUNNING
            or meeting.analysis_operation_status == AnalysisOperationStatus.RUNNING
        ):
            raise MeetingDeletionBlockedError(meeting_id)

        self._logger.info("Meeting deletion started meeting_id=%s", meeting_id)
        try:
            if not self._repository.delete(meeting_id):
                raise MeetingNotFoundError(meeting_id)
        except MeetingNotFoundError:
            raise
        except SQLAlchemyError as error:
            self._logger.exception(
                "Meeting database deletion failed meeting_id=%s error=%s",
                meeting_id,
                type(error).__name__,
            )
            raise MeetingDeletionError(meeting_id) from error
        failed_paths = self._file_storage.delete_meeting_files(meeting_id)
        self._logger.info(
            "Meeting deletion completed meeting_id=%s filesystem_failures=%s",
            meeting_id,
            len(failed_paths),
        )
        return MeetingDeletionResult(
            deleted_meeting_id=meeting_id, undeleted_paths=failed_paths
        )

    def _details(self, meeting: MeetingORM) -> MeetingDetails:
        audio_exists = Path(meeting.audio_path).is_file()
        is_running = (
            meeting.transcription_status == TranscriptionStatus.RUNNING
            or meeting.analysis_operation_status == AnalysisOperationStatus.RUNNING
        )
        return MeetingDetails(
            id=meeting.id,
            title=meeting.title,
            original_filename=meeting.original_filename,
            audio_path=meeting.audio_path,
            audio_duration_seconds=meeting.audio_duration_seconds,
            created_at=meeting.created_at,
            display_state=(
                derive_display_state(meeting)
                if audio_exists
                else MeetingDisplayState.AUDIO_MISSING
            ),
            audio_exists=audio_exists,
            can_delete=not is_running,
            transcription_status=meeting.transcription_status,
            analysis_operation_status=meeting.analysis_operation_status,
            transcript_revision=meeting.transcript_revision,
            transcript_segments=tuple(
                TranscriptSegment(
                    id=UUID(segment.id),
                    meeting_id=UUID(segment.meeting_id),
                    position=segment.position,
                    start_time_ms=segment.start_time_ms,
                    end_time_ms=segment.end_time_ms,
                    text=segment.text,
                    created_at=segment.created_at,
                    updated_at=segment.updated_at,
                )
                for segment in sorted(
                    meeting.transcript_segments, key=lambda item: item.position
                )
            ),
            analysis=build_analysis_presentation(meeting, self._logger),
        )

    def _compensate_failed_import(
        self, meeting_id: UUID, persisted: bool, staged: bool, finalized: bool
    ) -> None:
        if persisted:
            try:
                self._repository.delete(str(meeting_id))
            except Exception as error:
                self._logger.critical(
                    "Failed database compensation meeting_id=%s error=%s",
                    meeting_id,
                    type(error).__name__,
                    exc_info=True,
                )
        if finalized:
            self._file_storage.delete_meeting_files(meeting_id)
        elif staged:
            try:
                self._file_storage.cleanup_import(meeting_id)
            except OSError as error:
                self._logger.warning(
                    "Failed import cleanup meeting_id=%s error=%s",
                    meeting_id,
                    type(error).__name__,
                    exc_info=True,
                )
