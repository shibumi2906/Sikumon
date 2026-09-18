"""Lazy, CPU-only faster-whisper integration for the verified Ivrit.ai model."""

from __future__ import annotations

import logging
import math
import threading
import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sikumon.config.constants import (
    IVRIT_MODEL_ID,
    IVRIT_MODEL_REVISION,
    TRANSCRIPTION_COMPUTE_TYPE,
    TRANSCRIPTION_DEVICE,
    TRANSCRIPTION_LANGUAGE,
)
from sikumon.services.transcription.provider import (
    CancellationSignal,
    ProviderProgress,
    ProviderProgressCallback,
    ProviderSegment,
)


class TranscriptionProviderError(RuntimeError):
    def __init__(self, user_message: str, *, technical_message: str | None = None) -> None:
        super().__init__(technical_message or user_message)
        self.user_message = user_message


class TranscriptionCancelled(TranscriptionProviderError):
    def __init__(self) -> None:
        super().__init__("התמלול בוטל.")


class EmptyTranscriptionError(TranscriptionProviderError):
    def __init__(self) -> None:
        super().__init__("לא זוהה דיבור שניתן לתמלל בהקלטה.")


def seconds_to_milliseconds(seconds: float) -> int:
    if not math.isfinite(seconds):
        raise ValueError("Segment timestamp must be finite")
    try:
        milliseconds = int(
            (Decimal(str(max(0.0, seconds))) * Decimal(1000)).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
        )
    except (InvalidOperation, ValueError) as error:
        raise ValueError("Invalid segment timestamp") from error
    return milliseconds


class FasterWhisperIvritProvider:
    """Construct the local model on first use and reuse it for this process."""

    def __init__(self, model_directory: Path, logger: logging.Logger | None = None) -> None:
        self._model_directory = Path(model_directory)
        self._logger = logger or logging.getLogger("sikumon.transcription.provider")
        self._model: Any | None = None
        self._model_lock = threading.Lock()
        self._last_model_load_seconds: float | None = None

    @property
    def last_model_load_seconds(self) -> float | None:
        return self._last_model_load_seconds

    def transcribe(
        self,
        audio_path: Path,
        cancellation: CancellationSignal,
        progress_callback: ProviderProgressCallback | None = None,
    ) -> tuple[ProviderSegment, ...]:
        self._raise_if_cancelled(cancellation)
        model = self._get_model()
        self._raise_if_cancelled(cancellation)
        try:
            raw_segments, info = model.transcribe(
                str(audio_path),
                language=TRANSCRIPTION_LANGUAGE,
            )
            self._logger.info(
                "faster-whisper decoding initialized configured_language=%s "
                "reported_language=%s",
                TRANSCRIPTION_LANGUAGE,
                getattr(info, "language", "unknown"),
            )
            results: list[ProviderSegment] = []
            latest_end = 0
            try:
                for raw in raw_segments:
                    self._raise_if_cancelled(cancellation)
                    text = str(raw.text).strip()
                    start_ms = seconds_to_milliseconds(float(raw.start))
                    end_ms = max(start_ms, seconds_to_milliseconds(float(raw.end)))
                    latest_end = max(latest_end, end_ms)
                    if text:
                        results.append(ProviderSegment(start_ms, end_ms, text))
                    if progress_callback is not None:
                        progress_callback(ProviderProgress(latest_end))
            finally:
                close_segments = getattr(raw_segments, "close", None)
                if callable(close_segments):
                    close_segments()
            self._raise_if_cancelled(cancellation)
            if not results:
                raise EmptyTranscriptionError
            return tuple(results)
        except TranscriptionProviderError:
            raise
        except Exception as error:
            raise TranscriptionProviderError(
                "לא ניתן להשלים את התמלול המקומי. ההקלטה הקיימת נשמרה.",
                technical_message=(
                    f"faster-whisper transcription failure: {type(error).__name__}: {error}"
                ),
            ) from error

    def _get_model(self) -> Any:
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel  # type: ignore[import-untyped]

                started = time.monotonic()
                self._logger.info(
                    "STT model loading repository=%s requested_revision=%s device=%s "
                    "compute_type=%s path=%s",
                    IVRIT_MODEL_ID,
                    IVRIT_MODEL_REVISION or "UNRESOLVED",
                    TRANSCRIPTION_DEVICE,
                    TRANSCRIPTION_COMPUTE_TYPE,
                    self._model_directory,
                )
                self._model = WhisperModel(
                    str(self._model_directory),
                    device=TRANSCRIPTION_DEVICE,
                    compute_type=TRANSCRIPTION_COMPUTE_TYPE,
                )
                self._last_model_load_seconds = time.monotonic() - started
                self._logger.info(
                    "STT model loaded duration_seconds=%.3f",
                    self._last_model_load_seconds,
                )
                return self._model
            except Exception as error:
                self._logger.exception("STT model loading failed")
                raise TranscriptionProviderError(
                    "לא ניתן לטעון את מודל התמלול המקומי. אפשר לבדוק אותו בהגדרות.",
                    technical_message=(
                        f"faster-whisper model load failure: {type(error).__name__}: {error}"
                    ),
                ) from error

    @staticmethod
    def _raise_if_cancelled(cancellation: CancellationSignal) -> None:
        if cancellation.is_set():
            raise TranscriptionCancelled
