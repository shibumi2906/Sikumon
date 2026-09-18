from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolate_local_app_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent every test, including future default-path tests, from touching real user data."""

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))


@pytest.fixture
def database(tmp_path: Path):
    from sikumon.database.db import create_session_factory, create_sqlite_engine
    from sikumon.database.migrations import apply_migrations

    engine = create_sqlite_engine(tmp_path / "data" / "sikumon.db")
    apply_migrations(engine)
    try:
        yield engine, create_session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def make_wav(tmp_path: Path):
    def create(name: str = "meeting.wav", duration_seconds: float = 0.2) -> Path:
        path = tmp_path / name
        frame_rate = 8_000
        frame_count = int(frame_rate * duration_seconds)
        with wave.open(str(path), "wb") as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(frame_rate)
            recording.writeframes(b"\x00\x00" * frame_count)
        return path

    return create


@pytest.fixture
def phase2_app(tmp_path: Path):
    from sikumon.application.meeting_service import MeetingService
    from sikumon.database.db import create_session_factory, create_sqlite_engine
    from sikumon.database.migrations import apply_migrations
    from sikumon.database.repositories import MeetingRepository
    from sikumon.services.audio.metadata import AudioMetadataService
    from sikumon.storage.file_storage import MeetingFileStorage
    from sikumon.storage.paths import ApplicationPaths

    paths = ApplicationPaths.resolve(tmp_path / "phase2-data")
    paths.ensure_directories()
    engine = create_sqlite_engine(paths.database)
    apply_migrations(engine)
    repository = MeetingRepository(create_session_factory(engine))
    storage = MeetingFileStorage(paths)
    service = MeetingService(repository, AudioMetadataService(), storage)
    try:
        yield paths, repository, storage, service
    finally:
        engine.dispose()
