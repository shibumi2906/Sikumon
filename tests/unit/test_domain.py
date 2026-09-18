from uuid import uuid4

from sikumon.domain.analysis import AnalysisRevision, analysis_is_current, analysis_is_outdated
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus


def test_durable_enum_values_are_exact() -> None:
    assert [item.value for item in TranscriptionStatus] == [
        "NOT_STARTED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
    ]
    assert [item.value for item in AnalysisOperationStatus] == [
        "NOT_STARTED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
    ]


def test_analysis_freshness_is_derived_from_revision() -> None:
    analysis = AnalysisRevision(uuid4(), source_transcript_revision=2)
    assert analysis_is_current(2, analysis)
    assert not analysis_is_outdated(2, analysis)
    assert not analysis_is_current(3, analysis)
    assert analysis_is_outdated(3, analysis)
    assert not analysis_is_current(0, None)
    assert not analysis_is_outdated(0, None)

