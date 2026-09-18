"""Normalize durable states whose workers cannot survive application exit."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from sikumon.database.orm_models import MeetingORM
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus
from sikumon.services.audio.metadata import (
    AudioMetadataService,
    MediaValidationError,
    MediaValidationFailure,
)
from sikumon.storage.file_storage import MeetingFileStorage


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    transcription_failures: int
    analysis_failures: int


@dataclass(frozen=True, slots=True)
class StorageRecoveryResult:
    finalized_imports: int = 0
    removed_incomplete_imports: int = 0
    removed_orphan_directories: int = 0
    deferred_paths: tuple[Path, ...] = ()


def recover_stale_operations(
    session_factory: sessionmaker[Session], logger: logging.Logger | None = None
) -> RecoveryResult:
    with session_factory() as session, session.begin():
        transcription = session.execute(
            update(MeetingORM)
            .where(MeetingORM.transcription_status == TranscriptionStatus.RUNNING)
            .values(transcription_status=TranscriptionStatus.FAILED)
        )
        analysis = session.execute(
            update(MeetingORM)
            .where(MeetingORM.analysis_operation_status == AnalysisOperationStatus.RUNNING)
            .values(analysis_operation_status=AnalysisOperationStatus.FAILED)
        )
    result = RecoveryResult(
        transcription_failures=cast(CursorResult[Any], transcription).rowcount or 0,
        analysis_failures=cast(CursorResult[Any], analysis).rowcount or 0,
    )
    if logger:
        logger.info(
            "Startup recovery normalized transcription=%s analysis=%s stale operations",
            result.transcription_failures,
            result.analysis_failures,
        )
    return result


def recover_meeting_storage(
    repository: MeetingRepository,
    file_storage: MeetingFileStorage,
    metadata_service: AudioMetadataService,
    logger: logging.Logger | None = None,
) -> StorageRecoveryResult:
    """Reconcile only UUID-scoped Sikumon directories with authoritative SQLite rows.

    A staged directory matching a committed meeting is recoverable and must never be blindly
    deleted. It is finalized after its expected audio file validates. UUID directories without
    a database owner are incomplete imports or deletion leftovers and are safely retried for
    removal. Arbitrary non-UUID directories are ignored.
    """

    log = logger or logging.getLogger("sikumon.application.recovery")
    meetings = {UUID(meeting.id): meeting for meeting in repository.list()}
    database_ids = set(meetings)
    finalized_imports = 0
    removed_incomplete = 0
    removed_orphans = 0
    deferred: list[Path] = []

    for meeting_id in file_storage.staged_import_ids():
        meeting = meetings.get(meeting_id)
        staging = file_storage.import_directory(meeting_id)
        final_directory = file_storage.meeting_directory(meeting_id)
        if meeting is None:
            try:
                file_storage.cleanup_import(meeting_id)
                removed_incomplete += 1
            except OSError:
                log.exception("Failed removing uncommitted staged import meeting_id=%s", meeting_id)
                deferred.append(staging)
            continue
        if final_directory.is_dir():
            try:
                file_storage.cleanup_import(meeting_id)
                removed_incomplete += 1
            except OSError:
                log.exception("Failed removing redundant staged import meeting_id=%s", meeting_id)
                deferred.append(staging)
            continue

        expected_final = Path(meeting.audio_path)
        expected_staged = staging / expected_final.name
        try:
            expected_parent = final_directory.resolve(strict=False)
            configured_parent = expected_final.parent.resolve(strict=False)
            staged_entries = tuple(staging.iterdir())
        except OSError:
            log.exception("Failed inspecting committed staged import meeting_id=%s", meeting_id)
            deferred.append(staging)
            continue
        structurally_valid = (
            configured_parent == expected_parent
            and expected_final.name.startswith("source_audio.")
            and expected_staged.is_file()
            and staged_entries == (expected_staged,)
        )
        if not structurally_valid:
            try:
                file_storage.cleanup_import(meeting_id)
                removed_incomplete += 1
            except OSError:
                log.exception("Failed removing malformed staged import meeting_id=%s", meeting_id)
                deferred.append(staging)
            continue
        try:
            metadata_service.inspect(expected_staged)
            file_storage.finalize_import(meeting_id)
            finalized_imports += 1
            log.info("Recovered committed staged import meeting_id=%s", meeting_id)
        except MediaValidationError as error:
            if error.failure == MediaValidationFailure.INSPECTOR_UNAVAILABLE:
                log.warning("Deferred staged import verification meeting_id=%s", meeting_id)
                deferred.append(staging)
            else:
                try:
                    file_storage.cleanup_import(meeting_id)
                    removed_incomplete += 1
                except OSError:
                    log.exception("Failed removing invalid staged import meeting_id=%s", meeting_id)
                    deferred.append(staging)
        except OSError:
            log.exception("Failed finalizing committed staged import meeting_id=%s", meeting_id)
            deferred.append(staging)

    orphan_ids = (
        set(file_storage.finalized_meeting_ids())
        | set(file_storage.meeting_cache_ids())
    ) - database_ids
    for meeting_id in orphan_ids:
        failed = file_storage.delete_meeting_files(meeting_id)
        if failed:
            deferred.extend(failed)
        else:
            removed_orphans += 1
            log.info("Removed orphaned meeting storage meeting_id=%s", meeting_id)

    result = StorageRecoveryResult(
        finalized_imports=finalized_imports,
        removed_incomplete_imports=removed_incomplete,
        removed_orphan_directories=removed_orphans,
        deferred_paths=tuple(dict.fromkeys(deferred)),
    )
    log.info(
        "Meeting storage recovery finalized=%s incomplete_removed=%s "
        "orphans_removed=%s deferred=%s",
        result.finalized_imports,
        result.removed_incomplete_imports,
        result.removed_orphan_directories,
        len(result.deferred_paths),
    )
    return result
