"""SQLAlchemy ORM schema for durable Sikumon data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC timestamps in SQLite and always return aware UTC values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class SchemaVersionORM(Base):
    __tablename__ = "schema_version"

    singleton: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (CheckConstraint("singleton = 1", name="ck_schema_version_singleton"),)


class MeetingORM(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    audio_path: Mapped[str] = mapped_column(String(4096), nullable=False, default="")
    audio_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcription_status: Mapped[TranscriptionStatus] = mapped_column(
        Enum(
            TranscriptionStatus,
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            name="transcription_status",
        ),
        default=TranscriptionStatus.NOT_STARTED,
        nullable=False,
    )
    transcript_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    transcript_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    transcript_revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    analysis_operation_status: Mapped[AnalysisOperationStatus] = mapped_column(
        Enum(
            AnalysisOperationStatus,
            native_enum=False,
            validate_strings=True,
            create_constraint=True,
            name="analysis_operation_status",
        ),
        default=AnalysisOperationStatus.NOT_STARTED,
        nullable=False,
    )
    current_analysis_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("meeting_analyses.id", ondelete="SET NULL"), nullable=True
    )

    transcript_segments: Mapped[list[TranscriptSegmentORM]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TranscriptSegmentORM.position",
    )
    analyses: Mapped[list[MeetingAnalysisORM]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="MeetingAnalysisORM.meeting_id",
    )
    current_analysis: Mapped[MeetingAnalysisORM | None] = relationship(
        foreign_keys=[current_analysis_id],
        primaryjoin="MeetingORM.current_analysis_id == MeetingAnalysisORM.id",
        post_update=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["current_analysis_id", "id"],
            ["meeting_analyses.id", "meeting_analyses.meeting_id"],
            name="fk_meeting_current_analysis_owner",
        ),
        CheckConstraint("transcript_revision >= 0", name="ck_meeting_transcript_revision"),
    )


class TranscriptSegmentORM(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    start_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    meeting: Mapped[MeetingORM] = relationship(back_populates="transcript_segments")

    __table_args__ = (
        UniqueConstraint("meeting_id", "position", name="uq_segment_meeting_position"),
        CheckConstraint("position >= 0", name="ck_segment_position"),
        CheckConstraint("start_time_ms >= 0", name="ck_segment_start"),
        CheckConstraint("end_time_ms >= start_time_ms", name="ck_segment_times"),
    )


class MeetingAnalysisORM(Base):
    __tablename__ = "meeting_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    source_transcript_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    meeting: Mapped[MeetingORM] = relationship(
        back_populates="analyses", foreign_keys=[meeting_id]
    )
    decisions: Mapped[list[DecisionORM]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", passive_deletes=True
    )
    action_items: Mapped[list[ActionItemORM]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", passive_deletes=True
    )
    evidence_references: Mapped[list[EvidenceReferenceORM]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        UniqueConstraint("id", "meeting_id", name="uq_analysis_id_meeting"),
        CheckConstraint(
            "source_transcript_revision >= 0", name="ck_analysis_source_revision"
        ),
    )


class DecisionORM(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meeting_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    analysis: Mapped[MeetingAnalysisORM] = relationship(back_populates="decisions")
    evidence_references: Mapped[list[EvidenceReferenceORM]] = relationship(
        back_populates="decision",
        passive_deletes=True,
        foreign_keys="[EvidenceReferenceORM.decision_id, EvidenceReferenceORM.analysis_id]",
        overlaps="analysis,evidence_references",
    )

    __table_args__ = (
        UniqueConstraint("analysis_id", "position", name="uq_decision_position"),
        UniqueConstraint("id", "analysis_id", name="uq_decision_id_analysis"),
    )


class ActionItemORM(Base):
    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meeting_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(500), nullable=True)

    analysis: Mapped[MeetingAnalysisORM] = relationship(back_populates="action_items")
    evidence_references: Mapped[list[EvidenceReferenceORM]] = relationship(
        back_populates="action_item",
        passive_deletes=True,
        foreign_keys="[EvidenceReferenceORM.action_item_id, EvidenceReferenceORM.analysis_id]",
        overlaps="analysis,evidence_references,decision",
    )

    __table_args__ = (
        UniqueConstraint("analysis_id", "position", name="uq_action_position"),
        UniqueConstraint("id", "analysis_id", name="uq_action_id_analysis"),
    )


class EvidenceReferenceORM(Base):
    __tablename__ = "evidence_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meeting_analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    transcript_segment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transcript_segments.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    analysis: Mapped[MeetingAnalysisORM] = relationship(
        back_populates="evidence_references",
        foreign_keys=[analysis_id],
        overlaps="action_item,decision,evidence_references",
    )
    decision: Mapped[DecisionORM | None] = relationship(
        back_populates="evidence_references",
        foreign_keys=[decision_id, analysis_id],
        overlaps="analysis,evidence_references",
    )
    action_item: Mapped[ActionItemORM | None] = relationship(
        back_populates="evidence_references",
        foreign_keys=[action_item_id, analysis_id],
        overlaps="analysis,decision,evidence_references",
    )
    transcript_segment: Mapped[TranscriptSegmentORM] = relationship()

    __table_args__ = (
        ForeignKeyConstraint(
            ["decision_id", "analysis_id"],
            ["decisions.id", "decisions.analysis_id"],
            ondelete="CASCADE",
            name="fk_evidence_decision_owner",
        ),
        ForeignKeyConstraint(
            ["action_item_id", "analysis_id"],
            ["action_items.id", "action_items.analysis_id"],
            ondelete="CASCADE",
            name="fk_evidence_action_owner",
        ),
        CheckConstraint(
            "(decision_id IS NOT NULL AND action_item_id IS NULL) OR "
            "(decision_id IS NULL AND action_item_id IS NOT NULL)",
            name="ck_evidence_single_owner",
        ),
    )
