# Sikumon — English project overview

## One-line description

Sikumon is a Hebrew-first Windows meeting assistant that transcribes audio locally and turns the
transcript into evidence-grounded summaries, decisions, and action items.

## Recruiter description

Sikumon is a production-style desktop product designed and built end to end for Hebrew-speaking
users. It imports meeting audio, performs speech-to-text locally, and presents an editable RTL
transcript with timestamps, copy, and TXT/SRT export. Optional OpenAI analysis operates on
transcript-related text only and produces a structured Hebrew summary, decisions, and tasks linked
back to the supporting transcript segments. The product is packaged as a standalone Windows
installer with local persistence, credential protection, recovery paths, automated quality gates,
and installed-application validation.

## Technical description

The application uses Python 3.12 and PySide6, with faster-whisper, an Ivrit.ai CTranslate2 model,
and CPU int8 inference for local Hebrew STT. SQLAlchemy persists meetings, segments, transcript
revisions, analyses, evidence links, and operation state in SQLite transactions. OpenAI Responses
API Structured Outputs are parsed into strict Pydantic models; evidence IDs are validated against
the exact source revision before the result and current-analysis pointer are committed. API keys
are stored by keyring in Windows Credential Manager. PyInstaller and Inno Setup produce the
standalone Windows distribution.

## Business/client description

Sikumon helps Hebrew-speaking professionals turn recorded meetings into useful, traceable work
artifacts without uploading audio to an AI service. Users keep the recording and transcription
workflow on their own computer, then choose whether to request AI analysis. The result is a
searchable meeting record with an editable transcript, concise summary, decisions, tasks, and
clickable source evidence—useful for consultancies, small teams, interviews, and client meetings.

## LinkedIn post

I built Sikumon, a Hebrew-first Windows meeting assistant, end to end.

It imports Hebrew audio, runs speech-to-text locally, and provides an editable timestamped
transcript with copy and TXT/SRT export. When the user requests analysis, only transcript-related
text is sent to OpenAI; the app returns a structured Hebrew summary, decisions, and action items,
each linked to exact transcript evidence.

The product combines Python 3.12, PySide6, faster-whisper with an Ivrit.ai model, CTranslate2,
SQLite/SQLAlchemy, Pydantic Structured Outputs, Windows Credential Manager, PyInstaller, and Inno
Setup. I also handled transactional persistence, crash recovery, revision-aware analysis,
background operations, Windows DLL packaging, automated tests, and installed-app validation.

Sikumon is now packaged as a standalone Windows installer and ready as a portfolio release.

#Python #PySide6 #SpeechToText #OpenAI #DesktopApp #Hebrew #LocalFirst

## Short employer/recruiter message

Hello — I recently completed Sikumon, a Hebrew-first Windows desktop product that I designed and
built end to end. It combines local Hebrew speech-to-text, editable timestamped transcripts,
structured OpenAI analysis with evidence grounding, transactional SQLite persistence, secure
Windows credential storage, and a standalone installer. I would be glad to share a short demo and
discuss the engineering decisions behind the product.
