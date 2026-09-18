import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Signal

import sikumon
from sikumon.application.analysis_controller import AnalysisController
from sikumon.application.analysis_service import MeetingAnalysisService
from sikumon.application.meeting_service import MeetingService
from sikumon.application.model_management import ModelManagementController
from sikumon.application.transcript_edit_service import (
    TranscriptEditService,
    TranscriptSaveError,
)
from sikumon.application.transcription_controller import TranscriptionController
from sikumon.application.transcription_service import (
    CompletedTranscription,
    PreparedTranscription,
)
from sikumon.config.settings import ApplicationSettings
from sikumon.database.db import create_session_factory, create_sqlite_engine
from sikumon.database.migrations import apply_migrations
from sikumon.database.repositories import MeetingRepository
from sikumon.domain.enums import AnalysisOperationStatus, TranscriptionStatus
from sikumon.domain.transcript import TranscriptSegmentDraft
from sikumon.main import main
from sikumon.services.analysis.provider import (
    AnalysisProviderError,
    AnalysisProviderRequest,
    AnalysisProviderResult,
)
from sikumon.services.audio.metadata import AudioMetadataService
from sikumon.services.transcription.model_manager import (
    REQUIRED_MODEL_FILES,
    DownloadResult,
    ModelAvailability,
    ModelManager,
    VerificationVersions,
)
from sikumon.storage.file_storage import MeetingFileStorage
from sikumon.storage.paths import ApplicationPaths
from sikumon.ui.main_window import MainWindow
from sikumon.ui.meeting_view import UnsavedTranscriptDecision
from sikumon.ui.new_meeting_dialog import NewMeetingDialog
from sikumon.ui.settings_dialog import SettingsDialog


class FakeModelController(QObject):
    state_changed = Signal(object)
    progress_changed = Signal(object)
    error_changed = Signal(str)
    operation_finished = Signal()

    def __init__(self, model_directory: Path) -> None:
        super().__init__()
        self.availability = ModelAvailability.MISSING
        self.model_directory = str(model_directory)
        self.error_message = None
        self.started = 0
        self.cancelled = 0

    @property
    def is_active(self) -> bool:
        return self.availability in (
            ModelAvailability.DOWNLOADING,
            ModelAvailability.VERIFYING,
        )

    def start_download(self) -> None:
        self.started += 1
        self.availability = ModelAvailability.DOWNLOADING
        self.state_changed.emit(self.availability)

    def cancel_download(self) -> None:
        self.cancelled += 1


class FakeTranscriptionController(QObject):
    state_changed = Signal(str, object)
    progress_changed = Signal(str, object)
    succeeded = Signal(str)
    failed = Signal(str, str)
    cancelled = Signal(str)
    operation_finished = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.active_meeting_id = None
        self.started: list[str] = []
        self.cancel_requests = 0

    def start_transcription(self, meeting_id: str) -> None:
        self.started.append(meeting_id)
        self.active_meeting_id = meeting_id
        self.state_changed.emit(meeting_id, TranscriptionStatus.RUNNING)

    def cancel_transcription(self) -> None:
        self.cancel_requests += 1


class FakeCredentials:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def get_api_key(self) -> str | None:
        return self.api_key

    def set_api_key(self, api_key: str) -> None:
        self.api_key = api_key

    def delete_api_key(self) -> None:
        self.api_key = None


class SingleProviderFactory:
    def __init__(self, provider) -> None:
        self.provider = provider

    def create(self, api_key: str):
        assert api_key
        return self.provider


def test_package_imports() -> None:
    assert sikumon.__version__
    assert "faster_whisper" not in sys.modules
    assert "ctranslate2" not in sys.modules
    assert "openai" not in sys.modules


