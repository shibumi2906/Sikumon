from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from sikumon.application.analysis_presentation import build_analysis_presentation
from sikumon.application.analysis_service import (
    AnalysisOperationError,
    MeetingAnalysisService,
)
from sikumon.application.meeting_service import MeetingDisplayState, derive_display_state
from sikumon.application.transcript_edit_service import TranscriptEditService
from sikumon.database.db import create_session_factory, create_sqlite_engine
from sikumon.database.migrations import apply_migrations
from sikumon.database.orm_models import (
    ActionItemORM,
    DecisionORM,
    EvidenceReferenceORM,
    MeetingAnalysisORM,
    MeetingORM,
)
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import AnalysisOperationStatus
from sikumon.domain.transcript import TranscriptSegmentDraft
from sikumon.services.analysis.provider import (
    AnalysisAuthenticationError,
    AnalysisNetworkError,
    AnalysisProvider,
    AnalysisProviderError,
    AnalysisProviderRefusalError,
    AnalysisProviderRequest,
    AnalysisProviderResult,
    AnalysisRateLimitError,
    AnalysisServerError,
    AnalysisStructuredOutputError,
)


class FakeCredentials:
    def __init__(self, api_key: str | None = "sk-test") -> None:
        self.api_key = api_key

    def get_api_key(self) -> str | None:
        return self.api_key

    def set_api_key(self, api_key: str) -> None:
        self.api_key = api_key

    def delete_api_key(self) -> None:
        self.api_key = None


class QueueProvider:
    def __init__(self, responses: Sequence[object]) -> None:
        self.responses = list(responses)
        self.requests: list[AnalysisProviderRequest] = []

    def analyze(self, request: AnalysisProviderRequest) -> AnalysisProviderResult:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return AnalysisProviderResult(response, input_tokens=100, output_tokens=40)


class FakeFactory:
    def __init__(self, provider: AnalysisProvider) -> None:
        self.provider = provider
        self.keys: list[str] = []

    def create(self, api_key: str) -> AnalysisProvider:
        self.keys.append(api_key)
        return self.provider


def create_transcript(repository: MeetingRepository) -> MeetingORM:
    meeting = repository.create(
        MeetingORM(title="ניתוח", original_filename="a.wav", audio_path="a.wav")
    )
    repository.replace_transcript(
        meeting.id,
        (
            TranscriptSegmentDraft(uuid4(), 0, 0, 2_000, "החלטנו להשיק ביום ראשון."),
            TranscriptSegmentDraft(uuid4(), 1, 2_100, 4_000, "דוד ישלח את החוזה מחר."),
        ),
    )
    loaded = repository.get(meeting.id)
    assert loaded is not None
    return loaded


def payload(first_id: str, second_id: str | None = None) -> dict[str, object]:
    task_id = second_id or first_id
    return {
        "summary": "הצוות החליט להתקדם וחילק משימה.",
        "decisions": [
            {
                "title": "להשיק ביום ראשון",
                "description": None,
                "evidence": {"segment_ids": [first_id]},
            }
        ],
        "action_items": [
            {
                "title": "לשלוח את החוזה",
                "description": None,
                "assignee": "דוד",
                "deadline": "מחר",
                "evidence": {"segment_ids": [task_id]},
            }
        ],
    }


def service_with(
    repository: MeetingRepository,
    provider: AnalysisProvider,
    credentials: FakeCredentials | None = None,
) -> MeetingAnalysisService:
    return MeetingAnalysisService(
        repository,
        credentials or FakeCredentials(),
        FakeFactory(provider),
    )


