"""Application boundary for optimistic transactional transcript corrections."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from sikumon.database.repositories import (
    MeetingRepository,
    TranscriptMeetingNotFoundError,
    TranscriptRevisionConflictError,
    TranscriptStructureConflictError,
    TranscriptUpdateBlockedError,
)
from sikumon.domain.transcript import TranscriptSegment


class TranscriptSaveError(RuntimeError):
    def __init__(self, user_message: str, *, technical_message: str | None = None) -> None:
        super().__init__(technical_message or user_message)
        self.user_message = user_message


class TranscriptSaveConflictError(TranscriptSaveError):
    def __init__(self) -> None:
        super().__init__(
            "התמלול השתנה מאז שנפתח. יש לרענן אותו לפני שמירת התיקונים."
        )


class TranscriptSaveBlockedError(TranscriptSaveError):
    def __init__(self) -> None:
        super().__init__(
            "לא ניתן לשמור את התמלול בזמן שמתבצע תמלול או ניתוח של הפגישה."
        )


@dataclass(frozen=True, slots=True)
class TranscriptSnapshot:
    meeting_id: str
    revision: int
    transcript_updated_at: datetime | None
    segments: tuple[TranscriptSegment, ...]
    changed_segment_count: int


class TranscriptEditService:
    def __init__(
        self,
        repository: MeetingRepository,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repository = repository
        self._logger = logger or logging.getLogger("sikumon.application.transcript_edit")

    def save(
        self,
        meeting_id: str,
        expected_revision: int,
        segment_texts: Mapping[str, str],
    ) -> TranscriptSnapshot:
        self._logger.info(
            "Transcript save started meeting_id=%s source_revision=%s segment_count=%s",
            meeting_id,
            expected_revision,
            len(segment_texts),
        )
        try:
            result = self._repository.update_transcript_texts(
                meeting_id,
                expected_revision,
                segment_texts,
            )
            meeting = self._repository.get(meeting_id)
            if meeting is None:
                raise TranscriptMeetingNotFoundError(meeting_id)
        except TranscriptRevisionConflictError as error:
            self._logger.warning(
                "Transcript save conflict meeting_id=%s expected_revision=%s "
                "actual_revision=%s",
                meeting_id,
                error.expected,
                error.actual,
            )
            raise TranscriptSaveConflictError from error
        except TranscriptUpdateBlockedError as error:
            self._logger.warning("Transcript save blocked meeting_id=%s", meeting_id)
            raise TranscriptSaveBlockedError from error
        except TranscriptMeetingNotFoundError as error:
            self._logger.warning("Transcript save meeting missing meeting_id=%s", meeting_id)
            raise TranscriptSaveError("הפגישה לא נמצאה.") from error
        except TranscriptStructureConflictError as error:
            self._logger.warning(
                "Transcript save structure conflict meeting_id=%s", meeting_id
            )
            raise TranscriptSaveConflictError from error
        except SQLAlchemyError as error:
            self._logger.exception("Transcript save database failure meeting_id=%s", meeting_id)
            raise TranscriptSaveError(
                "לא ניתן לשמור את תיקוני התמלול. השינויים עדיין מופיעים במסך."
            ) from error
        snapshot = TranscriptSnapshot(
            meeting_id=meeting.id,
            revision=meeting.transcript_revision,
            transcript_updated_at=meeting.transcript_updated_at,
            segments=tuple(
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
            changed_segment_count=result.changed_segment_count,
        )
        self._logger.info(
            "Transcript save completed meeting_id=%s changed_segments=%s new_revision=%s",
            meeting_id,
            result.changed_segment_count,
            result.revision,
        )
        return snapshot