def test_database_and_empty_ui_construct(qapp, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QLabel

    paths = ApplicationPaths.resolve(tmp_path / "app-data")
    paths.ensure_directories()
    engine = create_sqlite_engine(paths.database)
    apply_migrations(engine)
    repository = MeetingRepository(create_session_factory(engine))
    service = MeetingService(
        repository,
        AudioMetadataService(),
        MeetingFileStorage(paths),
    )

    model_controller = FakeModelController(paths.models / "ivrit-whisper")
    window = MainWindow(
        service,
        paths,
        model_controller,
        FakeTranscriptionController(),
        TranscriptEditService(repository),
    )
    settings = SettingsDialog(paths, model_controller)
    window.load_meetings()
    qapp.processEvents()

    assert window.windowTitle() == "Sikumon"
    assert window.meeting_list.empty_state.isVisibleTo(window.meeting_list)
    assert window.meeting_list.list_widget.count() == 0
    assert settings.windowTitle() == "הגדרות"
    assert window.meeting_list.layoutDirection().name == "RightToLeft"
    assert window.meeting_view.layoutDirection().name == "RightToLeft"
    assert settings.layoutDirection().name == "RightToLeft"
    technical_labels = [
        label
        for label in settings.findChildren(QLabel)
        if "ivrit-ai/" in label.text() or str(paths.root) in label.text()
    ]
    assert technical_labels
    assert all(label.layoutDirection().name == "LeftToRight" for label in technical_labels)

    settings.close()
    window.close()
    engine.dispose()


def test_transcript_can_be_copied_and_exported_from_meeting_view(
    qapp, phase2_app, make_wav, tmp_path: Path, monkeypatch
) -> None:
    paths, repository, _, service = phase2_app
    meeting = service.import_meeting(make_wav("export.wav"), "ישיבת צוות")
    repository.replace_transcript(
        meeting.id,
        (
            TranscriptSegmentDraft(uuid4(), 0, 1_234, 3_456, "שלום לכולם"),
            TranscriptSegmentDraft(uuid4(), 1, 5_000, 7_000, "נסיים מחר"),
        ),
    )
    window = MainWindow(
        service,
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        FakeTranscriptionController(),
        TranscriptEditService(repository),
    )
    window.meeting_view.show_meeting(meeting.id)
    window.show()
    qapp.processEvents()

    window.meeting_view.transcript_view.copy_button.click()
    assert "שלום לכולם" in qapp.clipboard().text()
    assert "[00:00:01]" in qapp.clipboard().text()

    destination = tmp_path / "exported.srt"
    monkeypatch.setattr(
        "sikumon.ui.meeting_view.QFileDialog.getSaveFileName",
        lambda *args: (str(destination), "כתוביות SubRip (*.srt)"),
    )
    window.meeting_view.transcript_view.export_button.click()
    qapp.processEvents()

    exported = destination.read_text(encoding="utf-8-sig")
    assert "00:00:01,234 --> 00:00:03,456" in exported
    assert "שלום לכולם" in exported
    window.close()


def test_new_meeting_dialog_constructs_and_imports_once(
    qapp, phase2_app, make_wav
) -> None:
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QDialog

    _, repository, _, service = phase2_app
    source = make_wav("meeting recording.wav")
    dialog = NewMeetingDialog(service)
    dialog.set_source_path(source)

    assert dialog.title_edit.text() == "meeting recording"
    assert dialog.path_label.layoutDirection().name == "LeftToRight"

    event_loop = QEventLoop()
    dialog.finished.connect(event_loop.quit)
    dialog.show()
    dialog._start_import()
    dialog._start_import()
    QTimer.singleShot(5_000, event_loop.quit)
    event_loop.exec()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.imported_meeting_id is not None
    assert len(repository.list()) == 1


def test_successful_import_refreshes_list_and_confirmed_delete_removes_it(
    qapp, phase2_app, make_wav, monkeypatch
) -> None:
    paths, repository, _, service = phase2_app
    source = make_wav("refresh.wav")
    window = MainWindow(
        service,
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        FakeTranscriptionController(),
        TranscriptEditService(repository),
    )

    class SuccessfulImportDialog:
        def __init__(self, meeting_service, parent) -> None:
            self.imported_meeting_id = meeting_service.import_meeting(
                source, "פגישת רענון"
            ).id

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        "sikumon.ui.main_window.NewMeetingDialog", SuccessfulImportDialog
    )
    window._open_new_meeting()
    qapp.processEvents()

    assert window.meeting_list.list_widget.count() == 1
    assert window.meeting_view.title_label.text() == "פגישת רענון"
    imported_id = repository.list()[0].id

    monkeypatch.setattr(window, "_confirm_deletion", lambda: True)
    window._delete_meeting(imported_id)

    assert window.meeting_list.list_widget.count() == 0
    assert repository.get(imported_id) is None
    window.close()


def test_real_entrypoint_completes_startup_sequence(qapp, tmp_path: Path) -> None:
    from PySide6.QtCore import QTimer

    data_root = tmp_path / "entrypoint-data"
    QTimer.singleShot(100, qapp.quit)

    assert main(ApplicationSettings(data_root=data_root)) == 0
    assert (data_root / "sikumon.db").is_file()
    assert (data_root / "logs" / "sikumon.log").is_file()


