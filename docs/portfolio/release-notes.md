# Sikumon 0.1.0 — first portfolio release

Release date: 2026-09-18  
Platform: Windows x64  
Installer tooling: PyInstaller 6.22.3 + Inno Setup

The current application version is **0.1.0** in both `pyproject.toml` and runtime constants. This
portfolio packaging task does not change that version.

## Highlights

- Hebrew audio import with crash-consistent local storage
- Local faster-whisper transcription with the pinned Ivrit.ai
  `whisper-large-v3-turbo-ct2` model
- Editable timestamped RTL transcript with revision-safe saves
- Full transcript copy and UTF-8 TXT/SRT export
- Optional structured OpenAI analysis for Hebrew summary, decisions, and tasks
- Evidence validation and navigation to exact transcript segments
- Transactional SQLite persistence and restart recovery
- API-key storage through Windows Credential Manager
- Standalone per-user Windows installer

## Release artifact

| Field | Value |
| --- | --- |
| File | `dist/SikumonSetup.exe` |
| Size | 141,280,565 bytes (141.28 MB; 134.74 MiB) |
| SHA-256 | `F032E37F972F58407C8F4F66E8E856299582F82688035863CBFDA013BAC8C79C` |

The Ivrit.ai STT model is downloaded separately after installation and is not included in the
installer. The installer is not code-signed; Windows SmartScreen may display **Unknown Publisher**.
Users should verify the checksum and obtain the installer only from the project's official release
location. Do not instruct users to disable SmartScreen or antivirus protections.

## Runtime versions in the packaged build

- PySide6 / Essentials / Addons / shiboken6: 6.11.2
- faster-whisper: 1.2.1
- CTranslate2: 4.8.1
- SQLAlchemy: 2.0.54
- Pydantic: 2.13.5
- OpenAI Python SDK: 1.109.1
- keyring: 25.7.0

## Validation

The installed `Sikumon.exe` was smoke-tested on 2026-09-18: it launched, opened the persisted
HCSH001 Hebrew transcript, performed the copy action, opened the TXT/SRT export dialog, displayed
the saved Hebrew summary and tasks with evidence, opened Settings, and closed normally. No file
was saved during the export-dialog check.

No source/runtime code changed while preparing this portfolio package, so pytest, Ruff, and MyPy
were not rerun. The immediately preceding source validation baseline was: **169 passed in 46.30s**,
**Ruff: All checks passed**, **MyPy: Success: no issues found in 66 source files**.

## Known limitations

- Windows x64 only and Hebrew-first
- No speaker diarization
- Initial local STT model download requires internet access and substantial disk space
- AI analysis requires an internet connection, a user-supplied OpenAI API key, and account usage
- Unsigned installer may trigger SmartScreen
- AI output quality depends on transcript quality; evidence grounding reduces but does not
  eliminate semantic model errors

## Public repository safety audit

Audit date: 2026-09-18. The workspace currently has no `.git` directory, so it is not yet an
initialized Git repository and no tracked-file determination is possible.

### Findings

- No embedded `sk-...` API key and no `.env` file were found in the public-facing source,
  tests, scripts, documentation, packaging configuration, README, or project metadata.
- Source references to `OPENAI_API_KEY` are development fallback/credential integration code,
  not a committed credential.
- Local generated profiles (`.phase11-*`) contain SQLite databases/logs and validation state.
  They must not be added to a public repository.
- `test_media/` contains MP3 validation audio, including `HCSH001.mp3`. Even when believed to be
  test data, audio and derived transcripts require explicit rights/privacy review before release.
- `dist/`, `build/`, virtual environments, packaging vendor binaries, and generated version
  metadata are local build artifacts and should not be source-controlled.
- Existing validation screenshots and documents use test content. Review every image manually
  before publishing; the curated `docs/portfolio/screenshots/` set excludes API keys and personal
  filesystem paths. The Settings image is intentionally cropped.
- No downloaded model was found as a public source asset. Models can be very large and may have
  separate license/attribution requirements.
- Public-facing source/docs did not contain a user-specific home-directory path. Build script
  defaults such as `C:\ffmpeg\bin` are tool locations, not user data.

### .gitignore result

`.gitignore` already excluded virtual environments, caches, build/dist, vendor/generated
packaging content, environment files, logs, and SQLite files. It now also excludes local phase
profiles, `test_media/`, common audio formats, model directories, and `.env.*`.

### Before creating a public repository

1. Initialize Git only after running `git status --ignored` and reviewing the exact staged set.
2. Add files explicitly; do not use a broad first commit until generated/local data is confirmed
   ignored.
3. Perform a second secret scan and inspect Git history before changing repository visibility.
4. Confirm licenses/attribution for the application, icons, FFmpeg distribution, and Ivrit.ai
   model references.
5. Publish the source repository without the installer or model; attach the installer to a
   versioned release instead.

## Distribution recommendation

- **GitHub:** public source and documentation, plus a tagged `v0.1.0` Release containing the
  installer, checksum, release notes, screenshots, and unsigned-installer warning.
- **Google Drive / OneDrive:** a read-only fallback download for recruiters/clients when GitHub
  release assets are inconvenient; publish the checksum beside the link.
- **Personal portfolio:** use the hero image, concise case study, 60-second demo, architecture
  diagram, and links to the repository and official release.

No repository visibility, upload, release, or external sharing was changed by this task.
