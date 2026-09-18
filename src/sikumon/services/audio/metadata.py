"""Local audio validation and duration inspection."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sikumon.storage.resources import bundled_tool_path

SUPPORTED_AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".flac", ".aac", ".mp4"})


class MediaValidationFailure(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    NOT_A_FILE = "NOT_A_FILE"
    NOT_READABLE = "NOT_READABLE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    INVALID_AUDIO = "INVALID_AUDIO"
    INSPECTOR_UNAVAILABLE = "INSPECTOR_UNAVAILABLE"


class MediaValidationError(Exception):
    def __init__(self, failure: MediaValidationFailure, technical_detail: str = "") -> None:
        super().__init__(failure.value)
        self.failure = failure
        self.technical_detail = technical_detail

    @property
    def user_message(self) -> str:
        if self.failure == MediaValidationFailure.UNSUPPORTED_FORMAT:
            return "סוג הקובץ אינו נתמך. ניתן לבחור WAV, MP3, M4A או FLAC."
        if self.failure == MediaValidationFailure.NOT_FOUND:
            return "קובץ ההקלטה לא נמצא."
        return "לא ניתן לפתוח את ההקלטה.\n\nייתכן שהקובץ פגום או שהפורמט אינו נתמך."


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    duration_seconds: float
    normalized_extension: str


def normalized_audio_extension(path: Path) -> str:
    extension = path.suffix.lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        raise MediaValidationError(MediaValidationFailure.UNSUPPORTED_FORMAT, extension)
    return extension


class AudioMetadataService:
    """Inspect media locally using ffprobe, with a dependency-free WAV fallback.

    Phase 9 can inject the packaged ffprobe executable. During development the resolver also
    accepts an executable beside the application and finally checks PATH.
    """

    def __init__(
        self,
        ffprobe_path: Path | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ffprobe_path = ffprobe_path
        self._logger = logger or logging.getLogger("sikumon.audio.metadata")

    def inspect(self, source: Path) -> AudioMetadata:
        source = Path(source)
        extension = normalized_audio_extension(source)
        if not source.exists():
            raise MediaValidationError(MediaValidationFailure.NOT_FOUND)
        if not source.is_file():
            raise MediaValidationError(MediaValidationFailure.NOT_A_FILE)
        try:
            with source.open("rb") as stream:
                stream.read(1)
        except OSError as error:
            self._logger.warning("Media file is not readable: %s", type(error).__name__)
            raise MediaValidationError(
                MediaValidationFailure.NOT_READABLE, type(error).__name__
            ) from error

        ffprobe = self.resolve_ffprobe()
        if ffprobe is not None:
            return self._inspect_with_ffprobe(source, extension, ffprobe)
        if extension == ".wav":
            return self._inspect_wav(source, extension)
        raise MediaValidationError(MediaValidationFailure.INSPECTOR_UNAVAILABLE)

    def resolve_ffprobe(self) -> Path | None:
        """Resolve the configured, bundled, legacy-adjacent, or PATH ffprobe."""

        candidates: list[Path] = []
        if self._ffprobe_path is not None:
            candidates.append(Path(self._ffprobe_path))
        bundled = bundled_tool_path("ffprobe.exe")
        if bundled is not None:
            candidates.append(bundled)
        # Keep compatibility with early development bundles that placed the tool beside the EXE.
        candidates.append(Path(sys.executable).resolve().parent / "ffprobe.exe")
        discovered = shutil.which("ffprobe")
        if discovered:
            candidates.append(Path(discovered))
        return next((candidate for candidate in candidates if candidate.is_file()), None)

    def _inspect_with_ffprobe(
        self, source: Path, extension: str, ffprobe: Path
    ) -> AudioMetadata:
        command = [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,duration",
            "-of",
            "json",
            str(source),
        ]
        startup_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                creationflags=startup_flags,
            )
            if result.returncode != 0:
                raise MediaValidationError(
                    MediaValidationFailure.INVALID_AUDIO,
                    f"ffprobe_exit={result.returncode}",
                )
            payload = json.loads(result.stdout)
            streams = payload.get("streams", [])
            audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
            if not audio_streams:
                raise MediaValidationError(MediaValidationFailure.INVALID_AUDIO, "no_audio_stream")
            durations = [payload.get("format", {}).get("duration")]
            durations.extend(stream.get("duration") for stream in audio_streams)
            duration = next(
                (float(value) for value in durations if value is not None and float(value) > 0),
                None,
            )
            if duration is None:
                raise MediaValidationError(MediaValidationFailure.INVALID_AUDIO, "no_duration")
            return AudioMetadata(duration_seconds=duration, normalized_extension=extension)
        except MediaValidationError:
            raise
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as error:
            self._logger.warning("Media inspection failed: %s", type(error).__name__)
            raise MediaValidationError(
                MediaValidationFailure.INVALID_AUDIO, type(error).__name__
            ) from error

    def _inspect_wav(self, source: Path, extension: str) -> AudioMetadata:
        try:
            with wave.open(str(source), "rb") as recording:
                frame_rate = recording.getframerate()
                frame_count = recording.getnframes()
                if frame_rate <= 0 or frame_count <= 0 or recording.getnchannels() <= 0:
                    raise MediaValidationError(MediaValidationFailure.INVALID_AUDIO)
                duration = frame_count / frame_rate
                recording.readframes(min(frame_count, 1))
            return AudioMetadata(duration_seconds=duration, normalized_extension=extension)
        except MediaValidationError:
            raise
        except (OSError, EOFError, wave.Error) as error:
            self._logger.warning("WAV inspection failed: %s", type(error).__name__)
            raise MediaValidationError(
                MediaValidationFailure.INVALID_AUDIO, type(error).__name__
            ) from error