def test_settings_model_states_actions_and_cancellation(qapp, tmp_path: Path) -> None:
    paths = ApplicationPaths.resolve(tmp_path / "settings-data")
    paths.ensure_directories()
    controller = FakeModelController(paths.models / "ivrit-whisper")
    dialog = SettingsDialog(paths, controller)
    dialog.show()
    qapp.processEvents()

    assert "אינו מותקן" in dialog.model_status_label.text()
    assert dialog.model_action_button.text() == "הורד מודל"
    dialog.model_action_button.click()
    qapp.processEvents()
    assert controller.started == 1
    assert "מוריד" in dialog.model_status_label.text()
    assert not dialog.model_cancel_button.isHidden()

    dialog.model_cancel_button.click()
    assert controller.cancelled == 1

    controller.availability = ModelAvailability.VERIFYING
    controller.state_changed.emit(controller.availability)
    qapp.processEvents()
    assert "מאמת" in dialog.model_status_label.text()

    controller.availability = ModelAvailability.AVAILABLE
    controller.state_changed.emit(controller.availability)
    qapp.processEvents()
    assert "מותקן ומאומת" in dialog.model_status_label.text()
    assert dialog.model_action_button.isHidden()

    controller.availability = ModelAvailability.FAILED
    controller.state_changed.emit(controller.availability)
    controller.error_changed.emit("שגיאת רשת")
    qapp.processEvents()
    assert dialog.model_action_button.text() == "נסה שוב"
    assert dialog.model_error_label.text() == "שגיאת רשת"
    dialog.close()


def test_settings_openai_credential_controls_are_masked_and_secure(qapp, tmp_path: Path) -> None:
    paths = ApplicationPaths.resolve(tmp_path / "credential-settings")
    paths.ensure_directories()
    credentials = FakeCredentials()
    dialog = SettingsDialog(
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        credentials,
    )
    dialog.show()
    qapp.processEvents()

    assert dialog.api_key_edit.echoMode().name == "Password"
    assert "לא מוגדר" in dialog.credential_status_label.text()
    dialog.api_key_edit.setText("sk-secret-test")
    dialog.save_api_key_button.click()
    qapp.processEvents()

    assert credentials.api_key == "sk-secret-test"
    assert dialog.api_key_edit.text() == ""
    assert "sk-secret-test" not in dialog.credential_status_label.text()
    assert "מאובטח" in dialog.credential_status_label.text()
    dialog.clear_api_key_button.click()
    assert credentials.api_key is None
    dialog.close()


def test_analysis_action_runs_off_ui_thread_prevents_duplicate_and_refreshes(
    qapp, phase2_app, make_wav
) -> None:
    paths, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("analysis-ui.wav"), "ניתוח UI")
    segment_id = uuid4()
    repository.replace_transcript(
        meeting.id,
        (TranscriptSegmentDraft(segment_id, 0, 0, 1_000, "הוחלט להתקדם"),),
    )
    provider_threads: list[bool] = []
    provider_calls = 0

    class DelayedAnalysisProvider:
        def analyze(self, request: AnalysisProviderRequest) -> AnalysisProviderResult:
            nonlocal provider_calls
            provider_calls += 1
            provider_threads.append(QThread.currentThread() is qapp.thread())
            time.sleep(0.15)
            return AnalysisProviderResult(
                {
                    "summary": "הוחלט להתקדם.",
                    "decisions": [
                        {
                            "title": "להתקדם",
                            "description": None,
                            "evidence": {"segment_ids": [str(segment_id)]},
                        }
                    ],
                    "action_items": [],
                }
            )

    credentials = FakeCredentials("sk-test")
    analysis_service = MeetingAnalysisService(
        repository,
        credentials,
        SingleProviderFactory(DelayedAnalysisProvider()),
    )
    analysis_controller = AnalysisController(analysis_service)
    window = MainWindow(
        meeting_service,
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        FakeTranscriptionController(),
        TranscriptEditService(repository),
        analysis_controller,
        credentials,
    )
    window.meeting_view.show_meeting(meeting.id)
    window.show()
    qapp.processEvents()

    assert not window.meeting_view.analyze_button.isHidden()
    assert window.meeting_view.analyze_button.isEnabled()
    window.meeting_view.analyze_button.click()
    window.meeting_view.analyze_button.click()
    assert window.meeting_view.analysis_progress.isVisible()
    assert not window.meeting_view.analyze_button.isEnabled()

    loop = QEventLoop()
    ui_timer_fired: list[bool] = []
    QTimer.singleShot(20, lambda: ui_timer_fired.append(True))
    analysis_controller.operation_finished.connect(loop.quit)
    QTimer.singleShot(2_000, loop.quit)
    loop.exec()
    qapp.processEvents()

    reloaded = repository.get(meeting.id)
    assert provider_calls == 1
    assert provider_threads == [False]
    assert ui_timer_fired == [True]
    assert reloaded is not None
    assert reloaded.current_analysis is not None
    assert reloaded.analysis_operation_status == AnalysisOperationStatus.COMPLETED
    assert not window.meeting_view.analysis_progress.isVisible()
    assert window.meeting_view.analyze_button.isEnabled()
    assert window.meeting_view.summary_view.summary_label.text() == "הוחלט להתקדם."
    assert len(window.meeting_view.decisions_view.item_cards) == 1
    assert "לא זוהו משימות" in window.meeting_view.tasks_view.empty_label.text()
    window.close()


