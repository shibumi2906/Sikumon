"""Local transcription provider boundary and engine-neutral results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ProviderSegment:
    start_time_ms: int
    end_time_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class ProviderProgress:
    processed_time_ms: int


ProviderProgressCallback = Callable[[ProviderProgress], None]


class TranscriptionProvider(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        cancellation: CancellationSignal,
        progress_callback: ProviderProgressCallback | None = None,
    ) -> tuple[ProviderSegment, ...]: ...
