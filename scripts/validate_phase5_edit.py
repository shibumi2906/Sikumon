"""Manual Phase 5 edit/restart validation using the real Phase 4 transcript."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from PySide6.QtWidgets import QApplication

from sikumon.application.meeting_service import MeetingService
from sikumon.application.transcript_edit_service import TranscriptEditService
from sikumon.database.db import create_session_factory, create_sqlite_engine
from sikumon.database.migrations import apply_migrations
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import TranscriptionStatus
from sikumon.domain.transcript import TranscriptSegmentDraft
from sikumon.services.audio.metadata import AudioMetadataService
from sikumon.storage.file_storage import MeetingFileStorage
from sikumon.storage.paths import ApplicationPaths
from sikumon.ui.transcript_view import TranscriptView

MEDIA_DIRECTORY = Path(__file__).resolve().parents[1] / "test_media"
ORIGINAL = "זה מאני טיים. למה אני עף? צריכים הלוואה? במאני טיים, רק יסחקת."
CORRECTED = "זה מאני טיים. למה אני עף? צריכים הלוואה? במאני טיים, רק משחקת."


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    samples = tuple(
        path
        for path in MEDIA_DIRECTORY.rglob("*")
        if path.is_file() and path.suffix.lower() == ".mp3"
    )
    if len(samples) != 1:
        raise SystemExit(f"Expected exactly one MP3 in {MEDIA_DIRECTORY}, found {len(samples)}")
    source = samples[0]
    with TemporaryDirectory(
        prefix="sikumon-phase5-edit-", ignore_cleanup_errors=True
    ) as temporary:
        paths = ApplicationPaths.resolve(Path(temporary))
        paths.ensure_directories()
        engine = create_sqlite_engine(paths.database)
        apply_migrations(engine)
        repository = MeetingRepository(create_session_factory(engine))
        meeting_service = MeetingService(
            repository, AudioMetadataService(), MeetingFileStorage(paths)
        )
        meeting = meeting_service.import_meeting(source, "בדיקת עריכת תמלול")
        repository.replace_transcript(
            meeting.id,
            (
                TranscriptSegmentDraft(uuid4(), 0, 500, 5_900, ORIGINAL),
                TranscriptSegmentDraft(uuid4(), 1, 6_600, 7_200, "חופשה?"),
            ),
        )
        before = meeting_service.get_meeting(meeting.id)
        if before is None:
            raise SystemExit("Unable to load seeded Phase 4 transcript")
        original_metadata = {
            str(segment.id): (
                segment.position,
                segment.start_time_ms,
                segment.end_time_ms,
                segment.created_at,
            )
            for segment in before.transcript_segments
        }

        view = TranscriptView()
        view.set_segments(before.transcript_segments, before.transcript_revision)
        first_id = str(before.transcript_segments[0].id)
        editor = view.editor_for_segment(first_id)
        if editor is None:
            raise SystemExit("Unable to locate the first segment editor")
        editor.setPlainText(CORRECTED)
        if not view.is_dirty:
            raise SystemExit("Editor did not become dirty")
        snapshot = TranscriptEditService(repository).save(
            meeting.id, view.source_revision, view.current_texts()
        )
        view.set_segments(snapshot.segments, snapshot.revision)
        if view.is_dirty:
            raise SystemExit("Editor remained dirty after canonical reload")
        view.close()
        view.deleteLater()
        app.processEvents()
        engine.dispose()

        restarted_engine = create_sqlite_engine(paths.database)
        restarted_repository = MeetingRepository(
            create_session_factory(restarted_engine)
        )
        restarted = restarted_repository.get(meeting.id)
        if restarted is None:
            raise SystemExit("Edited transcript did not survive restart")
        for segment in restarted.transcript_segments:
            if (
                segment.position,
                segment.start_time_ms,
                segment.end_time_ms,
                segment.created_at,
            ) != original_metadata[segment.id]:
                raise SystemExit("Immutable segment metadata changed")
        print(f"meeting_id={meeting.id}")
        print(f"source={source}")
        print(f"edited_segment_id={first_id}")
        print(f"revision={restarted.transcript_revision}")
        print(
            "status_completed="
            f"{restarted.transcription_status == TranscriptionStatus.COMPLETED}"
        )
        restarted_ids = {segment.id for segment in restarted.transcript_segments}
        print(f"ids_stable={set(original_metadata) == restarted_ids}")
        print("timestamps_and_created_at_stable=True")
        corrected_text_persisted = restarted.transcript_segments[0].text == CORRECTED
        print(f"corrected_text_persisted={corrected_text_persisted}")
        print("restart_reload_succeeded=True")
        restarted_engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