def test_analysis_missing_credentials_and_failure_keep_previous_result_visible(
    qapp, phase2_app, make_wav
) -> None:
    paths, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("analysis-fail.wav"), "כשל ניתוח")
    segment_id = uuid4()
    repository.replace_transcript(
        meeting.id,
        (TranscriptSegmentDraft(segment_id, 0, 0, 1_000, "הוחלט להתקדם"),),
    )
    successful = MeetingAnalysisService(
        repository,
        FakeCredentials("sk-test"),
        SingleProviderFactory(
            type(
                "SuccessfulProvider",
                (),
                {
                    "analyze": lambda self, request: AnalysisProviderResult(
                        {
                            "summary": "סיכום קודם",
                            "decisions": [],
                            "action_items": [],
                        }
                    )
                },
            )()
        ),
    )
    previous_id = successful.execute(successful.prepare(meeting.id)).analysis_id
    persisted = repository.get(meeting.id)
    assert persisted is not None
    TranscriptEditService(repository).save(
        meeting.id,
        1,
        {persisted.transcript_segments[0].id: "תמלול מתוקן לאחר הניתוח הקודם"},
    )

    class FailingProvider:
        def analyze(self, request: AnalysisProviderRequest) -> AnalysisProviderResult:
            raise AnalysisProviderError("offline")

    missing_credentials = FakeCredentials()
    controller = AnalysisController(
        MeetingAnalysisService(
            repository,
            missing_credentials,
            SingleProviderFactory(FailingProvider()),
        )
    )
    window = MainWindow(
        meeting_service,
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        FakeTranscriptionController(),
        TranscriptEditService(repository),
        controller,
        missing_credentials,
    )
    window.meeting_view.show_meeting(meeting.id)
    assert window.meeting_view.summary_view.summary_label.text() == "סיכום קודם"
    assert not window.meeting_view.outdated_banner.isHidden()
    assert not window.meeting_view.analyze_button.isEnabled()
    assert "נדרש מפתח" in window.meeting_view.analysis_message.text()

    missing_credentials.set_api_key("sk-test")
    window.meeting_view.refresh_credentials()
    loop = QEventLoop()
    controller.operation_finished.connect(loop.quit)
    window.meeting_view.analyze_button.click()
    QTimer.singleShot(2_000, loop.quit)
    loop.exec()

    reloaded = repository.get(meeting.id)
    assert reloaded is not None
    assert reloaded.current_analysis_id == previous_id
    assert reloaded.analysis_operation_status == AnalysisOperationStatus.FAILED
    assert window.meeting_view.analysis_message.text()
    assert window.meeting_view.summary_view.summary_label.text() == "סיכום קודם"
    assert not window.meeting_view.outdated_banner.isHidden()
    window.close()