def test_success_persists_full_analysis_graph_and_source_revision(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    first, second = meeting.transcript_segments
    provider = QueueProvider([payload(first.id, second.id)])
    service = service_with(repository, provider)

    prepared = service.prepare(meeting.id)
    result = service.execute(prepared)
    reloaded = repository.get(meeting.id)
    assert reloaded is not None
    assert reloaded.current_analysis is not None

    assert result.source_transcript_revision == 1
    assert reloaded.analysis_operation_status == AnalysisOperationStatus.COMPLETED
    assert reloaded.current_analysis_id == result.analysis_id
    assert reloaded.current_analysis.source_transcript_revision == 1
    assert reloaded.current_analysis.provider == "openai"
    assert len(reloaded.current_analysis.decisions) == 1
    assert len(reloaded.current_analysis.action_items) == 1
    assert len(reloaded.current_analysis.evidence_references) == 2
    assert provider.requests[0].correction_instruction is None
    assert str(first.id) in provider.requests[0].transcript_input
    assert str(second.id) in provider.requests[0].transcript_input
    assert meeting.audio_path not in provider.requests[0].transcript_input


def test_invalid_evidence_gets_one_successful_controlled_retry(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    first, second = meeting.transcript_segments
    provider = QueueProvider([payload(str(uuid4())), payload(first.id, second.id)])
    service = service_with(repository, provider)

    result = service.execute(service.prepare(meeting.id))

    assert result.attempts == 2
    assert len(provider.requests) == 2
    assert provider.requests[1].correction_instruction is not None
    assert str(first.id) in provider.requests[1].correction_instruction
    assert repository.get(meeting.id).analysis_operation_status == AnalysisOperationStatus.COMPLETED


def test_invalid_correction_fails_after_two_attempts_and_creates_no_analysis(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    invalid = payload(str(uuid4()))
    provider = QueueProvider([invalid, invalid])
    service = service_with(repository, provider)

    with pytest.raises(AnalysisOperationError, match="לאמת"):
        service.execute(service.prepare(meeting.id))
    reloaded = repository.get(meeting.id)
    assert reloaded is not None
    assert len(provider.requests) == 2
    assert reloaded.analysis_operation_status == AnalysisOperationStatus.FAILED
    assert reloaded.current_analysis_id is None
    assert reloaded.analyses == []


def test_invalid_schema_after_single_retry_never_persists(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    invalid_schema = {"summary": "", "decisions": [], "action_items": []}
    provider = QueueProvider([invalid_schema, invalid_schema])
    service = service_with(repository, provider)

    with pytest.raises(AnalysisOperationError, match="לאמת"):
        service.execute(service.prepare(meeting.id))

    reloaded = repository.get(meeting.id)
    assert reloaded is not None
    assert len(provider.requests) == 2
    assert reloaded.analysis_operation_status == AnalysisOperationStatus.FAILED
    assert reloaded.current_analysis_id is None
    assert reloaded.analyses == []


def test_failed_reanalysis_preserves_previous_current_analysis(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    first, second = meeting.transcript_segments
    initial = service_with(repository, QueueProvider([payload(first.id, second.id)]))
    initial_result = initial.execute(initial.prepare(meeting.id))

    invalid = payload(str(uuid4()))
    failing = service_with(repository, QueueProvider([invalid, invalid]))
    with pytest.raises(AnalysisOperationError):
        failing.execute(failing.prepare(meeting.id))
    reloaded = repository.get(meeting.id)
    assert reloaded is not None

    assert reloaded.current_analysis_id == initial_result.analysis_id
    assert len(reloaded.analyses) == 1
    assert reloaded.analysis_operation_status == AnalysisOperationStatus.FAILED


@pytest.mark.parametrize(
    ("provider_error", "expected_message"),
    [
        (AnalysisAuthenticationError("HTTP 401"), "מפתח"),
        (AnalysisAuthenticationError("HTTP 403"), "מפתח"),
        (AnalysisRateLimitError("HTTP 429"), "מגבלת"),
        (AnalysisServerError("HTTP 503"), "זמנית"),
        (AnalysisNetworkError("connection"), "חיבור"),
        (AnalysisNetworkError("timeout"), "חיבור"),
    ],
)
def test_openai_transport_failures_preserve_previous_analysis_and_transcript(
    database,
    provider_error: AnalysisProviderError,
    expected_message: str,
) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    first, second = meeting.transcript_segments
    initial_service = service_with(
        repository, QueueProvider([payload(first.id, second.id)])
    )
    previous_id = initial_service.execute(initial_service.prepare(meeting.id)).analysis_id
    before = repository.get(meeting.id)
    assert before is not None
    transcript_snapshot = [(segment.id, segment.text) for segment in before.transcript_segments]
    class FailingProvider:
        def analyze(self, request: AnalysisProviderRequest) -> AnalysisProviderResult:
            raise provider_error

    failing_service = service_with(repository, FailingProvider())

    with pytest.raises(AnalysisOperationError) as captured:
        failing_service.execute(failing_service.prepare(meeting.id))

    after = repository.get(meeting.id)
    assert after is not None
    assert expected_message in captured.value.user_message
    assert after.current_analysis_id == previous_id
    assert after.analysis_operation_status == AnalysisOperationStatus.FAILED
    assert [(segment.id, segment.text) for segment in after.transcript_segments] == (
        transcript_snapshot
    )


@pytest.mark.parametrize(
    "provider_error",
    [
        AnalysisProviderRefusalError("refusal"),
        AnalysisProviderError("incomplete response"),
        AnalysisStructuredOutputError("missing parsed result"),
    ],
)
def test_refusal_incomplete_and_missing_parse_preserve_previous_analysis(
    database,
    provider_error: AnalysisProviderError,
) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    first, second = meeting.transcript_segments
    initial = service_with(repository, QueueProvider([payload(first.id, second.id)]))
    previous_id = initial.execute(initial.prepare(meeting.id)).analysis_id

    class FailingProvider:
        def analyze(self, request: AnalysisProviderRequest) -> AnalysisProviderResult:
            raise provider_error

    failing = service_with(repository, FailingProvider())
    with pytest.raises(AnalysisOperationError):
        failing.execute(failing.prepare(meeting.id))

    reloaded = repository.get(meeting.id)
    assert reloaded is not None
    assert reloaded.current_analysis_id == previous_id
    assert len(reloaded.analyses) == 1
    assert reloaded.analysis_operation_status == AnalysisOperationStatus.FAILED


def test_database_failure_rolls_back_reanalysis_and_preserves_previous(database) -> None:
    engine, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    first, second = meeting.transcript_segments
    first_service = service_with(repository, QueueProvider([payload(first.id, second.id)]))
    current_id = first_service.execute(first_service.prepare(meeting.id)).analysis_id
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER fail_analysis_insert BEFORE INSERT ON meeting_analyses "
                "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END"
            )
        )

    replacement = service_with(repository, QueueProvider([payload(first.id, second.id)]))
    with pytest.raises(AnalysisOperationError, match="לשמור"):
        replacement.execute(replacement.prepare(meeting.id))
    reloaded = repository.get(meeting.id)
    assert reloaded is not None

    assert reloaded.current_analysis_id == current_id
    assert len(reloaded.analyses) == 1
    assert reloaded.analysis_operation_status == AnalysisOperationStatus.FAILED


def test_revision_change_during_provider_work_never_becomes_current(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    first, second = meeting.transcript_segments
    service = service_with(repository, QueueProvider([payload(first.id, second.id)]))
    prepared = service.prepare(meeting.id)
    repository.update(meeting.id, transcript_revision=2)

    with pytest.raises(AnalysisOperationError, match="השתנה"):
        service.execute(prepared)
    reloaded = repository.get(meeting.id)
    assert reloaded is not None
    assert reloaded.current_analysis_id is None
    assert reloaded.analyses == []
    assert reloaded.analysis_operation_status == AnalysisOperationStatus.FAILED


def test_missing_credentials_and_oversized_input_stop_before_provider(database, monkeypatch) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    provider = QueueProvider([])

    missing = service_with(repository, provider, FakeCredentials(None))
    with pytest.raises(AnalysisOperationError, match="מפתח OpenAI"):
        missing.prepare(meeting.id)
    assert repository.get(meeting.id).analysis_operation_status == AnalysisOperationStatus.NOT_STARTED

    monkeypatch.setattr("sikumon.application.analysis_service.MAX_ANALYSIS_INPUT_ESTIMATED_TOKENS", 1)
    oversized = service_with(repository, provider)
    with pytest.raises(AnalysisOperationError, match="גדול מדי"):
        oversized.prepare(meeting.id)
    assert provider.requests == []
    assert repository.get(meeting.id).analysis_operation_status == AnalysisOperationStatus.FAILED


def test_duplicate_analysis_reservation_is_rejected(database) -> None:
    _, session_factory = database
    repository = MeetingRepository(session_factory)
    meeting = create_transcript(repository)
    provider = QueueProvider([])
    service = service_with(repository, provider)

    prepared = service.prepare(meeting.id)
    try:
        with pytest.raises(AnalysisOperationError, match="תהליך אחר"):
            service.prepare(meeting.id)
        assert provider.requests == []
    finally:
        service.abort_prepared(prepared)


def test_analysis_survives_engine_restart_and_becomes_outdated_after_edit(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "analysis-restart" / "sikumon.db"
    engine = create_sqlite_engine(database_path)
    apply_migrations(engine)
    repository = MeetingRepository(create_session_factory(engine))
    meeting = create_transcript(repository)
    first, second = meeting.transcript_segments
    service = service_with(repository, QueueProvider([payload(first.id, second.id)]))
    analysis_id = service.execute(service.prepare(meeting.id)).analysis_id
    engine.dispose()

    restarted_engine = create_sqlite_engine(database_path)
    try:
        restarted_repository = MeetingRepository(create_session_factory(restarted_engine))
        reloaded = restarted_repository.get(meeting.id)
        assert reloaded is not None
        assert reloaded.current_analysis_id == analysis_id
        assert reloaded.current_analysis is not None
        assert len(reloaded.current_analysis.evidence_references) == 2
        presentation = build_analysis_presentation(reloaded)
        assert presentation is not None
        assert presentation.summary == "הצוות החליט להתקדם וחילק משימה."
        assert [item.title for item in presentation.decisions] == ["להשיק ביום ראשון"]
        assert [item.title for item in presentation.action_items] == ["לשלוח את החוזה"]
        assert presentation.action_items[0].evidence[0].segment_id == second.id
        assert not presentation.is_outdated

        TranscriptEditService(restarted_repository).save(
            meeting.id,
            1,
            {
                reloaded.transcript_segments[0].id: "תמלול מתוקן",
                reloaded.transcript_segments[1].id: reloaded.transcript_segments[1].text,
            },
        )
        outdated = restarted_repository.get(meeting.id)
        assert outdated is not None
        assert outdated.current_analysis_id == analysis_id
        assert derive_display_state(outdated) == MeetingDisplayState.ANALYSIS_OUTDATED
        outdated_presentation = build_analysis_presentation(outdated)
        assert outdated_presentation is not None
        assert outdated_presentation.is_outdated
        assert outdated_presentation.summary == presentation.summary
        with restarted_repository._session_factory() as session:
            assert session.scalar(select(func.count()).select_from(DecisionORM)) == 1
            assert session.scalar(select(func.count()).select_from(ActionItemORM)) == 1
            assert session.scalar(select(func.count()).select_from(EvidenceReferenceORM)) == 2
            assert session.scalar(select(func.count()).select_from(MeetingAnalysisORM)) == 1
    finally:
        restarted_engine.dispose()
