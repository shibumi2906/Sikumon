from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from sikumon.application.transcription_service import (
    build_transcript_drafts,
    calculate_transcription_progress,
)
from sikumon.services.transcription.faster_whisper_ivrit import (
    EmptyTranscriptionError,
    FasterWhisperIvritProvider,
    TranscriptionCancelled,
    TranscriptionProviderError,
    seconds_to_milliseconds,
)
from sikumon.services.transcription.provider import ProviderSegment
from sikumon.ui.presentation import format_timestamp_ms


@pytest.mark.parametrize(
    ("seconds", "milliseconds"),
    [(0.0, 0), (1.2344, 1234), (1.2345, 1235), (-1.0, 0), (65.001, 65001)],
)
def test_seconds_to_milliseconds(seconds: float, milliseconds: int) -> None:
    assert seconds_to_milliseconds(seconds) == milliseconds


@pytest.mark.parametrize(
    ("milliseconds", "formatted"),
    [(0, "00:00"), (65_999, "01:05"), (3_600_000, "01:00:00"), (4_372_000, "01:12:52")],
)
def test_timestamp_formatting_supports_hours(
    milliseconds: int, formatted: str
) -> None:
    assert format_timestamp_ms(milliseconds) == formatted


def test_draft_mapping_filters_empty_text_and_assigns_ordered_stable_uuids() -> None:
    drafts = build_transcript_drafts(
        (
            ProviderSegment(5_000, 6_000, "  שלום  "),
            ProviderSegment(6_000, 7_000, "   "),
            ProviderSegment(7_000, 9_000, "עולם"),
        )
    )

    assert [draft.position for draft in drafts] == [0, 1]
    assert [draft.text for draft in drafts] == ["שלום", "עולם"]
    assert len({draft.id for draft in drafts}) == 2


def test_progress_is_estimated_and_safely_clamped() -> None:
    assert calculate_transcription_progress(2_500, 10.0).estimated_percent == 25
    assert calculate_transcription_progress(11_000, 10.0).estimated_percent == 100
    assert calculate_transcription_progress(-1, 10.0).estimated_percent == 0
    assert calculate_transcription_progress(1_000, None).estimated_percent is None


def test_faster_whisper_provider_is_lazy_reuses_model_and_forces_hebrew(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    constructor_calls: list[tuple[str, str, str]] = []
    transcription_calls: list[tuple[str, str]] = []

    class FakeModel:
        def __init__(self, path: str, *, device: str, compute_type: str) -> None:
            constructor_calls.append((path, device, compute_type))

        def transcribe(self, audio_path: str, *, language: str):
            transcription_calls.append((audio_path, language))
            return (
                iter(
                    (
                        SimpleNamespace(start=0.004, end=1.2345, text=" שלום "),
                        SimpleNamespace(start=1.3, end=2.0, text=" "),
                        SimpleNamespace(start=2.0, end=3.0, text="עולם"),
                    )
                ),
                SimpleNamespace(language="he"),
            )

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeModel))
    model_directory = tmp_path / "model"
    audio = tmp_path / "audio.wav"
    provider = FasterWhisperIvritProvider(model_directory)
    progress: list[int] = []

    first = provider.transcribe(
        audio,
        threading.Event(),
        lambda item: progress.append(item.processed_time_ms),
    )
    second = provider.transcribe(audio, threading.Event())

    assert constructor_calls == [(str(model_directory), "cpu", "int8")]
    assert transcription_calls == [(str(audio), "he"), (str(audio), "he")]
    assert first == (
        ProviderSegment(4, 1235, "שלום"),
        ProviderSegment(2000, 3000, "עולם"),
    )
    assert second == first
    assert progress == [1235, 2000, 3000]


def test_provider_cancellation_and_empty_results_are_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class EmptyModel:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def transcribe(self, *args, **kwargs):
            return iter((SimpleNamespace(start=0, end=1, text=" "),)), SimpleNamespace(
                language="he"
            )

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=EmptyModel))
    provider = FasterWhisperIvritProvider(tmp_path / "model")
    with pytest.raises(EmptyTranscriptionError):
        provider.transcribe(tmp_path / "audio.wav", threading.Event())

    cancellation = threading.Event()
    cancellation.set()
    with pytest.raises(TranscriptionCancelled):
        provider.transcribe(tmp_path / "audio.wav", cancellation)


def test_model_construction_failure_is_actionable_and_recoverable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class BrokenModel:
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("native model load failed")

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=BrokenModel))
    provider = FasterWhisperIvritProvider(tmp_path / "model")

    with pytest.raises(TranscriptionProviderError) as captured:
        provider.transcribe(tmp_path / "audio.wav", threading.Event())

    assert "מודל התמלול" in captured.value.user_message
    assert "native model load failed" not in captured.value.user_message