def test_model_controller_runs_download_and_verification_off_ui_thread(
    qapp, tmp_path: Path
) -> None:
    paths = ApplicationPaths.resolve(tmp_path / "worker-data")
    paths.ensure_directories()
    ran_on_ui_thread: list[bool] = []

    class ThreadRecordingDownloader:
        def download(
            self,
            repository_id: str,
            revision: str | None,
            destination: Path,
            cache_directory: Path,
            cancellation: threading.Event,
            progress,
        ) -> DownloadResult:
            ran_on_ui_thread.append(QThread.currentThread() is qapp.thread())
            destination.mkdir(parents=True, exist_ok=True)
            for filename in REQUIRED_MODEL_FILES:
                (destination / filename).write_bytes(b"model-data")
            return DownloadResult("worker-commit", len(REQUIRED_MODEL_FILES))

    class ThreadRecordingVerifier:
        def verify(self, model_directory: Path) -> VerificationVersions:
            ran_on_ui_thread.append(QThread.currentThread() is qapp.thread())
            return VerificationVersions("1.2.1", "4.8.1")

    manager = ModelManager(paths, ThreadRecordingDownloader(), ThreadRecordingVerifier())
    controller = ModelManagementController(manager)
    event_loop = QEventLoop()
    controller.operation_finished.connect(event_loop.quit)
    controller.start_download()
    QTimer.singleShot(5_000, event_loop.quit)
    event_loop.exec()

    assert ran_on_ui_thread == [False, False]
    assert controller.availability == ModelAvailability.AVAILABLE


def test_transcription_ui_capabilities_cancel_and_read_only_display(
    qapp, phase2_app, make_wav
) -> None:
    paths, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("ui-hebrew.wav", 10), "תצוגה")
    model = FakeModelController(paths.models / "ivrit-whisper")
    transcription = FakeTranscriptionController()
    window = MainWindow(
        meeting_service,
        paths,
        model,
        transcription,
        TranscriptEditService(repository),
    )
    window.meeting_view.show_meeting(meeting.id)
    window.show()
    qapp.processEvents()

    assert not window.meeting_view.transcribe_button.isHidden()
    assert not window.meeting_view.transcribe_button.isEnabled()

    model.availability = ModelAvailability.AVAILABLE
    model.state_changed.emit(model.availability)
    qapp.processEvents()
    assert window.meeting_view.transcribe_button.isEnabled()

    window.meeting_view.transcribe_button.click()
    qapp.processEvents()
    assert transcription.started == [meeting.id]
    assert not window.meeting_view.cancel_transcription_button.isHidden()
    assert not window.meeting_view.delete_button.isEnabled()
    window.meeting_view.cancel_transcription_button.click()
    assert transcription.cancel_requests == 1

    repository.replace_transcript(
        meeting.id,
        (
            TranscriptSegmentDraft(uuid4(), 0, 2_000, 4_000, "בוקר טוב"),
            TranscriptSegmentDraft(uuid4(), 1, 5_000, 8_000, "מתחילים את הפגישה"),
        ),
    )
    transcription.active_meeting_id = None
    transcription.operation_finished.emit(meeting.id)
    qapp.processEvents()

    view = window.meeting_view.transcript_view
    assert [label.text() for label in view.timestamp_labels] == ["00:02", "00:05"]
    assert [editor.toPlainText() for editor in view.segment_editors] == [
        "בוקר טוב",
        "מתחילים את הפגישה",
    ]
    assert all(editor.layoutDirection().name == "RightToLeft" for editor in view.segment_editors)
    assert all(label.layoutDirection().name == "LeftToRight" for label in view.timestamp_labels)

    Path(meeting.audio_path).unlink()
    window.meeting_view.show_meeting(meeting.id)
    assert not window.meeting_view.transcribe_button.isEnabled()
    window.close()


