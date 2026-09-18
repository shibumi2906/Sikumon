"""Meeting-owned filesystem staging, finalization, and cleanup."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from uuid import UUID

from sikumon.storage.paths import ApplicationPaths


class MeetingFileStorage:
    def __init__(
        self, paths: ApplicationPaths, logger: logging.Logger | None = None
    ) -> None:
        self._paths = paths
        self._logger = logger or logging.getLogger("sikumon.storage")

    def meeting_directory(self, meeting_id: UUID | str) -> Path:
        return self._paths.meetings / str(self._validated_id(meeting_id))

    def meeting_cache_directory(self, meeting_id: UUID | str) -> Path:
        return self._paths.cache / "meetings" / str(self._validated_id(meeting_id))

    def import_directory(self, meeting_id: UUID | str) -> Path:
        return self._paths.meetings / ".imports" / str(self._validated_id(meeting_id))

    def prepare_import(self, meeting_id: UUID | str) -> Path:
        directory = self.import_directory(meeting_id)
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    def staged_audio_path(self, meeting_id: UUID | str, extension: str) -> Path:
        return self.import_directory(meeting_id) / f"source_audio{extension}"

    def final_audio_path(self, meeting_id: UUID | str, extension: str) -> Path:
        return self.meeting_directory(meeting_id) / f"source_audio{extension}"

    def copy_to_staging(
        self, source: Path, meeting_id: UUID | str, extension: str
    ) -> Path:
        source = Path(source)
        directory = self.prepare_import(meeting_id)
        destination = directory / f"source_audio{extension}"
        self._logger.info("Copying meeting audio to staging for meeting_id=%s", meeting_id)
        try:
            shutil.copy2(source, destination)
            if not destination.is_file():
                raise OSError("staged copy is missing")
            if source.stat().st_size <= 0 or destination.stat().st_size != source.stat().st_size:
                raise OSError("staged copy size mismatch")
            with destination.open("rb") as stream:
                stream.read(1)
            return destination
        except Exception:
            self.cleanup_import(meeting_id)
            raise

    def finalize_import(self, meeting_id: UUID | str) -> Path:
        staging = self.import_directory(meeting_id)
        final = self.meeting_directory(meeting_id)
        if final.exists():
            raise FileExistsError(final)
        os.replace(staging, final)
        self._logger.info("Finalized meeting storage for meeting_id=%s", meeting_id)
        return final

    def cleanup_import(self, meeting_id: UUID | str) -> None:
        staging = self.import_directory(meeting_id)
        if staging.exists():
            shutil.rmtree(staging)
            self._logger.info("Cleaned incomplete import for meeting_id=%s", meeting_id)

    def staged_import_ids(self) -> tuple[UUID, ...]:
        return self._uuid_directories(self._paths.meetings / ".imports")

    def finalized_meeting_ids(self) -> tuple[UUID, ...]:
        return self._uuid_directories(self._paths.meetings)

    def meeting_cache_ids(self) -> tuple[UUID, ...]:
        return self._uuid_directories(self._paths.cache / "meetings")

    def delete_meeting_files(self, meeting_id: UUID | str) -> tuple[Path, ...]:
        """Best-effort deletion; missing paths are success and failures are returned."""

        failed: list[Path] = []
        targets = (
            self.meeting_directory(meeting_id),
            self.import_directory(meeting_id),
            self.meeting_cache_directory(meeting_id),
        )
        for target in targets:
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
            except OSError as error:
                failed.append(target)
                self._logger.exception(
                    "Failed deleting meeting-owned path for meeting_id=%s error=%s",
                    meeting_id,
                    type(error).__name__,
                )
        return tuple(failed)

    @staticmethod
    def _validated_id(meeting_id: UUID | str) -> UUID:
        return meeting_id if isinstance(meeting_id, UUID) else UUID(str(meeting_id))

    def _uuid_directories(self, root: Path) -> tuple[UUID, ...]:
        if not root.is_dir():
            return ()
        identifiers: list[UUID] = []
        try:
            candidates = tuple(root.iterdir())
        except OSError:
            self._logger.exception("Failed listing meeting-owned storage root=%s", root)
            return ()
        for candidate in candidates:
            try:
                if candidate.is_dir():
                    identifiers.append(UUID(candidate.name))
            except (OSError, ValueError):
                continue
        return tuple(identifiers)
