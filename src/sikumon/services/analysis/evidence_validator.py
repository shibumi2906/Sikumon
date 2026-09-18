"""Semantic evidence-anchor validation."""

from __future__ import annotations

from collections.abc import Iterable

from sikumon.domain.transcript import TranscriptSegment
from sikumon.services.analysis.schemas import MeetingAnalysisPayload


class EvidenceValidationError(ValueError):
    def __init__(self, reason: str, invalid_segment_ids: Iterable[str] = ()) -> None:
        self.reason = reason
        self.invalid_segment_ids = tuple(invalid_segment_ids)
        super().__init__(reason)


def validate_evidence(
    payload: MeetingAnalysisPayload,
    meeting_id: str,
    segments: Iterable[TranscriptSegment],
) -> None:
    segment_list = tuple(segments)
    foreign = [segment for segment in segment_list if str(segment.meeting_id) != meeting_id]
    if foreign:
        raise EvidenceValidationError("מקטע מקור אינו שייך לפגישה")
    valid_ids = {str(segment.id) for segment in segment_list}
    referenced_ids = [
        segment_id
        for decision in payload.decisions
        for segment_id in decision.evidence.segment_ids
    ]
    referenced_ids.extend(
        segment_id
        for item in payload.action_items
        for segment_id in item.evidence.segment_ids
    )
    invalid = sorted(set(referenced_ids) - valid_ids)
    if invalid:
        raise EvidenceValidationError("מזהי ראיה לא מוכרים", invalid)