def test_transcription_controller_keeps_qt_event_loop_responsive(qapp, tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    ui_thread_checks: list[bool] = []

    class DelayedService:
        def prepare(self, meeting_id: str) -> PreparedTranscription:
            return PreparedTranscription(meeting_id, audio, 1.0, False)

        def execute(self, prepared, cancellation, progress_callback=None):
            ui_thread_checks.append(QThread.currentThread() is qapp.thread())
            time.sleep(0.15)
            return CompletedTranscription(prepared.meeting_id, 1, 1, 0.15)

        def abort_prepared(self, prepared) -> None:
            pass

    controller = TranscriptionController(DelayedService())
    loop = QEventLoop()
    ui_timer_fired: list[bool] = []
    QTimer.singleShot(20, lambda: ui_timer_fired.append(True))
    controller.operation_finished.connect(loop.quit)
    controller.start_transcription("meeting-1")
    QTimer.singleShot(2_000, loop.quit)
    loop.exec()

    assert ui_timer_fired == [True]
    assert ui_thread_checks == [False]
    assert controller.active_meeting_id is None


def test_editing_and_successful_save_clear_dirty_state(qapp, phase2_app, make_wav) -> None:
    paths, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("edit-ui.wav"), "עריכת תמלול")
    repository.replace_transcript(
        meeting.id,
        (
            TranscriptSegmentDraft(uuid4(), 0, 500, 2_000, "שלום 123"),
            TranscriptSegmentDraft(uuid4(), 1, 2_500, 4_000, "פגישה עם Alice"),
        ),
    )
    before = repository.get(meeting.id)
    original_ids = [segment.id for segment in before.transcript_segments]
    edit_service = TranscriptEditService(repository)
    window = MainWindow(
        meeting_service,
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        FakeTranscriptionController(),
        edit_service,
    )
    window.meeting_view.show_meeting(meeting.id)
    view = window.meeting_view.transcript_view

    assert not view.is_dirty
    view.segment_editors[0].setPlainText("שלום 456, Bob!")
    qapp.processEvents()
    assert view.is_dirty
    assert view.save_button.isEnabled()
    view.save_button.click()
    qapp.processEvents()

    after = repository.get(meeting.id)
    assert not view.is_dirty
    assert not view.save_button.isEnabled()
    assert after.transcript_revision == 2
    assert after.transcript_segments[0].text == "שלום 456, Bob!"
    assert [segment.id for segment in after.transcript_segments] == original_ids
    window.close()


def test_failed_ui_save_keeps_edits_dirty(qapp, phase2_app, make_wav, monkeypatch) -> None:
    paths, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("failed-edit.wav"), "כשל שמירה")
    repository.replace_transcript(
        meeting.id,
        (TranscriptSegmentDraft(uuid4(), 0, 0, 1_000, "מקור"),),
    )
    edit_service = TranscriptEditService(repository)
    window = MainWindow(
        meeting_service,
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        FakeTranscriptionController(),
        edit_service,
    )
    window.meeting_view.show_meeting(meeting.id)
    editor = window.meeting_view.transcript_view.segment_editors[0]
    editor.setPlainText("תיקון שלא נשמר")
    monkeypatch.setattr(
        edit_service,
        "save",
        lambda *args, **kwargs: (_ for _ in ()).throw(TranscriptSaveError("כשל בדיקה")),
    )

    assert not window.meeting_view.save_transcript()
    assert window.meeting_view.transcript_view.is_dirty
    assert editor.toPlainText() == "תיקון שלא נשמר"
    assert window.meeting_view.transcription_message.text() == "כשל בדיקה"
    monkeypatch.setattr(
        window.meeting_view,
        "_ask_unsaved_changes",
        lambda: UnsavedTranscriptDecision.DISCARD,
    )
    window.close()


def test_dirty_meeting_switch_cancel_discard_and_save_paths(
    qapp, phase2_app, make_wav, monkeypatch
) -> None:
    paths, repository, _, meeting_service = phase2_app
    first = meeting_service.import_meeting(make_wav("first.wav"), "ראשונה")
    second = meeting_service.import_meeting(make_wav("second.wav"), "שנייה")
    for meeting, text_value in ((first, "ראשון"), (second, "שני")):
        repository.replace_transcript(
            meeting.id,
            (TranscriptSegmentDraft(uuid4(), 0, 0, 1_000, text_value),),
        )
    window = MainWindow(
        meeting_service,
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        FakeTranscriptionController(),
        TranscriptEditService(repository),
    )
    window.load_meetings()
    window._select_meeting(first.id)
    editor = window.meeting_view.transcript_view.segment_editors[0]
    editor.setPlainText("תיקון ראשון")

    monkeypatch.setattr(
        window.meeting_view,
        "_ask_unsaved_changes",
        lambda: UnsavedTranscriptDecision.CANCEL,
    )
    window._select_meeting(second.id)
    assert window.meeting_view.current_meeting_id == first.id
    assert window.meeting_view.transcript_view.is_dirty

    monkeypatch.setattr(
        window.meeting_view,
        "_ask_unsaved_changes",
        lambda: UnsavedTranscriptDecision.DISCARD,
    )
    window._select_meeting(second.id)
    assert window.meeting_view.current_meeting_id == second.id
    assert not window.meeting_view.transcript_view.is_dirty

    window._select_meeting(first.id)
    window.meeting_view.transcript_view.segment_editors[0].setPlainText("תיקון נשמר")
    monkeypatch.setattr(
        window.meeting_view,
        "_ask_unsaved_changes",
        lambda: UnsavedTranscriptDecision.SAVE,
    )
    window._select_meeting(second.id)
    saved = repository.get(first.id)
    assert window.meeting_view.current_meeting_id == second.id
    assert saved.transcript_segments[0].text == "תיקון נשמר"
    assert saved.transcript_revision == 2
    window.close()


