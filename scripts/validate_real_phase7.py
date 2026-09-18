"""Validate the real persisted HCSH001 analysis through the Phase 7 Qt UI."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from sikumon.application.analysis_controller import AnalysisController
from sikumon.application.analysis_service import MeetingAnalysisService
from sikumon.application.meeting_service import MeetingService
from sikumon.application.model_management import ModelManagementController
from sikumon.application.transcript_edit_service import TranscriptEditService
from sikumon.application.transcription_controller import TranscriptionController
from sikumon.application.transcription_service import TranscriptionService
from sikumon.config.constants import DEFAULT_ANALYSIS_MODEL
from sikumon.database.db import create_session_factory, create_sqlite_engine
from sikumon.database.migrations import apply_migrations
from sikumon.database.repositories import MeetingRepository
from sikumon.security.credentials import KeyringCredentialStore
from sikumon.services.analysis.openai_provider import OpenAIAnalysisProviderFactory
from sikumon.services.audio.metadata import AudioMetadataService
from sikumon.services.transcription.faster_whisper_ivrit import FasterWhisperIvritProvider
from sikumon.services.transcription.model_manager import ModelManager
from sikumon.storage.file_storage import MeetingFileStorage
from sikumon.storage.paths import ApplicationPaths
from sikumon.ui.main_window import MainWindow


def build_window(paths: ApplicationPaths) -> tuple[MainWindow, object]:
    engine = create_sqlite_engine(paths.database)
    apply_migrations(engine)
    repository = MeetingRepository(create_session_factory(engine))
    meeting_service = MeetingService(
        repository,
        AudioMetadataService(),
        MeetingFileStorage(paths),
    )
    model_manager = ModelManager(paths)
    model_controller = ModelManagementController(model_manager)
    transcription_controller = TranscriptionController(
        TranscriptionService(
            repository,
            model_manager,
            FasterWhisperIvritProvider(model_manager.model_directory),
        )
    )
    credentials = KeyringCredentialStore()
    analysis_controller = AnalysisController(
        MeetingAnalysisService(
            repository,
            credentials,
            OpenAIAnalysisProviderFactory(DEFAULT_ANALYSIS_MODEL),
        )
    )
    return (
        MainWindow(
            meeting_service,
            paths,
            model_controller,
            transcription_controller,
            TranscriptEditService(repository),
            analysis_controller,
            credentials,
        ),
        engine,
    )


def validate_window(window: MainWindow, app: QApplication) -> dict[str, object]:
    meetings = window._meeting_service.list_meetings()
    item = next((meeting for meeting in meetings if meeting.title == "HCSH001"), None)
    if item is None:
        raise RuntimeError("Persisted HCSH001 meeting is unavailable")
    window.meeting_view.show_meeting(item.id)
    window.show()
    app.processEvents()
    view = window.meeting_view
    buttons = tuple(view.tasks_view.evidence_buttons)
    navigation_results: list[bool] = []
    for button in buttons:
        expected_id = button.segment_id
        button.click()
        app.processEvents()
        editor = view.transcript_view.editor_for_segment(expected_id)
        navigation_results.append(
            view.tabs.currentWidget() is view.transcript_view
            and view.transcript_view.highlighted_segment_id == expected_id
            and editor is not None
            and editor.hasFocus()
        )
        view.tabs.setCurrentWidget(view.tasks_view)
        app.processEvents()
    result = {
        "meeting_id": item.id,
        "summary_displayed": bool(view.summary_view.summary_label.text().strip()),
        "summary_rtl": view.summary_view.summary_label.layoutDirection().name
        == "RightToLeft",
        "decisions_empty_state_displayed": (
            "לא זוהו החלטות" in view.decisions_view.empty_label.text()
        ),
        "task_count_displayed": len(view.tasks_view.item_cards),
        "evidence_controls_displayed": len(buttons),
        "evidence_navigation_success": bool(buttons) and all(navigation_results),
        "correct_segment_reached": bool(buttons) and all(navigation_results),
        "highlight_success": bool(buttons) and all(navigation_results),
        "optional_fields_omitted": not view.tasks_view.findChildren(
            type(view.title_label), "analysisAssignee"
        )
        and not view.tasks_view.findChildren(type(view.title_label), "analysisDeadline"),
    }
    window.close()
    app.processEvents()
    return result


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    paths = ApplicationPaths.resolve()
    first_window, first_engine = build_window(paths)
    first = validate_window(first_window, app)
    first_engine.dispose()
    second_window, second_engine = build_window(paths)
    second = validate_window(second_window, app)
    second_engine.dispose()
    reload_succeeded = (
        first["meeting_id"] == second["meeting_id"]
        and second["summary_displayed"] is True
        and second["task_count_displayed"] == 2
        and second["evidence_navigation_success"] is True
    )
    for key, value in first.items():
        print(f"{key}={value}")
    print(f"restart_reload_display_success={reload_succeeded}")
    return 0 if all(
        (
            first["summary_displayed"],
            first["summary_rtl"],
            first["decisions_empty_state_displayed"],
            first["task_count_displayed"] == 2,
            first["evidence_controls_displayed"] == 4,
            first["evidence_navigation_success"],
            first["optional_fields_omitted"],
            reload_succeeded,
        )
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
