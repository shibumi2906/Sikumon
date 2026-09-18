from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError

from sikumon.domain.analysis import AnalysisRevision, analysis_is_current, analysis_is_outdated
from sikumon.domain.transcript import TranscriptSegment
from sikumon.security.credentials import KeyringCredentialStore
from sikumon.services.analysis.evidence_validator import (
    EvidenceValidationError,
    validate_evidence,
)
from sikumon.services.analysis.openai_provider import OpenAIAnalysisProvider
from sikumon.services.analysis.prompt_builder import (
    ANALYSIS_INSTRUCTIONS,
    build_transcript_input,
    estimate_input_tokens,
)
from sikumon.services.analysis.provider import (
    AnalysisAuthenticationError,
    AnalysisNetworkError,
    AnalysisProviderError,
    AnalysisProviderRefusalError,
    AnalysisProviderRequest,
    AnalysisRateLimitError,
    AnalysisServerError,
)
from sikumon.services.analysis.schemas import MeetingAnalysisPayload


def segment(meeting_id: UUID, position: int, text: str) -> TranscriptSegment:
    now = datetime.now(UTC)
    return TranscriptSegment(
        id=uuid4(),
        meeting_id=meeting_id,
        position=position,
        start_time_ms=position * 1_000,
        end_time_ms=(position + 1) * 1_000,
        text=text,
        created_at=now,
        updated_at=now,
    )


def valid_payload(segment_id: str) -> dict[str, object]:
    return {
        "summary": "סיכום בעברית",
        "decisions": [
            {
                "title": "החלטה",
                "description": None,
                "evidence": {"segment_ids": [segment_id]},
            }
        ],
        "action_items": [
            {
                "title": "משימה",
                "description": None,
                "assignee": None,
                "deadline": None,
                "evidence": {"segment_ids": [segment_id]},
            }
        ],
    }


def test_prompt_contains_only_supplied_segments_and_exact_ids() -> None:
    meeting_id = uuid4()
    second = segment(meeting_id, 1, "דוד ישלח מחר")
    first = segment(meeting_id, 0, "הוחלט להתקדם")

    rendered = build_transcript_input((second, first))

    assert rendered.index(str(first.id)) < rendered.index(str(second.id))
    assert f"[{first.id}]" in rendered
    assert f"[{second.id}]" in rendered
    assert "הוחלט להתקדם" in rendered
    assert "דוד ישלח מחר" in rendered
    assert "audio" not in rendered.lower()
    assert "never invent" not in rendered.lower()
    assert "בעברית" in ANALYSIS_INSTRUCTIONS


def test_schema_accepts_empty_results_and_null_assignment_fields() -> None:
    payload = MeetingAnalysisPayload.model_validate(
        {"summary": "סיכום", "decisions": [], "action_items": []}
    )
    assert payload.decisions == []
    assert payload.action_items == []

    with_task = MeetingAnalysisPayload.model_validate(valid_payload(str(uuid4())))
    assert with_task.action_items[0].assignee is None
    assert with_task.action_items[0].deadline is None


@pytest.mark.parametrize(
    "evidence",
    [None, {"segment_ids": []}],
)
def test_schema_rejects_missing_or_empty_evidence(evidence: object) -> None:
    decision: dict[str, object] = {"title": "החלטה", "description": None}
    if evidence is not None:
        decision["evidence"] = evidence
    with pytest.raises(ValidationError):
        MeetingAnalysisPayload.model_validate(
            {"summary": "סיכום", "decisions": [decision], "action_items": []}
        )


def test_evidence_rejects_unknown_ids_and_segments_from_another_meeting() -> None:
    meeting_id = uuid4()
    valid_segment = segment(meeting_id, 0, "טקסט")
    foreign_segment = segment(uuid4(), 0, "זר")
    payload = MeetingAnalysisPayload.model_validate(valid_payload(str(foreign_segment.id)))
    with pytest.raises(EvidenceValidationError) as unknown:
        validate_evidence(payload, str(meeting_id), (valid_segment,))
    assert unknown.value.invalid_segment_ids == (str(foreign_segment.id),)

    empty = MeetingAnalysisPayload.model_validate(
        {"summary": "סיכום", "decisions": [], "action_items": []}
    )
    with pytest.raises(EvidenceValidationError, match="אינו שייך"):
        validate_evidence(empty, str(meeting_id), (foreign_segment,))


def test_analysis_freshness_rules_remain_derived() -> None:
    analysis = AnalysisRevision(uuid4(), 3)
    assert analysis_is_current(3, analysis)
    assert not analysis_is_outdated(3, analysis)
    assert analysis_is_outdated(4, analysis)