def test_window_close_with_dirty_transcript_can_cancel_or_discard(
    qapp, phase2_app, make_wav, monkeypatch
) -> None:
    paths, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("close-edit.wav"), "סגירה")
    repository.replace_transcript(
        meeting.id,
        (TranscriptSegmentDraft(uuid4(), 0, 0, 1_000, "מקור"),),
    )
    window = MainWindow(
        meeting_service,
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        FakeTranscriptionController(),
        TranscriptEditService(repository),
    )
    window.meeting_view.show_meeting(meeting.id)
    window.meeting_view.transcript_view.segment_editors[0].setPlainText("לא נשמר")
    window.show()
    qapp.processEvents()

    monkeypatch.setattr(
        window.meeting_view,
        "_ask_unsaved_changes",
        lambda: UnsavedTranscriptDecision.CANCEL,
    )
    assert not window.close()
    assert window.isVisible()

    monkeypatch.setattr(
        window.meeting_view,
        "_ask_unsaved_changes",
        lambda: UnsavedTranscriptDecision.DISCARD,
    )
    assert window.close()
    qapp.processEvents()
    assert not window.isVisible()


def test_phase7_persisted_analysis_renders_and_evidence_navigates_by_segment_id(
    qapp, phase2_app, make_wav
) -> None:
    paths, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("phase7.wav", 15), "ממשק ניתוח")
    segment_ids = [uuid4() for _ in range(12)]
    repository.replace_transcript(
        meeting.id,
        tuple(
            TranscriptSegmentDraft(
                segment_id,
                position,
                position * 10_000,
                position * 10_000 + 2_000,
                f"מקטע תמלול מספר {position}",
            )
            for position, segment_id in enumerate(segment_ids)
        ),
    )

    class PresentationProvider:
        def analyze(self, request: AnalysisProviderRequest) -> AnalysisProviderResult:
            return AnalysisProviderResult(
                {
                    "summary": "זהו סיכום עברי שמוצג מתוך מסד הנתונים.",
                    "decisions": [],
                    "action_items": [
                        {
                            "title": "לטפל במסמך",
                            "description": None,
                            "assignee": None,
                            "deadline": None,
                            "evidence": {"segment_ids": [str(segment_ids[-1])]},
                        }
                    ],
                }
            )

    credentials = FakeCredentials("sk-test")
    service = MeetingAnalysisService(
        repository,
        credentials,
        SingleProviderFactory(PresentationProvider()),
    )
    service.execute(service.prepare(meeting.id))
    controller = AnalysisController(service)
    window = MainWindow(
        meeting_service,
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        FakeTranscriptionController(),
        TranscriptEditService(repository),
        controller,
        credentials,
    )
    window.meeting_view.show_meeting(meeting.id)
    window.show()
    qapp.processEvents()

    view = window.meeting_view
    assert "סיכום עברי" in view.summary_view.summary_label.text()
    assert "לא זוהו החלטות" in view.decisions_view.empty_label.text()
    assert len(view.tasks_view.item_cards) == 1
    assert len(view.tasks_view.evidence_buttons) == 1
    assert not view.tasks_view.findChildren(type(view.title_label), "analysisAssignee")
    assert not view.tasks_view.findChildren(type(view.title_label), "analysisDeadline")

    target_id = str(segment_ids[-1])
    target_editor = view.transcript_view.editor_for_segment(target_id)
    assert target_editor is not None
    target_editor.setPlainText("עריכה מקומית שלא נשמרה")
    view.tasks_view.evidence_buttons[0].click()
    qapp.processEvents()

    assert view.tabs.currentWidget() is view.transcript_view
    assert view.transcript_view.highlighted_segment_id == target_id
    assert target_editor.hasFocus()
    assert target_editor.toPlainText() == "עריכה מקומית שלא נשמרה"
    assert view.transcript_view.scroll_area.verticalScrollBar().value() > 0

    target_editor.setPlainText("מקטע תמלול מספר 11")
    qapp.processEvents()
    edited_texts = view.transcript_view.current_texts()
    edited_texts[str(segment_ids[0])] = "תיקון שמייצר ניתוח לא עדכני"
    TranscriptEditService(repository).save(meeting.id, 1, edited_texts)
    view.show_meeting(meeting.id)
    qapp.processEvents()
    assert view.outdated_banner.isVisible()
    assert view.reanalyze_button.isEnabled()
    assert "סיכום עברי" in view.summary_view.summary_label.text()

    other = meeting_service.import_meeting(make_wav("other-phase7.wav"), "פגישה אחרת")
    repository.replace_transcript(
        other.id,
        (TranscriptSegmentDraft(uuid4(), 0, 0, 1_000, "תמלול אחר"),),
    )
    view.show_meeting(other.id)
    assert "טרם נוצר" in view.summary_view.empty_label.text()
    assert not view.tasks_view.evidence_buttons
    window.close()


