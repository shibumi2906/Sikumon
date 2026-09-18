# CV and interview notes

## CV bullets

- Designed and built Sikumon end to end: a Hebrew-first Windows meeting assistant with local STT,
  RTL transcript editing, optional AI analysis, evidence navigation, export, and a standalone
  installer.
- Implemented local Hebrew speech recognition with faster-whisper, a pinned Ivrit.ai CTranslate2
  model, lazy loading, CPU int8 inference, progress reporting, and cancellation-safe persistence.
- Designed transactional SQLite/SQLAlchemy workflows for crash-consistent audio import, canonical
  transcript replacement, revision-aware editing, structured analysis, and restart recovery.
- Integrated OpenAI Responses API Structured Outputs with strict Pydantic validation, semantic
  evidence checks, a bounded correction retry, and revision-safe transactional commits.
- Built a privacy-aware local/cloud boundary: audio remains local, transcript-related text is sent
  only on explicit analysis, and the API key is stored in Windows Credential Manager.
- Delivered a native PySide6 RTL interface with timestamped editing, summary/decision/task views,
  exact evidence navigation, transcript copy, and UTF-8 TXT/SRT export.
- Produced and validated a standalone Windows distribution with PyInstaller and Inno Setup;
  diagnosed a Qt/ICU DLL conflict caused by a polluted PATH and foreign ICU DLLs, then made clean,
  isolated builds reproducible.

## Interview talking points

### Why local STT?

Audio is the most sensitive and largest meeting artifact. Keeping transcription local makes the
privacy boundary easy to explain, avoids audio-upload latency and vendor coupling, and supports
offline transcription after the model is installed. The trade-offs are a roughly 1.6 GB model,
CPU time, disk use, and a first-run download.

### Why PySide6?

The product needed a native Windows desktop UI, strong Unicode/RTL support, mature widgets, file
dialogs, threading primitives, and deterministic packaging. PySide6 allowed a single Python code
base around the STT/AI ecosystem. The principal cost was native Qt deployment complexity.

### Why SQLite?

The data belongs to one local desktop user and needs transactions, referential integrity, queryable
history, and no server administration. SQLite matches that operational model. SQLAlchemy separates
domain/application code from persistence details and makes transactional boundaries explicit.

### Why transcript revisions?

Analysis is derived from a particular transcript. A monotonically increasing revision prevents a
late background result or stale editor from overwriting newer content. Each analysis stores its
source revision, so the UI can mark it outdated and the repository can reject an invalid commit.

### How does evidence grounding work?

Every committed transcript segment has a stable UUID. The analysis request includes only the
supplied segment IDs, timestamps, and text. The structured response must cite those IDs for every
decision and task. Sikumon validates the schema and checks that every cited ID belongs to the
source transcript; invalid evidence triggers at most one full correction retry, then fails safely.
Clicking an evidence item navigates to and highlights the source segment.

### Why Structured Outputs?

Summary, decisions, tasks, and evidence are application data, not display prose. Responses API
Structured Outputs bound to Pydantic make missing fields and invalid types explicit, simplify the
provider boundary, and support deterministic downstream validation. Schema validation is necessary
but not sufficient, which is why semantic evidence validation is separate.

### How does recovery work?

Long-running operations store state, while canonical data changes only in short transactions.
Audio import uses staging; transcription commits the complete candidate or none of it; analysis
commits only after final schema, evidence, and revision checks. On restart, stale in-progress
states are reconciled to a recoverable failure/previous-good state. The prior transcript or
analysis pointer remains intact when a later operation fails.

### How does Windows packaging work?

PyInstaller collects Python, Qt, STT/AI dependencies, metadata, application assets, and bundled
FFmpeg tools into a directory build. Inno Setup creates a per-user x64 installer under
`%LOCALAPPDATA%\Programs\Sikumon`. The STT model stays outside the installer and is downloaded
and verified separately in application data.

### What was the real Qt/ICU packaging bug?

The first packaged executable failed while importing `QtWidgets` with “procedure not found”.
Inspection showed the build environment's PATH exposed foreign ICU/Qt-adjacent DLLs, which
PyInstaller collected ahead of the matching PySide6 runtime. The resulting distribution mixed Qt
with incompatible ICU DLLs. I compared the bundled DLL set and the mutually matched PySide6,
PySide6 Essentials/Addons, and shiboken6 versions; removed stale build/dist artifacts; restricted
PATH to Windows system directories during collection; and rebuilt cleanly from the Python 3.12
packaging environment. The final GUI build uses the compatible PySide6 6.11.2 family and launches
without requiring Python or PySide6 on the target machine.

### What would come next?

Code-signing is the highest-value release improvement. Product extensions could include
diarization, search, configurable models, richer export, and accessibility testing, but they should
be driven by user research rather than added to the portfolio release without evidence.
