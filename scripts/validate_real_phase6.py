"""Run the final real Phase 6 validation through production services."""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path

from sikumon.application.analysis_service import MeetingAnalysisService
from sikumon.application.meeting_service import MeetingService, default_meeting_title
from sikumon.application.transcription_service import TranscriptionService
from sikumon.config.constants import DEFAULT_ANALYSIS_MODEL
from sikumon.database.db import create_session_factory, create_sqlite_engine
from sikumon.database.migrations import apply_migrations
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus
from sikumon.security.credentials import KeyringCredentialStore
from sikumon.services.analysis.evidence_validator import validate_evidence
from sikumon.services.analysis.openai_provider import OpenAIAnalysisProvider
from sikumon.services.analysis.prompt_builder import ANALYSIS_INSTRUCTIONS
from sikumon.services.analysis.provider import (
    AnalysisProvider,
    AnalysisProviderRequest,
    AnalysisProviderResult,
)
from sikumon.services.analysis.schemas import ActionItem, Decision, Evidence, MeetingAnalysisPayload
from sikumon.services.audio.metadata import AudioMetadataService
from sikumon.services.transcription.faster_whisper_ivrit import FasterWhisperIvritProvider
from sikumon.services.transcription.model_manager import ModelAvailability, ModelManager
from sikumon.storage.file_storage import MeetingFileStorage
from sikumon.storage.paths import ApplicationPaths

HEBREW_PATTERN = re.compile(r"[\u0590-\u05ff]")
SOURCE_AUDIO = Path(__file__).resolve().parents[1] / "test_media" / "HCSH001.mp3"


class AuditedProvider:
    def __init__(
        self,
        delegate: AnalysisProvider,
        repository: MeetingRepository,
        meeting_id: str,
        expected_input: str,
        initial_analysis_id: str | None,
    ) -> None:
        self._delegate = delegate
        self._repository = repository
        self._meeting_id = meeting_id
        self._expected_input = expected_input
        self._initial_analysis_id = initial_analysis_id
        self.latencies: list[float] = []
        self.request_scope_verified = True
        self.pointer_unchanged_before_persistence = True

    def analyze(self, request: AnalysisProviderRequest) -> AnalysisProviderResult:
        self.request_scope_verified &= (
            request.instructions == ANALYSIS_INSTRUCTIONS
            and request.transcript_input == self._expected_input
        )
        before = self._repository.get(self._meeting_id)
        self.pointer_unchanged_before_persistence &= (
            before is not None and before.current_analysis_id == self._initial_analysis_id
        )
        started = time.monotonic()
        result = self._delegate.analyze(request)
        self.latencies.append(time.monotonic() - started)
        after = self._repository.get(self._meeting_id)
        self.pointer_unchanged_before_persistence &= (
            after is not None and after.current_analysis_id == self._initial_analysis_id
        )
        return result


class AuditedProviderFactory:
    def __init__(
        self,
        repository: MeetingRepository,
        meeting_id: str,
        expected_input: str,
        initial_analysis_id: str | None,
    ) -> None:
        self._repository = repository
        self._meeting_id = meeting_id
        self._expected_input = expected_input
        self._initial_analysis_id = initial_analysis_id
        self.provider: AuditedProvider | None = None

    def create(self, api_key: str) -> AnalysisProvider:
        self.provider = AuditedProvider(
            OpenAIAnalysisProvider(api_key, DEFAULT_ANALYSIS_MODEL),
            self._repository,
            self._meeting_id,
            self._expected_input,
            self._initial_analysis_id,
        )
        return self.provider


