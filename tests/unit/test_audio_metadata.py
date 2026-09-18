from pathlib import Path

import pytest

from sikumon.services.audio.metadata import (
    AudioMetadataService,
    MediaValidationError,
    MediaValidationFailure,
    normalized_audio_extension,
)


@pytest.mark.parametrize("extension", [".wav", ".MP3", ".m4a", ".FLAC", ".aac", ".mp4"])
def test_supported_extension_detection(extension: str) -> None:
    assert normalized_audio_extension(Path(f"recording{extension}")) == extension.lower()


def test_unsupported_media_extension_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "meeting.txt"
    source.write_text("not audio", encoding="utf-8")

    with pytest.raises(MediaValidationError) as caught:
        AudioMetadataService().inspect(source)

    assert caught.value.failure == MediaValidationFailure.UNSUPPORTED_FORMAT


def test_supported_extension_is_not_enough_for_valid_audio(tmp_path: Path) -> None:
    source = tmp_path / "broken.wav"
    source.write_bytes(b"not a wave recording")

    with pytest.raises(MediaValidationError) as caught:
        AudioMetadataService().inspect(source)

    assert caught.value.failure == MediaValidationFailure.INVALID_AUDIO


def test_real_wav_metadata_is_read(make_wav) -> None:
    source = make_wav(duration_seconds=0.25)

    metadata = AudioMetadataService().inspect(source)

    assert metadata.normalized_extension == ".wav"
    assert metadata.duration_seconds == pytest.approx(0.25, abs=0.01)
