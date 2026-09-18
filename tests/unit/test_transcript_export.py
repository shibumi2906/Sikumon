from sikumon.application.transcript_export import (
    ExportSegment,
    format_plain_transcript,
    format_srt_transcript,
    safe_export_stem,
    write_export,
)


def sample_segments() -> tuple[ExportSegment, ...]:
    return (
        ExportSegment(1_234, 3_456, "שלום לכולם"),
        ExportSegment(65_000, 67_890, "משימה שנייה"),
    )


def test_plain_transcript_is_readable_and_timestamped() -> None:
    assert format_plain_transcript(sample_segments()) == (
        "[00:00:01]\nשלום לכולם\n\n[00:01:05]\nמשימה שנייה\n"
    )


def test_srt_transcript_has_precise_ranges() -> None:
    assert format_srt_transcript(sample_segments()) == (
        "1\n00:00:01,234 --> 00:00:03,456\nשלום לכולם\n\n"
        "2\n00:01:05,000 --> 00:01:07,890\nמשימה שנייה\n"
    )


def test_safe_filename_and_atomic_utf8_write(tmp_path) -> None:
    assert safe_export_stem('  פגישה: צוות/מכירות?  ') == "פגישה_ צוות_מכירות_"
    destination = tmp_path / "תמלול.txt"
    write_export(destination, "שלום\n")
    assert destination.read_text(encoding="utf-8-sig") == "שלום\n"