def test_missing_audio_keeps_transcript_and_analysis_visible_but_disables_transcription(
    qapp, phase2_app, make_wav
) -> None:
    paths, repository, _, meeting_service = phase2_app
    meeting = meeting_service.import_meeting(make_wav("missing-after.wav"), "שמע חסר")
    segment_id = uuid4()
    repository.replace_transcript(
        meeting.id,
        (TranscriptSegmentDraft(segment_id, 0, 0, 1_000, "תמלול בטוח"),),
    )

    class Provider:
        def analyze(self, request: AnalysisProviderRequest) -> AnalysisProviderResult:
            return AnalysisProviderResult(
                {"summary": "סיכום בטוח", "decisions": [], "action_items": []}
            )

    service = MeetingAnalysisService(
        repository,
        FakeCredentials("sk-test"),
        SingleProviderFactory(Provider()),
    )
    service.execute(service.prepare(meeting.id))
    Path(meeting.audio_path).unlink()
    window = MainWindow(
        meeting_service,
        paths,
        FakeModelController(paths.models / "ivrit-whisper"),
        FakeTranscriptionController(),
        TranscriptEditService(repository),
    )
    window.meeting_view.show_meeting(meeting.id)
    window.show()
    qapp.processEvents()

    assert window.meeting_view.status_label.text() == "קובץ ההקלטה חסר"
    assert not window.meeting_view.transcribe_button.isEnabled()
    assert window.meeting_view.transcript_view.segment_editors[0].toPlainText() == "תמלול בטוח"
    assert window.meeting_view.summary_view.summary_label.text() == "סיכום בטוח"
    assert window.meeting_view.delete_button.isEnabled()
    window.close()


def test_close_during_active_work_requires_confirmation_and_cancels_cooperatively(
    qapp, phase2_app, monkeypatch
) -> None:
    paths, repository, _, meeting_service = phase2_app
    model = FakeModelController(paths.models / "ivrit-whisper")
    transcription = FakeTranscriptionController()
    window = MainWindow(
        meeting_service,
        paths,
        model,
        transcription,
        TranscriptEditService(repository),
    )
    transcription.active_meeting_id = "active-meeting"
    window.show()
    qapp.processEvents()

    monkeypatch.setattr(window, "_confirm_active_shutdown", lambda active: False)
    assert not window.close()
    assert transcription.cancel_requests == 0
    assert window.isVisible()

    monkeypatch.setattr(window, "_confirm_active_shutdown", lambda active: True)
    assert not window.close()
    assert transcription.cancel_requests == 1
    assert window.isVisible()

    transcription.active_meeting_id = None
    transcription.operation_finished.emit("active-meeting")
    qapp.processEvents()
    assert not window.isVisible()


def test_close_during_model_download_requests_cancellation_and_waits_for_cleanup(
    qapp, phase2_app, monkeypatch
) -> None:
    paths, repository, _, meeting_service = phase2_app
    model = FakeModelController(paths.models / "ivrit-whisper")
    model.availability = ModelAvailability.DOWNLOADING
    window = MainWindow(
        meeting_service,
        paths,
        model,
        FakeTranscriptionController(),
        TranscriptEditService(repository),
    )
    monkeypatch.setattr(window, "_confirm_active_shutdown", lambda active: True)
    window.show()
    qapp.processEvents()

    assert not window.close()
    assert model.cancelled == 1
    model.availability = ModelAvailability.MISSING
    model.operation_finished.emit()
    qapp.processEvents()
    assert not window.isVisible()