def payload_from_persisted(meeting_id: str, repository: MeetingRepository) -> MeetingAnalysisPayload:
    meeting = repository.get(meeting_id)
    if meeting is None or meeting.current_analysis is None:
        raise RuntimeError("Persisted current analysis is unavailable")
    analysis = meeting.current_analysis
    decisions = [
        Decision(
            title=row.title,
            description=row.description,
            evidence=Evidence(
                segment_ids=[
                    ref.transcript_segment_id
                    for ref in sorted(
                        analysis.evidence_references,
                        key=lambda item: item.position,
                    )
                    if ref.decision_id == row.id
                ]
            ),
        )
        for row in sorted(analysis.decisions, key=lambda item: item.position)
    ]
    action_items = [
        ActionItem(
            title=row.title,
            description=row.description,
            assignee=row.assignee,
            deadline=row.deadline,
            evidence=Evidence(
                segment_ids=[
                    ref.transcript_segment_id
                    for ref in sorted(
                        analysis.evidence_references,
                        key=lambda item: item.position,
                    )
                    if ref.action_item_id == row.id
                ]
            ),
        )
        for row in sorted(analysis.action_items, key=lambda item: item.position)
    ]
    return MeetingAnalysisPayload.model_validate(
        {
            "summary": analysis.summary,
            "decisions": decisions,
            "action_items": action_items,
        }
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not SOURCE_AUDIO.is_file():
        raise SystemExit(f"Missing test audio: {SOURCE_AUDIO}")

    paths = ApplicationPaths.resolve()
    paths.ensure_directories()
    engine = create_sqlite_engine(paths.database)
    apply_migrations(engine)
    repository = MeetingRepository(create_session_factory(engine))
    meeting_service = MeetingService(
        repository,
        AudioMetadataService(),
        MeetingFileStorage(paths),
    )

    existing = next(
        (item for item in repository.list() if item.original_filename == SOURCE_AUDIO.name),
        None,
    )
    if existing is None:
        details = meeting_service.import_meeting(SOURCE_AUDIO, default_meeting_title(SOURCE_AUDIO))
        meeting_id = details.id
        imported = True
    else:
        meeting_id = existing.id
        imported = False

    meeting = repository.get(meeting_id)
    if meeting is None:
        raise RuntimeError("Meeting disappeared after import")
    if not meeting.transcript_segments:
        model_manager = ModelManager(paths)
        if model_manager.availability != ModelAvailability.AVAILABLE:
            raise RuntimeError("Verified local Ivrit.ai model is unavailable")
        transcription_service = TranscriptionService(
            repository,
            model_manager,
            FasterWhisperIvritProvider(model_manager.model_directory),
        )
        transcription_result = transcription_service.execute(
            transcription_service.prepare(meeting_id),
            threading.Event(),
        )
        transcription_seconds = transcription_result.duration_seconds
    else:
        transcription_seconds = 0.0

    meeting = repository.get(meeting_id)
    if meeting is None or not meeting.transcript_segments:
        raise RuntimeError("A persisted transcript was not produced")
    if meeting.transcription_status != TranscriptionStatus.COMPLETED:
        raise RuntimeError("Transcription did not reach COMPLETED")
    if not any(HEBREW_PATTERN.search(segment.text) for segment in meeting.transcript_segments):
        raise RuntimeError("Persisted transcript contains no Hebrew characters")

    initial_analysis_id = meeting.current_analysis_id
    credential_store = KeyringCredentialStore()
    if not credential_store.get_api_key():
        raise RuntimeError("OpenAI API key is unavailable")

    preliminary_service = MeetingAnalysisService(
        repository,
        credential_store,
        AuditedProviderFactory(repository, meeting_id, "", initial_analysis_id),
    )
    prepared = preliminary_service.prepare(meeting_id)
    factory = AuditedProviderFactory(
        repository,
        meeting_id,
        prepared.transcript_input,
        initial_analysis_id,
    )
    analysis_service = MeetingAnalysisService(repository, credential_store, factory)
    analysis_result = analysis_service.execute(prepared)
    audited = factory.provider
    if audited is None:
        raise RuntimeError("Production OpenAI provider was not created")

    persisted = repository.get(meeting_id)
    if persisted is None or persisted.current_analysis is None:
        raise RuntimeError("Analysis graph was not persisted")
    payload = payload_from_persisted(meeting_id, repository)
    validate_evidence(payload, meeting_id, prepared.source.segments)
    evidence_ids = {
        segment_id
        for decision in payload.decisions
        for segment_id in decision.evidence.segment_ids
    }
    evidence_ids.update(
        segment_id
        for item in payload.action_items
        for segment_id in item.evidence.segment_ids
    )
    source_ids = {str(segment.id) for segment in prepared.source.segments}

    transactional_persistence = (
        persisted.current_analysis_id == analysis_result.analysis_id
        and persisted.current_analysis.id == analysis_result.analysis_id
        and persisted.analysis_operation_status == AnalysisOperationStatus.COMPLETED
        and persisted.current_analysis.source_transcript_revision
        == prepared.source.transcript_revision
    )
    model_matches = persisted.current_analysis.model == DEFAULT_ANALYSIS_MODEL
    summary_has_hebrew = bool(HEBREW_PATTERN.search(payload.summary))

    engine.dispose()
    restarted_engine = create_sqlite_engine(paths.database)
    apply_migrations(restarted_engine)
    restarted_repository = MeetingRepository(create_session_factory(restarted_engine))
    reloaded = restarted_repository.get(meeting_id)
    reload_succeeded = (
        reloaded is not None
        and reloaded.current_analysis_id == analysis_result.analysis_id
        and reloaded.current_analysis is not None
        and reloaded.current_analysis.source_transcript_revision
        == prepared.source.transcript_revision
        and reloaded.analysis_operation_status == AnalysisOperationStatus.COMPLETED
    )
    restarted_engine.dispose()

    api_latency = sum(audited.latencies)
    print(f"meeting_id={meeting_id}")
    print(f"meeting_title={persisted.title}")
    print(f"meeting_imported={imported}")
    print(f"local_transcription_seconds={transcription_seconds:.3f}")
    print(f"model={persisted.current_analysis.model}")
    print(f"model_matches_required={model_matches}")
    print(f"transcript_revision={prepared.source.transcript_revision}")
    print(f"source_segment_count={len(prepared.source.segments)}")
    print(f"api_call_count={len(audited.latencies)}")
    print(f"api_latency_seconds={api_latency:.3f}")
    print(f"correction_retry_occurred={analysis_result.attempts == 2}")
    print(f"decision_count={len(payload.decisions)}")
    print(f"action_item_count={len(payload.action_items)}")
    print(f"pydantic_validation_succeeded={isinstance(payload, MeetingAnalysisPayload)}")
    print(f"evidence_validation_succeeded={evidence_ids <= source_ids}")
    print(f"hebrew_summary_returned={summary_has_hebrew}")
    print(f"summary_character_count={len(payload.summary)}")
    print(f"request_scope_verified={audited.request_scope_verified}")
    print(
        "current_analysis_unchanged_before_persistence="
        f"{audited.pointer_unchanged_before_persistence}"
    )
    print(f"transactional_persistence_succeeded={transactional_persistence}")
    print(f"reload_succeeded={reload_succeeded}")
    print(f"input_tokens={analysis_result.input_tokens}")
    print(f"output_tokens={analysis_result.output_tokens}")

    succeeded = all(
        (
            model_matches,
            summary_has_hebrew,
            evidence_ids <= source_ids,
            audited.request_scope_verified,
            audited.pointer_unchanged_before_persistence,
            transactional_persistence,
            reload_succeeded,
            1 <= analysis_result.attempts <= 2,
        )
    )
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
