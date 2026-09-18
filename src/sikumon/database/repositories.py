"""Persistence boundaries used by application services and UI presenters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from sikumon.database.orm_models import (
    ActionItemORM,
    DecisionORM,
    EvidenceReferenceORM,
    MeetingAnalysisORM,
    MeetingORM,
    TranscriptSegmentORM,
    utc_now,
)
from sikumon.domain.analysis import MeetingAnalysisDraft
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus
from sikumon.domain.transcript import TranscriptSegment, TranscriptSegmentDraft


class MeetingRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _load_options() -> tuple[Any, ...]:
        current_analysis = selectinload(MeetingORM.current_analysis)
        return (
            selectinload(MeetingORM.transcript_segments),
            selectinload(MeetingORM.analyses).selectinload(MeetingAnalysisORM.decisions),
            selectinload(MeetingORM.analyses).selectinload(MeetingAnalysisORM.action_items),
            selectinload(MeetingORM.analyses).selectinload(
                MeetingAnalysisORM.evidence_references
            ),
            current_analysis.selectinload(MeetingAnalysisORM.decisions),
            current_analysis.selectinload(MeetingAnalysisORM.action_items),
            current_analysis.selectinload(MeetingAnalysisORM.evidence_references),
        )

    def create(self, meeting: MeetingORM) -> MeetingORM:
        with self._session_factory() as session, session.begin():
            session.add(meeting)
        return meeting

    def save(self, meeting: MeetingORM) -> MeetingORM:
        with self._session_factory() as session, session.begin():
            saved = session.merge(meeting)
        return saved

    def get(self, meeting_id: str) -> MeetingORM | None:
        with self._session_factory() as session:
            statement = (
                select(MeetingORM)
                .where(MeetingORM.id == str(meeting_id))
                .options(*self._load_options())
            )
            return session.scalar(statement)

    def list(self) -> Sequence[MeetingORM]:
        with self._session_factory() as session:
            statement = (
                select(MeetingORM)
                .order_by(MeetingORM.created_at.desc())
                .options(*self._load_options())
            )
            return tuple(session.scalars(statement).unique().all())

    def update(self, meeting_id: str, **changes: object) -> MeetingORM:
        allowed = {
            "title",
            "original_filename",
            "audio_path",
            "audio_duration_seconds",
            "transcription_status",
            "transcript_created_at",
            "transcript_updated_at",
            "transcript_revision",
            "analysis_operation_status",
            "current_analysis_id",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unsupported meeting fields: {sorted(unknown)}")
        with self._session_factory() as session, session.begin():
            meeting = session.get(MeetingORM, str(meeting_id))
            if meeting is None:
                raise KeyError(str(meeting_id))
            for field, value in changes.items():
                setattr(meeting, field, value)
        return meeting

    def begin_transcription(self, meeting_id: str) -> bool:
        """Atomically reserve a meeting transcription operation."""

        with self._session_factory() as session, session.begin():
            meeting = session.get(MeetingORM, str(meeting_id))
            if meeting is None:
                raise KeyError(str(meeting_id))
            if meeting.transcription_status == TranscriptionStatus.RUNNING:
                return False
            meeting.transcription_status = TranscriptionStatus.RUNNING
        return True

    def begin_analysis(self, meeting_id: str) -> AnalysisSourceSnapshot:
        """Atomically reserve analysis and capture its exact canonical transcript."""

        with self._session_factory() as session, session.begin():
            statement = (
                select(MeetingORM)
                .where(MeetingORM.id == str(meeting_id))
                .options(selectinload(MeetingORM.transcript_segments))
            )
            meeting = session.scalar(statement)
            if meeting is None:
                raise AnalysisMeetingNotFoundError(str(meeting_id))
            if meeting.analysis_operation_status == AnalysisOperationStatus.RUNNING:
                raise AnalysisStartBlockedError("analysis is already running")
            if meeting.transcription_status == TranscriptionStatus.RUNNING:
                raise AnalysisStartBlockedError("transcription is running")
            if not meeting.transcript_segments or not any(
                segment.text.strip() for segment in meeting.transcript_segments
            ):
                raise AnalysisStartBlockedError("transcript is empty")
            meeting.analysis_operation_status = AnalysisOperationStatus.RUNNING
            segments = tuple(
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
            )
            return AnalysisSourceSnapshot(
                meeting_id=meeting.id,
                transcript_revision=meeting.transcript_revision,
                segments=segments,
            )

    def fail_analysis(self, meeting_id: str) -> None:
        with self._session_factory() as session, session.begin():
            meeting = session.get(MeetingORM, str(meeting_id))
            if (
                meeting is not None
                and meeting.analysis_operation_status == AnalysisOperationStatus.RUNNING
            ):
                meeting.analysis_operation_status = AnalysisOperationStatus.FAILED

    def complete_analysis(
        self,
        meeting_id: str,
        expected_revision: int,
        draft: MeetingAnalysisDraft,
    ) -> str:
        """Persist one complete validated analysis graph and publish it atomically."""

        with self._session_factory() as session, session.begin():
            meeting = session.get(MeetingORM, str(meeting_id))
            if meeting is None:
                raise AnalysisMeetingNotFoundError(str(meeting_id))
            if meeting.transcript_revision != expected_revision:
                raise AnalysisStaleRevisionError(expected_revision, meeting.transcript_revision)
            if meeting.analysis_operation_status != AnalysisOperationStatus.RUNNING:
                raise AnalysisStartBlockedError("analysis operation is not running")
            if draft.source_transcript_revision != expected_revision:
                raise AnalysisStaleRevisionError(
                    expected_revision, draft.source_transcript_revision
                )
            canonical_segment_ids = set(
                session.scalars(
                    select(TranscriptSegmentORM.id).where(
                        TranscriptSegmentORM.meeting_id == meeting.id
                    )
                )
            )
            evidence_ids = {
                segment_id
                for decision in draft.decisions
                for segment_id in decision.evidence_segment_ids
            }
            evidence_ids.update(
                segment_id
                for item in draft.action_items
                for segment_id in item.evidence_segment_ids
            )
            if not evidence_ids <= canonical_segment_ids:
                raise AnalysisEvidenceConflictError(
                    "analysis evidence does not belong to the canonical meeting transcript"
                )
            analysis = MeetingAnalysisORM(
                meeting_id=meeting.id,
                provider=draft.provider,
                model=draft.model,
                prompt_version=draft.prompt_version,
                schema_version=draft.schema_version,
                source_transcript_revision=draft.source_transcript_revision,
                summary=draft.summary,
            )
            decision_rows = [
                DecisionORM(
                    analysis=analysis,
                    position=position,
                    title=decision.title,
                    description=decision.description,
                )
                for position, decision in enumerate(draft.decisions)
            ]
            action_rows = [
                ActionItemORM(
                    analysis=analysis,
                    position=position,
                    title=item.title,
                    description=item.description,
                    assignee=item.assignee,
                    deadline=item.deadline,
                )
                for position, item in enumerate(draft.action_items)
            ]
            session.add(analysis)
            session.add_all((*decision_rows, *action_rows))
            session.flush()
            evidence_rows = [
                EvidenceReferenceORM(
                    analysis_id=analysis.id,
                    decision_id=row.id,
                    transcript_segment_id=segment_id,
                    position=position,
                )
                for row, decision in zip(decision_rows, draft.decisions, strict=True)
                for position, segment_id in enumerate(decision.evidence_segment_ids)
            ]
            evidence_rows.extend(
                EvidenceReferenceORM(
                    analysis_id=analysis.id,
                    action_item_id=row.id,
                    transcript_segment_id=segment_id,
                    position=position,
                )
                for row, item in zip(action_rows, draft.action_items, strict=True)
                for position, segment_id in enumerate(item.evidence_segment_ids)
            )
            session.add_all(evidence_rows)
            session.flush()
            meeting.current_analysis_id = analysis.id
            meeting.analysis_operation_status = AnalysisOperationStatus.COMPLETED
            analysis_id = analysis.id
        return analysis_id

    def set_transcription_status(
        self, meeting_id: str, status: TranscriptionStatus
    ) -> None:
        with self._session_factory() as session, session.begin():
            meeting = session.get(MeetingORM, str(meeting_id))
            if meeting is None:
                raise KeyError(str(meeting_id))
            meeting.transcription_status = status

    def replace_transcript(
        self, meeting_id: str, segments: Sequence[TranscriptSegmentDraft]
    ) -> int:
        """Replace the complete canonical transcript and revision in one transaction."""

        if not segments:
            raise ValueError("A canonical transcript must contain at least one segment")
        with self._session_factory() as session, session.begin():
            meeting = session.get(MeetingORM, str(meeting_id))
            if meeting is None:
                raise KeyError(str(meeting_id))
            now = utc_now()
            session.execute(
                delete(TranscriptSegmentORM).where(
                    TranscriptSegmentORM.meeting_id == meeting.id
                )
            )
            session.add_all(
                TranscriptSegmentORM(
                    id=str(segment.id),
                    meeting_id=meeting.id,
                    position=segment.position,
                    start_time_ms=segment.start_time_ms,
                    end_time_ms=segment.end_time_ms,
                    text=segment.text,
                    created_at=now,
                    updated_at=now,
                )
                for segment in segments
            )
            meeting.transcript_created_at = meeting.transcript_created_at or now
            meeting.transcript_updated_at = now
            meeting.transcript_revision += 1
            meeting.transcription_status = TranscriptionStatus.COMPLETED
            revision = meeting.transcript_revision
        return revision

    def update_transcript_texts(
        self,
        meeting_id: str,
        expected_revision: int,
        segment_texts: Mapping[str, str],
    ) -> TranscriptTextUpdateResult:
        """Optimistically update transcript text only, as one transaction."""

        with self._session_factory() as session, session.begin():
            statement = (
                select(MeetingORM)
                .where(MeetingORM.id == str(meeting_id))
                .options(selectinload(MeetingORM.transcript_segments))
            )
            meeting = session.scalar(statement)
            if meeting is None:
                raise TranscriptMeetingNotFoundError(str(meeting_id))
            if meeting.transcript_revision != expected_revision:
                raise TranscriptRevisionConflictError(
                    expected_revision, meeting.transcript_revision
                )
            if meeting.transcription_status == TranscriptionStatus.RUNNING:
                raise TranscriptUpdateBlockedError("transcription is running")
            if meeting.analysis_operation_status == AnalysisOperationStatus.RUNNING:
                raise TranscriptUpdateBlockedError("analysis is running")
            persisted_by_id = {
                segment.id: segment for segment in meeting.transcript_segments
            }
            if not persisted_by_id:
                raise TranscriptStructureConflictError("meeting has no transcript segments")
            if set(segment_texts) != set(persisted_by_id):
                raise TranscriptStructureConflictError(
                    "submitted segment IDs do not match the canonical transcript"
                )
            changed = [
                segment
                for segment_id, segment in persisted_by_id.items()
                if segment.text != segment_texts[segment_id]
            ]
            if not changed:
                return TranscriptTextUpdateResult(
                    revision=meeting.transcript_revision,
                    changed_segment_count=0,
                )
            now = utc_now()
            for segment in changed:
                segment.text = segment_texts[segment.id]
                segment.updated_at = now
            meeting.transcript_updated_at = now
            meeting.transcript_revision += 1
            return TranscriptTextUpdateResult(
                revision=meeting.transcript_revision,
                changed_segment_count=len(changed),
            )

    def delete(self, meeting_id: str) -> bool:
        with self._session_factory() as session, session.begin():
            meeting = session.get(MeetingORM, str(meeting_id))
            if meeting is None:
                return False
            # Break the intentional current-analysis cycle before database cascades remove
            # the complete meeting aggregate. Analyses go before transcript segments because
            # evidence deliberately restricts deletion of anchors that are still referenced.
            meeting.current_analysis_id = None
            session.flush()
            session.execute(
                delete(MeetingAnalysisORM).where(MeetingAnalysisORM.meeting_id == meeting.id)
            )
            session.flush()
            session.delete(meeting)
        return True


@dataclass(frozen=True, slots=True)
class TranscriptTextUpdateResult:
    revision: int
    changed_segment_count: int


@dataclass(frozen=True, slots=True)
class AnalysisSourceSnapshot:
    meeting_id: str
    transcript_revision: int
    segments: tuple[TranscriptSegment, ...]


class TranscriptMeetingNotFoundError(RuntimeError):
    pass


class TranscriptRevisionConflictError(RuntimeError):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"Transcript revision conflict: expected {expected}, actual {actual}")
        self.expected = expected
        self.actual = actual


class TranscriptStructureConflictError(RuntimeError):
    pass


class TranscriptUpdateBlockedError(RuntimeError):
    pass


class AnalysisMeetingNotFoundError(RuntimeError):
    pass


class AnalysisStartBlockedError(RuntimeError):
    pass


class AnalysisStaleRevisionError(RuntimeError):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"Analysis revision conflict: expected {expected}, actual {actual}")
        self.expected = expected
        self.actual = actual


class AnalysisEvidenceConflictError(RuntimeError):
    pass
