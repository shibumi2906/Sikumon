"""Authoritative Pydantic v2 schema for meeting analysis."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class Evidence(StrictAnalysisModel):
    segment_ids: list[str] = Field(min_length=1)


class Decision(StrictAnalysisModel):
    title: str = Field(min_length=1)
    description: str | None = None
    evidence: Evidence


class ActionItem(StrictAnalysisModel):
    title: str = Field(min_length=1)
    description: str | None = None
    assignee: str | None = None
    deadline: str | None = None
    evidence: Evidence


class MeetingAnalysisPayload(StrictAnalysisModel):
    summary: str = Field(min_length=1)
    decisions: list[Decision]
    action_items: list[ActionItem]
