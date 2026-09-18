"""Meeting-domain values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus


@dataclass(frozen=True, slots=True)
class Meeting:
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    original_filename: str
    audio_path: str
    audio_duration_seconds: float | None = None
    transcription_status: TranscriptionStatus = TranscriptionStatus.NOT_STARTED
    transcript_created_at: datetime | None = None
    transcript_updated_at: datetime | None = None
    transcript_revision: int = 0
    analysis_operation_status: AnalysisOperationStatus = AnalysisOperationStatus.NOT_STARTED
    current_analysis_id: UUID | None = None

