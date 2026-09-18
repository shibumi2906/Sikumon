"""Hebrew presentation mappings for derived application state."""

from __future__ import annotations

from sikumon.application.meeting_service import MeetingDisplayState

STATUS_LABELS = {
    MeetingDisplayState.CREATED: "ההקלטה יובאה",
    MeetingDisplayState.TRANSCRIBING: "בתהליך תמלול",
    MeetingDisplayState.TRANSCRIPT_READY: "התמלול מוכן",
    MeetingDisplayState.ANALYZING: "בתהליך ניתוח",
    MeetingDisplayState.ANALYSIS_READY: "הניתוח מוכן",
    MeetingDisplayState.ANALYSIS_OUTDATED: "הסיכום אינו עדכני",
    MeetingDisplayState.ACTION_REQUIRED: "נדרשת פעולה",
    MeetingDisplayState.AUDIO_MISSING: "קובץ ההקלטה חסר",
}


def format_duration(duration_seconds: float | None) -> str:
    if duration_seconds is None:
        return "לא ידוע"
    total_seconds = max(0, round(duration_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_timestamp_ms(timestamp_ms: int) -> str:
    total_seconds = max(0, timestamp_ms) // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
