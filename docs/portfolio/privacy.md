# Privacy and data handling

> Your audio stays on your computer.  
> Speech-to-text is performed locally.  
> Only transcript-related text is sent to OpenAI when AI analysis is requested.

## What remains local

- Imported meeting audio and application-managed audio copies
- The Ivrit.ai speech-to-text model
- Speech-to-text inference through faster-whisper/CTranslate2
- Editable transcript segments and revisions
- Meeting metadata, summaries, decisions, tasks, evidence links, and operation state in SQLite
- TXT/SRT exports selected by the user
- The OpenAI API key, stored through keyring in Windows Credential Manager

## What can be sent to OpenAI

Only after the user explicitly requests AI analysis, Sikumon sends transcript-related text:
ordered segment text, stable segment identifiers, and timestamps required to return traceable
evidence. The audio file is not attached or transmitted. The request uses `store=False`.

The OpenAI response is parsed into a strict Pydantic schema. Decision and action-item evidence IDs
must belong to the supplied transcript; invalid output is rejected, with at most the existing one
correction retry. Validated results are then stored locally.

## Network-dependent and offline workflows

Importing already supported audio, local transcription after the model is installed, transcript
editing, copy/export, and viewing saved data are local workflows. Downloading the STT model the
first time requires internet access. AI analysis also requires internet access, a user-provided
OpenAI API key, and may be subject to the user's OpenAI account terms and usage charges.

## Credentials and logs

The production API key is not written to SQLite, ordinary settings, release documentation, or
application logs. Sikumon stores it in Windows Credential Manager via keyring. Logs should be
treated as local diagnostic data and reviewed before sharing in a support or portfolio context.

## Distribution note

The portfolio installer is currently unsigned. Windows SmartScreen may show **Unknown Publisher**;
this is a code-signing limitation, not a request to disable Windows security protections.
