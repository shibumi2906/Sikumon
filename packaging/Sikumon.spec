# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata


project_root = Path(SPEC).resolve().parents[1]
source_root = project_root / "src"
generated_root = project_root / "packaging" / "generated"
vendor_root = project_root / "packaging" / "vendor" / "ffmpeg"

ffmpeg = vendor_root / "ffmpeg.exe"
ffprobe = vendor_root / "ffprobe.exe"
version_info = generated_root / "version_info.txt"
for required in (ffmpeg, ffprobe, version_info):
    if not required.is_file():
        raise SystemExit(f"Required packaging input is missing: {required}")

datas = [(str(source_root / "sikumon" / "ui" / "assets"), "sikumon/ui/assets")]
for distribution in (
    "sikumon",
    "PySide6",
    "PySide6_Essentials",
    "PySide6_Addons",
    "shiboken6",
    "SQLAlchemy",
    "pydantic",
    "httpx",
    "faster-whisper",
    "ctranslate2",
    "huggingface-hub",
    "keyring",
    "openai",
):
    datas += copy_metadata(distribution)

hiddenimports = ["keyring.backends.Windows"]

analysis = Analysis(
    [str(source_root / "sikumon" / "main.py")],
    pathex=[str(source_root)],
    binaries=[
        (str(ffmpeg), "tools"),
        (str(ffprobe), "tools"),
    ],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "pytest_cov", "mypy", "ruff"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Sikumon",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    version=str(version_info),
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Sikumon",
)
