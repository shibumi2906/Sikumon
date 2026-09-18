"""Revision-safe orchestration for structured cloud transcript analysis."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from sikumon.config.constants import (
    ANALYSIS_PROMPT_VERSION,
    ANALYSIS_SCHEMA_VERSION,
    DEFAULT_ANALYSIS_MODEL,
    DEFAULT_ANALYSIS_PROVIDER,
    MAX_ANALYSIS_INPUT_ESTIMATED_TOKENS,
)
from sikumon.database.repositories import (
    AnalysisMeetingNotFoundError,
    AnalysisSourceSnapshot,
    AnalysisStaleRevisionError,
    AnalysisStartBlockedError,
    MeetingRepository,
)
from sikumon.domain.analysis import (
    AnalysisActionItemDraft,
    AnalysisDecisionDraft,
    MeetingAnalysisDraft,
)
from sikumon.security.credentials import CredentialStore, CredentialStoreError
from sikumon.services.analysis.evidence_validator import (
    EvidenceValidationError,
    validate_evidence,
)
from sikumon.services.analysis.prompt_builder import (
    ANALYSIS_INSTRUCTIONS,
    build_correction_instruction,
    build_transcript_input,
    estimate_input_tokens,
)
from sikumon.services.analysis.provider import (
    AnalysisProviderError,
    AnalysisProviderFactory,
    AnalysisProviderRequest,
    AnalysisStructuredOutputError,
)
from sikumon.services.analysis.schemas import MeetingAnalysisPayload


class AnalysisOperationError(RuntimeError):
    def __init__(self, user_message: str, *, technical_message: str | None = None) -> None:
        super().__init__(technical_message or user_message)
        self.user_message = user_message


class AnalysisCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedAnalysis:
    source: AnalysisSourceSnapshot
    transcript_input: str
    api_key: str = field(repr=False)

    @property
    def meeting_id(self) -> str:
        return self.source.meeting_id


@dataclass(frozen=True, slots=True)
class CompletedAnalysis:
    meeting_id: str
    analysis_id: str
    source_transcript_revision: int
    attempts: int
    input_tokens: int | None
    output_tokens: int | None
    duration_seconds: float


class MeetingAnalysisService:
    def __init__(
        self,
        repository: MeetingRepository,
        credential_store: CredentialStore,
        provider_factory: AnalysisProviderFactory,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repository = repository
        self._credential_store = credential_store
        self._provider_factory = provider_factory
        self._logger = logger or logging.getLogger("sikumon.application.analysis")

    def prepare(self, meeting_id: str) -> PreparedAnalysis:
        try:
            api_key = self._credential_store.get_api_key()
        except CredentialStoreError as error:
            raise AnalysisOperationError(
                "לא ניתן לקרוא את מפתח OpenAI ממנהל האישורים של Windows."
            ) from error
        if not api_key:
            raise AnalysisOperationError(
                "נדרש מפתח OpenAI לניתוח פגישה. אפשר להגדיר אותו בהגדרות."
            )
        try:
            source = self._repository.begin_analysis(meeting_id)
        except AnalysisMeetingNotFoundError as error:
            raise AnalysisOperationError("הפגישה לא נמצאה.") from error
        except AnalysisStartBlockedError as error:
            if "empty" in str(error):
                message = "נדרש תמלול שמור ולא ריק לפני ניתוח הפגישה."
            else:
                message = "לא ניתן להתחיל ניתוח בזמן שמתבצע תהליך אחר בפגישה."
            raise AnalysisOperationError(message) from error

        transcript_input = build_transcript_input(source.segments)
        estimate = estimate_input_tokens(ANALYSIS_INSTRUCTIONS + transcript_input)
        if estimate > MAX_ANALYSIS_INPUT_ESTIMATED_TOKENS:
            self._repository.fail_analysis(meeting_id)
            self._logger.warning(
                "Analysis input rejected meeting_id=%s revision=%s estimated_tokens=%s",
                meeting_id,
                source.transcript_revision,
                estimate,
            )
            raise AnalysisOperationError(
                "התמלול גדול מדי לניתוח במודל שנבחר. התמלול נשמר ולא השתנה."
            )
        self._logger.info(
            "Analysis prepared meeting_id=%s revision=%s segment_count=%s model=%s "
            "prompt_version=%s schema_version=%s estimated_tokens=%s",
            meeting_id,
            source.transcript_revision,
            len(source.segments),
            DEFAULT_ANALYSIS_MODEL,
            ANALYSIS_PROMPT_VERSION,
            ANALYSIS_SCHEMA_VERSION,
            estimate,
        )
        return PreparedAnalysis(source, transcript_input, api_key)

    def execute(
        self,
        prepared: PreparedAnalysis,
        cancellation: threading.Event | None = None,
    ) -> CompletedAnalysis:
        started = time.monotonic()
        attempts = 0
        input_tokens: int | None = None
        output_tokens: int | None = None
        correction: str | None = None
        valid_ids = tuple(str(segment.id) for segment in prepared.source.segments)
        try:
            provider = self._provider_factory.create(prepared.api_key)
            while attempts < 2:
                self._raise_if_cancelled(cancellation)
                attempts += 1
                try:
                    result = provider.analyze(
                        AnalysisProviderRequest(
                            instructions=ANALYSIS_INSTRUCTIONS,
                            transcript_input=prepared.transcript_input,
                            correction_instruction=correction,
                        )
                    )
                    payload = MeetingAnalysisPayload.model_validate(result.payload)
                    validate_evidence(
                        payload,
                        prepared.meeting_id,
                        prepared.source.segments,
                    )
                    input_tokens = result.input_tokens
                    output_tokens = result.output_tokens
                    break
                except (
                    AnalysisStructuredOutputError,
                    ValidationError,
                    EvidenceValidationError,
                ) as error:
                    failure_type = type(error).__name__
                    self._logger.warning(
                        "Analysis validation failed meeting_id=%s attempt=%s type=%s",
                        prepared.meeting_id,
                        attempts,
                        failure_type,
                    )
                    if attempts >= 2:
                        raise AnalysisOperationError(
                            "לא ניתן לאמת את תוצאת הניתוח. התמלול והניתוח הקודם נשמרו."
                        ) from error
                    reason = (
                        error.reason
                        if isinstance(error, EvidenceValidationError)
                        else "מבנה התוצאה אינו תקין"
                    )
                    correction = build_correction_instruction(reason, valid_ids)
                    self._logger.info(
                        "Analysis correction retry meeting_id=%s revision=%s",
                        prepared.meeting_id,
                        prepared.source.transcript_revision,
                    )
            else:
                raise AnalysisOperationError("לא ניתן לאמת את תוצאת הניתוח.")

            self._raise_if_cancelled(cancellation)
            draft = self._to_draft(payload, prepared.source.transcript_revision)
            analysis_id = self._repository.complete_analysis(
                prepared.meeting_id,
                prepared.source.transcript_revision,
                draft,
            )
        except AnalysisCancelled:
            self._repository.fail_analysis(prepared.meeting_id)
            raise
        except AnalysisStaleRevisionError as error:
            self._repository.fail_analysis(prepared.meeting_id)
            self._logger.warning(
                "Stale analysis rejected meeting_id=%s source_revision=%s actual_revision=%s",
                prepared.meeting_id,
                error.expected,
                error.actual,
            )
            raise AnalysisOperationError(
                "התמלול השתנה בזמן הניתוח. התוצאה לא נשמרה; אפשר להפעיל ניתוח חדש."
            ) from error
        except AnalysisProviderError as error:
            self._repository.fail_analysis(prepared.meeting_id)
            self._logger.warning(
                "Analysis provider failure meeting_id=%s type=%s",
                prepared.meeting_id,
                type(error).__name__,
            )
            raise AnalysisOperationError(error.user_message) from error
        except AnalysisOperationError:
            self._repository.fail_analysis(prepared.meeting_id)
            raise
        except (SQLAlchemyError, AnalysisMeetingNotFoundError) as error:
            self._repository.fail_analysis(prepared.meeting_id)
            self._logger.error(
                "Analysis persistence failure meeting_id=%s type=%s",
                prepared.meeting_id,
                type(error).__name__,
            )
            raise AnalysisOperationError(
                "לא ניתן לשמור את הניתוח. התמלול והניתוח הקודם נשמרו."
            ) from error
        except Exception as error:
            self._repository.fail_analysis(prepared.meeting_id)
            self._logger.error(
                "Unexpected analysis failure meeting_id=%s type=%s",
                prepared.meeting_id,
                type(error).__name__,
            )
            raise AnalysisOperationError(
                "לא ניתן להשלים את ניתוח הפגישה. התמלול והניתוח הקודם נשמרו."
            ) from error
        duration = time.monotonic() - started
        self._logger.info(
            "Analysis completed meeting_id=%s revision=%s analysis_id=%s attempts=%s "
            "decisions=%s action_items=%s duration_seconds=%.3f input_tokens=%s "
            "output_tokens=%s",
            prepared.meeting_id,
            prepared.source.transcript_revision,
            analysis_id,
            attempts,
            len(payload.decisions),
            len(payload.action_items),
            duration,
            input_tokens,
            output_tokens,
        )
        return CompletedAnalysis(
            meeting_id=prepared.meeting_id,
            analysis_id=analysis_id,
            source_transcript_revision=prepared.source.transcript_revision,
            attempts=attempts,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            duration_seconds=duration,
        )

    def abort_prepared(self, prepared: PreparedAnalysis) -> None:
        self._repository.fail_analysis(prepared.meeting_id)

    @staticmethod
    def _raise_if_cancelled(cancellation: threading.Event | None) -> None:
        if cancellation is not None and cancellation.is_set():
            raise AnalysisCancelled

    @staticmethod
    def _to_draft(payload: MeetingAnalysisPayload, revision: int) -> MeetingAnalysisDraft:
        return MeetingAnalysisDraft(
            provider=DEFAULT_ANALYSIS_PROVIDER,
            model=DEFAULT_ANALYSIS_MODEL,
            prompt_version=ANALYSIS_PROMPT_VERSION,
            schema_version=ANALYSIS_SCHEMA_VERSION,
            source_transcript_revision=revision,
            summary=payload.summary,
            decisions=tuple(
                AnalysisDecisionDraft(
                    title=item.title,
                    description=item.description,
                    evidence_segment_ids=tuple(item.evidence.segment_ids),
                )
                for item in payload.decisions
            ),
            action_items=tuple(
                AnalysisActionItemDraft(
                    title=item.title,
                    description=item.description,
                    assignee=item.assignee,
                    deadline=item.deadline,
                    evidence_segment_ids=tuple(item.evidence.segment_ids),
                )
                for item in payload.action_items
            ),
        )
