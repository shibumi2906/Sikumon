"""Sikumon process entry point."""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import Engine

from sikumon.application.analysis_controller import AnalysisController
from sikumon.application.analysis_service import MeetingAnalysisService
from sikumon.application.meeting_service import MeetingService
from sikumon.application.model_management import ModelManagementController
from sikumon.application.startup_recovery import (
    recover_meeting_storage,
    recover_stale_operations,
)
from sikumon.application.transcript_edit_service import TranscriptEditService
from sikumon.application.transcription_controller import TranscriptionController
from sikumon.application.transcription_service import TranscriptionService
from sikumon.config.constants import DEFAULT_ANALYSIS_MODEL
from sikumon.config.settings import ApplicationSettings
from sikumon.database.db import create_session_factory, create_sqlite_engine
from sikumon.database.migrations import apply_migrations
from sikumon.database.repositories import MeetingRepository
from sikumon.logging_config import configure_logging
from sikumon.packaging_probe import maybe_run_packaging_probe
from sikumon.security.credentials import KeyringCredentialStore
from sikumon.services.analysis.openai_provider import OpenAIAnalysisProviderFactory
from sikumon.services.audio.metadata import AudioMetadataService
from sikumon.services.transcription.faster_whisper_ivrit import FasterWhisperIvritProvider
from sikumon.services.transcription.model_manager import ModelManager
from sikumon.storage.file_storage import MeetingFileStorage
from sikumon.storage.paths import ApplicationPaths
from sikumon.ui.main_window import MainWindow
from sikumon.ui.resources import asset_path
from sikumon.ui.theme import apply_application_theme


def _application() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        return QApplication(sys.argv)
    if not isinstance(instance, QApplication):
        raise TypeError("A non-GUI Qt application already exists")
    return instance


def main(settings: ApplicationSettings | None = None) -> int:
    if settings is None:
        probe_exit_code = maybe_run_packaging_probe(sys.argv[1:])
        if probe_exit_code is not None:
            return probe_exit_code
    settings = settings or ApplicationSettings()
    paths = ApplicationPaths.resolve(settings.data_root)
    paths.ensure_directories()
    logger = configure_logging(paths, settings.log_level)
    engine: Engine | None = None

    try:
        engine = create_sqlite_engine(paths.database, logger)
        apply_migrations(engine, logger)
        session_factory = create_session_factory(engine)
        recover_stale_operations(session_factory, logger)
        file_storage = MeetingFileStorage(paths, logger)
        metadata_service = AudioMetadataService(settings.ffprobe_path, logger)
        repository = MeetingRepository(session_factory)
        recover_meeting_storage(repository, file_storage, metadata_service, logger)
        meeting_service = MeetingService(
            repository,
            metadata_service,
            file_storage,
            logger,
        )
        model_manager = ModelManager(paths, logger=logger)
        transcription_provider = FasterWhisperIvritProvider(
            model_manager.model_directory, logger
        )
        transcription_service = TranscriptionService(
            repository, model_manager, transcription_provider, logger
        )
        transcript_edit_service = TranscriptEditService(repository, logger)
        credential_store = KeyringCredentialStore()
        analysis_service = MeetingAnalysisService(
            repository,
            credential_store,
            OpenAIAnalysisProviderFactory(DEFAULT_ANALYSIS_MODEL),
            logger,
        )

        app = _application()
        apply_application_theme(app)
        app.setWindowIcon(QIcon(str(asset_path("brand-mark.svg"))))
        model_controller = ModelManagementController(model_manager, app)
        transcription_controller = TranscriptionController(transcription_service, app)
        analysis_controller = AnalysisController(analysis_service, app)
        window = MainWindow(
            meeting_service,
            paths,
            model_controller,
            transcription_controller,
            transcript_edit_service,
            analysis_controller,
            credential_store,
        )
        window.load_meetings()
        window.show()
        return app.exec()
    except Exception:
        logger.exception("Unhandled exception during application startup")
        app = _application()
        apply_application_theme(app)
        QMessageBox.critical(
            None,
            "Sikumon",
            "לא ניתן להפעיל את היישום. פרטים נוספים נשמרו ביומן היישום.",
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        logger.info("Application stopped")


if __name__ == "__main__":
    raise SystemExit(main())
