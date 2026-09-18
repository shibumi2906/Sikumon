"""Explicit real-Hebrew Phase 4 validation; intentionally outside normal pytest."""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from PySide6.QtWidgets import QApplication

from sikumon.application.meeting_service import MeetingService
from sikumon.application.transcription_service import TranscriptionService
from sikumon.database.db import create_session_factory, create_sqlite_engine
from sikumon.database.migrations import apply_migrations
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import TranscriptionStatus
from sikumon.services.audio.metadata import AudioMetadataService
from sikumon.services.transcription.faster_whisper_ivrit import FasterWhisperIvritProvider
from sikumon.services.transcription.model_manager import ModelAvailability, ModelManager
from sikumon.storage.file_storage import MeetingFileStorage
from sikumon.storage.paths import ApplicationPaths
from sikumon.ui.transcript_view import TranscriptView

HEBREW_PATTERN = re.compile(r"[\u0590-\u05ff]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the separate real-Hebrew Sikumon Phase 4 validation."
    )
    parser.add_argument("audio", type=Path, help="Path to a genuine Hebrew recording")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    validation_started = time.monotonic()
    args = parse_args()
    source = args.audio.resolve()
    if not source.is_file():
        raise SystemExit(f"Audio file does not exist: {source}")

    real_paths = ApplicationPaths.resolve()
    model_manager = ModelManager(real_paths)
    if model_manager.availability != ModelAvailability.AVAILABLE:
        raise SystemExit("The verified Ivrit.ai model is not available in Sikumon storage")

    with TemporaryDirectory(prefix="sikumon-real-stt-") as temporary:
        paths = ApplicationPaths.resolve(Path(temporary))
        paths.ensure_directories()
        engine = create_sqlite_engine(paths.database)
        apply_migrations(engine)
        repository = MeetingRepository(create_session_factory(engine))
        metadata = AudioMetadataService()
        meeting_service = MeetingService(
            repository,
            metadata,
            MeetingFileStorage(paths),
            logging.getLogger("sikumon.real_validation"),
        )
        meeting = meeting_service.import_meeting(source, "בדיקת תמלול אמיתית")
        provider = FasterWhisperIvritProvider(model_manager.model_directory)
        transcription = TranscriptionService(repository, model_manager, provider)
        started = time.monotonic()
        result = transcription.execute(
            transcription.prepare(meeting.id), threading.Event()
        )
        wall_seconds = time.monotonic() - started
        before_restart = repository.get(meeting.id)
        if before_restart is None:
            raise SystemExit("Persisted transcript was unavailable before restart")
        ids_before_restart = [segment.id for segment in before_restart.transcript_segments]
        engine.dispose()

        restarted_engine = create_sqlite_engine(paths.database)
        apply_migrations(restarted_engine)
        restarted_repository = MeetingRepository(
            create_session_factory(restarted_engine)
        )
        restarted = restarted_repository.get(meeting.id)
        if restarted is None:
            raise SystemExit("Persisted meeting did not survive repository restart")
        details = MeetingService(
            restarted_repository,
            metadata,
            MeetingFileStorage(paths),
        ).get_meeting(meeting.id)
        if details is None:
            raise SystemExit("Persisted transcript could not be reloaded")

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication(sys.argv[:1])
        view = TranscriptView()
        view.set_segments(details.transcript_segments)
        app.processEvents()

        texts = [segment.text for segment in details.transcript_segments]
        ids_after_restart = [str(segment.id) for segment in details.transcript_segments]
        positions = [segment.position for segment in details.transcript_segments]
        has_hebrew = any(HEBREW_PATTERN.search(text) for text in texts)
        timestamps_plausible = all(
            segment.start_time_ms >= 0
            and segment.end_time_ms >= segment.start_time_ms
            for segment in details.transcript_segments
        )
        audio_duration = meeting.audio_duration_seconds or 0.0
        real_time_factor = wall_seconds / audio_duration if audio_duration > 0 else None
        rendered_segment_count = len(view.segment_editors)
        view.close()
        view.deleteLater()
        app.processEvents()
        restarted_engine.dispose()
        total_wall_seconds = time.monotonic() - validation_started
        print(f"audio_duration_seconds={audio_duration:.3f}")
        print(
            "model_load_seconds="
            + (
                f"{provider.last_model_load_seconds:.3f}"
                if provider.last_model_load_seconds is not None
                else "unknown"
            )
        )
        print(f"transcription_wall_seconds={wall_seconds:.3f}")
        print(f"total_validation_wall_seconds={total_wall_seconds:.3f}")
        print(f"segment_count={result.segment_count}")
        print(
            "real_time_factor="
            + (f"{real_time_factor:.3f}" if real_time_factor is not None else "unknown")
        )
        print(f"hebrew_characters_detected={has_hebrew}")
        print(f"timestamps_plausible={timestamps_plausible}")
        print(f"persisted_after_restart={len(details.transcript_segments) > 0}")
        print(f"stable_ids_after_restart={ids_after_restart == ids_before_restart}")
        print(
            "ids_are_uuids="
            f"{all(str(UUID(value)) == value for value in ids_after_restart)}"
        )
        print(f"positions_ordered={positions == list(range(len(positions)))}")
        print(f"transcript_revision={details.transcript_revision}")
        print(
            "transcription_status_completed="
            f"{details.transcription_status == TranscriptionStatus.COMPLETED}"
        )
        print(f"rendered_segment_count={rendered_segment_count}")
        print("--- transcript for qualitative review ---")
        for segment in details.transcript_segments:
            print(
                f"[{segment.position}] [{segment.start_time_ms}-{segment.end_time_ms}] "
                f"id={segment.id} {segment.text}"
            )
        return 0 if has_hebrew and timestamps_plausible and texts else 1


if __name__ == "__main__":
    raise SystemExit(main())
