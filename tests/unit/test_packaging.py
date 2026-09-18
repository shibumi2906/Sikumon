from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from sikumon.config.constants import APP_VERSION
from sikumon.services.audio.metadata import AudioMetadataService
from sikumon.storage.resources import application_bundle_root, bundled_tool_path


def test_package_and_runtime_versions_match() -> None:
    project_root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["version"] == APP_VERSION


def test_development_bundle_root_is_project_root() -> None:
    project_root = Path(__file__).resolve().parents[2]

    assert application_bundle_root() == project_root


def test_frozen_bundle_resolves_media_tools(
    monkeypatch, tmp_path: Path
) -> None:
    executable = tmp_path / "Sikumon.exe"
    resources = tmp_path / "_internal"
    tools = resources / "tools"
    tools.mkdir(parents=True)
    ffprobe = tools / "ffprobe.exe"
    ffprobe.write_bytes(b"probe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(resources), raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    assert application_bundle_root() == resources
    assert bundled_tool_path("ffprobe.exe") == ffprobe
    assert AudioMetadataService().resolve_ffprobe() == ffprobe


def test_packaging_configuration_exists() -> None:
    packaging = Path(__file__).resolve().parents[2] / "packaging"

    assert (packaging / "Sikumon.spec").is_file()
    assert (packaging / "Sikumon.iss").is_file()
    assert (packaging / "build.ps1").is_file()
