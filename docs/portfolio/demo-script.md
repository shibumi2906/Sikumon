# Sikumon 60-second demo script

Use the packaged, installed application with prepared non-sensitive Hebrew demo audio and a
pre-downloaded STT model. Keep the OpenAI result pre-generated if network latency would distract
from the product flow.

| Time | On screen | Narration |
| --- | --- | --- |
| 0–6 s | Launch Sikumon | “Sikumon is a Hebrew-first Windows meeting assistant built as a standalone desktop product.” |
| 6–14 s | Click **New meeting**, choose Hebrew audio | “I import a Hebrew meeting recording. The audio is copied to local application storage and is not sent to OpenAI.” |
| 14–23 s | Start transcription; show progress, then the transcript | “Speech-to-text runs locally with faster-whisper and an Ivrit.ai model. The result is segmented, timestamped, and stored locally.” |
| 23–31 s | Edit one RTL segment and save | “The transcript is fully editable. Revision checks prevent stale edits or analyses from silently overwriting newer content.” |
| 31–39 s | Click **Analyze** | “AI analysis is optional. Only transcript-related text is sent through the OpenAI Responses API—never the audio.” |
| 39–52 s | Show summary, decisions, and tasks | “Structured Outputs produce a Hebrew summary, decisions, and action items. Pydantic and semantic checks validate the result before it is saved.” |
| 52–60 s | Click an evidence chip; transcript jumps/highlights | “Every extracted decision or task links back to the exact supporting transcript segment.” |
| 60–68 s | Show Copy and Export; open TXT/SRT dialog | “The user can copy the transcript or export it as TXT or SRT. Meetings remain available locally after restart.” |

## Recording notes

- Target 60–70 seconds; never wait through a complete model download in the demo.
- Use the hero summary as the thumbnail.
- Avoid showing the OpenAI key, personal paths, Windows username, real conversations, logs, or
  Credential Manager.
- State “local speech-to-text” and “optional cloud analysis”; do not call the entire product
  offline.