def test_openai_provider_uses_responses_parse_structured_output_and_store_false() -> None:
    calls: list[dict[str, object]] = []

    class Responses:
        def parse(self, **kwargs: object) -> object:
            calls.append(kwargs)
            return SimpleNamespace(
                status="completed",
                output_parsed=MeetingAnalysisPayload.model_validate(
                    {"summary": "סיכום", "decisions": [], "action_items": []}
                ),
                output=(),
                usage=SimpleNamespace(input_tokens=12, output_tokens=8),
            )

    class Client:
        responses = Responses()
        closed = False

        def close(self) -> None:
            self.closed = True

    client = Client()
    provider = OpenAIAnalysisProvider(
        "secret",
        "test-model",
        client_factory=lambda api_key: client,  # type: ignore[arg-type]
    )
    result = provider.analyze(AnalysisProviderRequest("instructions", "transcript"))

    assert result.input_tokens == 12
    assert calls[0]["model"] == "test-model"
    assert calls[0]["text_format"] is MeetingAnalysisPayload
    assert calls[0]["store"] is False
    assert calls[0]["input"] == "transcript"
    assert client.closed


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (
            SimpleNamespace(
                status="incomplete", output_parsed=None, output=(), usage=None
            ),
            AnalysisProviderError,
        ),
        (
            SimpleNamespace(
                status="completed",
                output_parsed=None,
                output=(
                    SimpleNamespace(content=(SimpleNamespace(type="refusal"),)),
                ),
                usage=None,
            ),
            AnalysisProviderRefusalError,
        ),
    ],
)
def test_openai_provider_rejects_incomplete_and_refusal_responses(
    response: object, error_type: type[AnalysisProviderError]
) -> None:
    class Responses:
        def parse(self, **kwargs: object) -> object:
            return response

    class Client:
        responses = Responses()

        def close(self) -> None:
            pass

    provider = OpenAIAnalysisProvider(
        "secret",
        "test-model",
        client_factory=lambda api_key: Client(),  # type: ignore[arg-type]
    )
    with pytest.raises(error_type):
        provider.analyze(AnalysisProviderRequest("instructions", "transcript"))


@pytest.mark.parametrize(
    ("status_code", "expected_type", "message_fragment"),
    [
        (401, AnalysisAuthenticationError, "מפתח"),
        (403, AnalysisAuthenticationError, "מפתח"),
        (429, AnalysisRateLimitError, "מגבלת"),
        (500, AnalysisServerError, "זמנית"),
        (503, AnalysisServerError, "זמנית"),
    ],
)
def test_openai_provider_maps_http_failures_to_actionable_hebrew(
    status_code: int,
    expected_type: type[AnalysisProviderError],
    message_fragment: str,
) -> None:
    from openai import APIStatusError

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    error = APIStatusError(
        "provider failure",
        response=httpx.Response(status_code, request=request),
        body=None,
    )
    closed: list[bool] = []

    class Responses:
        def parse(self, **kwargs: object) -> object:
            raise error

    class Client:
        responses = Responses()

        def close(self) -> None:
            closed.append(True)

    provider = OpenAIAnalysisProvider(
        "secret", "test-model", client_factory=lambda api_key: Client()  # type: ignore[arg-type]
    )
    with pytest.raises(expected_type) as captured:
        provider.analyze(AnalysisProviderRequest("instructions", "transcript"))

    assert message_fragment in captured.value.user_message
    assert closed == [True]


@pytest.mark.parametrize("network_error", ["connection", "timeout"])
def test_openai_provider_maps_network_failures_and_closes_client(
    network_error: str,
) -> None:
    from openai import APIConnectionError, APITimeoutError

    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    error = (
        APIConnectionError(request=request)
        if network_error == "connection"
        else APITimeoutError(request)
    )
    closed: list[bool] = []

    class Responses:
        def parse(self, **kwargs: object) -> object:
            raise error

    class Client:
        responses = Responses()

        def close(self) -> None:
            closed.append(True)

    provider = OpenAIAnalysisProvider(
        "secret", "test-model", client_factory=lambda api_key: Client()  # type: ignore[arg-type]
    )
    with pytest.raises(AnalysisNetworkError, match=type(error).__name__) as captured:
        provider.analyze(AnalysisProviderRequest("instructions", "transcript"))

    assert "החיבור לאינטרנט" in captured.value.user_message
    assert closed == [True]


def test_keyring_store_never_exposes_saved_key_in_state(monkeypatch) -> None:
    saved: dict[tuple[str, str], str] = {}
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "keyring.get_password", lambda service, account: saved.get((service, account))
    )
    monkeypatch.setattr(
        "keyring.set_password",
        lambda service, account, value: saved.__setitem__((service, account), value),
    )
    monkeypatch.setattr(
        "keyring.delete_password", lambda service, account: saved.pop((service, account))
    )
    store = KeyringCredentialStore()

    assert store.get_api_key() is None
    store.set_api_key("  sk-test  ")
    assert store.get_api_key() == "sk-test"
    assert not hasattr(store, "api_key")
    store.delete_api_key()
    assert store.get_api_key() is None


def test_utf8_byte_estimator_is_conservative_for_hebrew() -> None:
    assert estimate_input_tokens("שלום") == len("שלום".encode())
