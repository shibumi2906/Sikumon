"""Deterministic user-facing transcript export formats."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True, slots=True)
class ExportSegment:
    start_time_ms: int
    end_time_ms: int
    text: str


def _plain_timestamp(milliseconds: int) -> str:
    total_seconds = max(0, milliseconds) // 1_000
    hours, remainder = divmod(total_seconds, 3_600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _srt_timestamp(milliseconds: int) -> str:
    value = max(0, milliseconds)
    hours, remainder = divmod(value, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def format_plain_transcript(segments: Sequence[ExportSegment]) -> str:
    """Return readable UTF-8 text with stable timestamps."""
    blocks = [
        f"[{_plain_timestamp(segment.start_time_ms)}]\n{segment.text.strip()}"
        for segment in segments
        if segment.text.strip()
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def format_srt_transcript(segments: Sequence[ExportSegment]) -> str:
    """Return a standards-compatible SubRip transcript."""
    blocks = []
    for index, segment in enumerate(
        (segment for segment in segments if segment.text.strip()), start=1
    ):
        blocks.append(
            f"{index}\n"
            f"{_srt_timestamp(segment.start_time_ms)} --> "
            f"{_srt_timestamp(segment.end_time_ms)}\n"
            f"{segment.text.strip()}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def safe_export_stem(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")
    return cleaned[:120] or "transcript"


def write_export(path: Path, content: str) -> None:
    """Atomically replace a user-selected export file with UTF-8 text."""
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8-sig",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
