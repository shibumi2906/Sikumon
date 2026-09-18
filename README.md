# Sikumon

**A Hebrew-first Windows meeting assistant with local speech-to-text and evidence-grounded AI analysis.**

![Sikumon showing a Hebrew meeting summary](docs/portfolio/screenshots/01-hero-summary.png)

Sikumon turns Hebrew meeting recordings into an editable, timestamped transcript on the user's
computer. When requested, it sends transcript-related text—not audio—to OpenAI and returns a
structured Hebrew summary, decisions, and action items linked to their exact transcript evidence.

## Key features

- Import Hebrew meeting audio and transcribe it locally with faster-whisper and an Ivrit.ai model.
- Review and edit RTL transcript segments with stable timestamps.
- Copy the full transcript or export it as UTF-8 TXT/SRT.
- Generate a Hebrew summary, decisions, and action items through the OpenAI Responses API.
- Navigate from a decision or task to the supporting transcript segment.
- Keep meetings, transcripts, analyses, and operation state in local SQLite storage.
- Install as a standalone Windows desktop application; Python is not required on the target PC.

## Privacy and local-first architecture

> Your audio stays on your computer.  
> Speech-to-text is performed locally.  
> Only transcript-related text is sent to OpenAI when AI analysis is requested.

Local transcription, transcript editing, export, and previously saved meeting review work without
an OpenAI request. AI analysis requires internet access and an OpenAI API key, stored through
`keyring` in Windows Credential Manager. The key is not stored in SQLite.

See [privacy details](docs/portfolio/privacy.md) and the
[architecture overview](docs/portfolio/architecture.md).

## Screenshots

| Transcript and export | Action items and evidence |
| --- | --- |
| ![Editable Hebrew transcript with copy and export controls](docs/portfolio/screenshots/02-transcript-and-export-controls.png) | ![Hebrew action items linked to transcript evidence](docs/portfolio/screenshots/05-action-items-and-evidence.png) |

More: [portfolio screenshots](docs/portfolio/screenshots/).

## Tech stack

Python 3.12, PySide6, faster-whisper, Ivrit.ai, CTranslate2, SQLite, SQLAlchemy,
Pydantic, OpenAI Responses API, keyring/Windows Credential Manager, PyInstaller,
Inno Setup, pytest, Ruff, and MyPy.

## Installation

The portfolio build is distributed as `SikumonSetup.exe` for 64-bit Windows. The installer is
currently unsigned, so Windows SmartScreen may display **Unknown Publisher**. The local STT model
is downloaded separately after installation and is not embedded in the installer.

For source development, use Python 3.12:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[analysis,transcription,dev]"
python -m sikumon.main
```

## Demo

The [45–90 second demo script](docs/portfolio/demo-script.md) covers import, local transcription,
editing, AI analysis, evidence navigation, and transcript export.

## Testing and quality

The project uses pytest for unit/integration/smoke coverage, Ruff for linting, and strict MyPy for
the application package. The packaged and installed executable is also validated separately,
including launch, saved transcript access, copy/export, analysis views, settings, and clean exit.

## Status and limitations

Portfolio release **0.1.0** is functionally complete and available as a standalone installer.
Current limitations: Windows x64 only; Hebrew-first UI/workflow; no speaker diarization; local STT
model download requires disk space and an initial internet connection; OpenAI analysis requires a
user-supplied API key and network access; the installer is not code-signed.

See the [portfolio overview](docs/portfolio/project-overview-en.md) and
[release notes](docs/portfolio/release-notes.md).
