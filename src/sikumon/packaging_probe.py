"""Non-interactive checks executed by the real frozen application binary."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import wave
from importlib.metadata import version
from pathlib import Path
from typing import Any

from PySide6.QtCore import QLibraryInfo

from sikumon.application.meeting_service import MeetingService
from sikumon.config.constants import APP_VERSION
from sikumon.database.db import create_session_factory, create_sqlite_engine
from sikumon.database.migrations import apply_migrations, get_schema_version
from sikumon.database.repositories import MeetingRepository
from sikumon.logging_config import configure_logging
from sikumon.security.credentials import KeyringCredentialStore
from sikumon.services.audio.metadata import AudioMetadataService, MediaValidationError
from sikumon.services.transcription.model_manager import FasterWhisperModelVerifier
from sikumon.storage.file_storage import MeetingFileStorage
from sikumon.storage.paths import ApplicationPaths
from sikumon.storage.resources import bundled_tool_path

_CREDENTIAL_SENTINEL = "sikumon-packaging-probe-not-an-api-key"


def _tool_version(tool: Path) -> str:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result = subprocess.run(
        [str(tool), "-version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=flags,
    )
    return result.stdout.splitlines()[0]


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as recording:
        recording.setnchannels(1)
        recording.setsampwidth(2)
        recording.setframerate(8_000)
        recording.writeframes(b"\x00\x00" * 1_600)


def _credential_check(action: str, account: str) -> bool:
    store = KeyringCredentialStore(
        account=account,
        allow_environment_fallback=False,
    )
    if action == "write":
        store.set_api_key(_CREDENTIAL_SENTINEL)
        return store.get_api_key() == _CREDENTIAL_SENTINEL
    if action == "read-delete":
        matched = store.get_api_key() == _CREDENTIAL_SENTINEL
        store.delete_api_key()
        return matched
    return store.get_api_key() is not None


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    paths = ApplicationPaths.resolve(args.data_root)
    paths.ensure_directories()
    logger = configure_logging(paths)
    engine = create_sqlite_engine(paths.database, logger)
    apply_migrations(engine, logger)
    repository = MeetingRepository(create_session_factory(engine))
    metadata = AudioMetadataService(logger=logger)
    ffprobe = metadata.resolve_ffprobe()
    ffmpeg = bundled_tool_path("ffmpeg.exe")
    if ffprobe is None or ffmpeg is None:
        raise RuntimeError("Bundled media tools were not resolved")

    report: dict[str, Any] = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "application_version": APP_VERSION,
        "python_version": sys.version.split()[0],
        "data_root": str(paths.root),
        "database_exists": paths.database.is_file(),
        "schema_version": get_schema_version(engine),
        "log_exists": (paths.logs / "sikumon.log").is_file(),
        "ffmpeg_version": _tool_version(ffmpeg),
        "ffprobe_version": _tool_version(ffprobe),
        "ffprobe_path": str(ffprobe),
        "package_versions": {
            name: version(name)
            for name in (
                "sikumon",
                "PySide6",
                "SQLAlchemy",
                "pydantic",
                "keyring",
                "openai",
                "httpx",
                "faster-whisper",
                "ctranslate2",
                "huggingface-hub",
            )
        },
    }

    plugin_root = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
    report["qt_windows_plugin"] = (plugin_root / "platforms" / "qwindows.dll").is_file()
    report["credential_check"] = _credential_check(
        args.credential_action, args.credential_account
    )

    if args.import_media:
        source_wav = paths.cache / "packaging-probe.wav"
        source_mp3 = paths.cache / "packaging-probe.mp3"
        corrupt_mp3 = paths.cache / "corrupt.mp3"
        _write_wav(source_wav)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        subprocess.run(
            [
                str(ffmpeg),
                "-v",
                "error",
                "-y",
                "-i",
                str(source_wav),
                str(source_mp3),
            ],
            check=True,
            capture_output=True,
            timeout=30,
            creationflags=flags,
        )
        service = MeetingService(
            repository,
            metadata,
            MeetingFileStorage(paths, logger),
            logger,
        )
        imported = service.import_meeting(source_mp3, "בדיקת אריזה")
        report["media_import"] = {
            "meeting_id": imported.id,
            "local_copy_exists": Path(imported.audio_path).is_file(),
            "duration_seconds": imported.audio_duration_seconds,
        }
        corrupt_mp3.write_bytes(b"not media")
        try:
            metadata.inspect(corrupt_mp3)
        except MediaValidationError as error:
            report["controlled_error_hebrew"] = any(
                "\u0590" <= character <= "\u05ff" for character in error.user_message
            )
        else:
            report["controlled_error_hebrew"] = False

    report["meeting_count"] = len(repository.list())
    if args.model_directory is not None:
        model_directory = args.model_directory.resolve()
        required = ("config.json", "model.bin", "tokenizer.json")
        report["existing_model_detected"] = all(
            (model_directory / filename).is_file() for filename in required
        )
        if args.load_model:
            verified = FasterWhisperModelVerifier().verify(model_directory)
            report["model_constructed"] = True
            report["model_runtime_versions"] = {
                "faster_whisper": verified.faster_whisper,
                "ctranslate2": verified.ctranslate2,
            }
    engine.dispose()
    return report


def maybe_run_packaging_probe(argv: list[str]) -> int | None:
    if "--packaging-probe" not in argv:
        return None
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--packaging-probe", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument(
        "--credential-action",
        choices=("write", "read-delete", "inspect"),
        default="inspect",
    )
    parser.add_argument("--credential-account", default="packaging-probe")
    parser.add_argument("--import-media", action="store_true")
    parser.add_argument("--model-directory", type=Path)
    parser.add_argument("--load-model", action="store_true")
    args = parser.parse_args(argv)
    report_path = args.packaging_probe.resolve()
    try:
        payload = {"success": True, **run_probe(args)}
        exit_code = 0
    except Exception as error:  # noqa: BLE001 - frozen probe must always serialize failure
        payload = {
            "success": False,
            "error_type": type(error).__name__,
            "error": str(error),
        }
        exit_code = 1
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return exit_code
