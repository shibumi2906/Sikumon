"""Analysis-domain values and freshness rules."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AnalysisRevision:
    id: UUID | str
    source_transcript_revision: int


@dataclass(frozen=True, slots=True)
class AnalysisDecisionDraft:
    title: str
    description: str | None
    evidence_segment_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnalysisActionItemDraft:
    title: str
    description: str | None
    assignee: str | None
    deadline: str | None
    evidence_segment_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeetingAnalysisDraft:
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    source_transcript_revision: int
    summary: str
    decisions: tuple[AnalysisDecisionDraft, ...]
    action_items: tuple[AnalysisActionItemDraft, ...]


def analysis_is_current(
    transcript_revision: int, current_analysis: AnalysisRevision | None
) -> bool:
    return (
        current_analysis is not None
        and current_analysis.source_transcript_revision == transcript_revision
    )


def analysis_is_outdated(
    transcript_revision: int, current_analysis: AnalysisRevision | None
) -> bool:
    return (
        current_analysis is not None
        and current_analysis.source_transcript_revision != transcript_revision
    )
