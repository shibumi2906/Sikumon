"""Transcript-domain values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    id: UUID
    meeting_id: UUID
    position: int
    start_time_ms: int
    end_time_ms: int
    text: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TranscriptSegmentDraft:
    """Complete candidate segment ready for one transactional commit."""

    id: UUID
    position: int
    start_time_ms: int
    end_time_ms: int
    text: str
