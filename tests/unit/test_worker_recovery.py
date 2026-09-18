from pathlib import Path
from types import SimpleNamespace

from sikumon.application.analysis_service import AnalysisOperationError
from sikumon.application.meeting_service import MeetingImportError
from sikumon.application.transcription_service import TranscriptionOperationError
from sikumon.services.transcription.model_manager import ModelManagementError
from sikumon.workers.analysis_worker import AnalysisWorker
from sikumon.workers.meeting_import_worker import MeetingImportWorker
from sikumon.workers.model_download_worker import ModelDownloadWorker
from sikumon.workers.transcription_worker import TranscriptionWorker


def test_unexpected_analysis_worker_exception_is_normalized_and_signalled(qapp) -> None:
    class Service:
        aborted = False

        def execute(self, prepared, cancellation):
            raise RuntimeError("unexpected")

        def abort_prepared(self, prepared) -> None:
            self.aborted = True

    service = Service()
    worker = AnalysisWorker(service, SimpleNamespace(meeting_id="meeting-1"), object())
    failures: list[object] = []
    finished: list[bool] = []
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert service.aborted
    assert len(failures) == 1
    assert isinstance(failures[0], AnalysisOperationError)
    assert finished == [True]


def test_unexpected_transcription_worker_exception_is_normalized_and_signalled(qapp) -> None:
    class Service:
        failed = False

        def execute(self, prepared, cancellation, progress):
            raise RuntimeError("unexpected")

        def fail_prepared(self, prepared) -> None:
            self.failed = True

    service = Service()
    worker = TranscriptionWorker(
        service,
        SimpleNamespace(meeting_id="meeting-1"),
        object(),
    )
    failures: list[object] = []
    finished: list[bool] = []
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert service.failed
    assert len(failures) == 1
    assert isinstance(failures[0], TranscriptionOperationError)
    assert finished == [True]


def test_unexpected_model_worker_exception_becomes_controlled_failure(qapp) -> None:
    controlled = ModelManagementError("כשל מבוקר")

    class Manager:
        normalized = False

        def download_and_verify(self, **kwargs):
            raise RuntimeError("unexpected")

        def normalize_unexpected_failure(self, error: Exception) -> ModelManagementError:
            self.normalized = True
            return controlled

    manager = Manager()
    worker = ModelDownloadWorker(manager)
    failures: list[object] = []
    finished: list[bool] = []
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert manager.normalized
    assert failures == [controlled]
    assert finished == [True]


def test_unexpected_import_worker_exception_is_hidden_from_user(qapp) -> None:
    class Service:
        def import_meeting(self, source: Path, title: str):
            raise RuntimeError("raw internal detail")

    worker = MeetingImportWorker(Service(), Path("recording.wav"), "פגישה")
    failures: list[object] = []
    finished: list[bool] = []
    worker.failed.connect(failures.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.run()

    assert len(failures) == 1
    assert isinstance(failures[0], MeetingImportError)
    assert "raw internal detail" not in failures[0].user_message
    assert finished == [True]
