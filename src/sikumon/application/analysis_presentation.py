"""Immutable presentation data for persisted meeting analyses."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sikumon.database.orm_models import EvidenceReferenceORM, MeetingORM

EVIDENCE_PREVIEW_LENGTH = 140


@dataclass(frozen=True, slots=True)
class EvidencePresentation:
    segment_id: str
    start_time_ms: int | None
    preview: str
    available: bool


@dataclass(frozen=True, slots=True)
class DecisionPresentation:
    title: str
    description: str | None
    evidence: tuple[EvidencePresentation, ...]


@dataclass(frozen=True, slots=True)
class ActionItemPresentation:
    title: str
    description: str | None
    assignee: str | None
    deadline: str | None
    evidence: tuple[EvidencePresentation, ...]


@dataclass(frozen=True, slots=True)
class AnalysisPresentation:
    summary: str
    decisions: tuple[DecisionPresentation, ...]
    action_items: tuple[ActionItemPresentation, ...]
    is_outdated: bool


def format_evidence_preview(text: str, limit: int = EVIDENCE_PREVIEW_LENGTH) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(1, limit - 1)].rstrip() + "…"


def build_analysis_presentation(
    meeting: MeetingORM,
    logger: logging.Logger | None = None,
) -> AnalysisPresentation | None:
    analysis = meeting.current_analysis
    if analysis is None:
        return None
    log = logger or logging.getLogger("sikumon.application.analysis_presentation")
    segments = {segment.id: segment for segment in meeting.transcript_segments}

    def resolve(refs: list[EvidenceReferenceORM]) -> tuple[EvidencePresentation, ...]:
        resolved: list[EvidencePresentation] = []
        for reference in sorted(refs, key=lambda item: item.position):
            segment = segments.get(reference.transcript_segment_id)
            if segment is None:
                log.warning(
                    "Analysis evidence segment unavailable meeting_id=%s analysis_id=%s",
                    meeting.id,
                    analysis.id,
                )
                resolved.append(
                    EvidencePresentation(
                        segment_id=reference.transcript_segment_id,
                        start_time_ms=None,
                        preview="המקור אינו זמין",
                        available=False,
                    )
                )
                continue
            resolved.append(
                EvidencePresentation(
                    segment_id=segment.id,
                    start_time_ms=segment.start_time_ms,
                    preview=format_evidence_preview(segment.text),
                    available=True,
                )
            )
        return tuple(resolved)

    decisions = tuple(
        DecisionPresentation(
            title=row.title,
            description=row.description,
            evidence=resolve(
                [ref for ref in analysis.evidence_references if ref.decision_id == row.id]
            ),
        )
        for row in sorted(analysis.decisions, key=lambda item: item.position)
    )
    action_items = tuple(
        ActionItemPresentation(
            title=row.title,
            description=row.description,
            assignee=row.assignee,
            deadline=row.deadline,
            evidence=resolve(
                [
                    ref
                    for ref in analysis.evidence_references
                    if ref.action_item_id == row.id
                ]
            ),
        )
        for row in sorted(analysis.action_items, key=lambda item: item.position)
    )
    return AnalysisPresentation(
        summary=analysis.summary,
        decisions=decisions,
        action_items=action_items,
        is_outdated=analysis.source_transcript_revision != meeting.transcript_revision,
    )
