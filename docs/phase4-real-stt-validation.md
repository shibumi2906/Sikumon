# Phase 4 Real Hebrew STT Validation

Validation date: 2026-09-02

- Repository: `ivrit-ai/whisper-large-v3-turbo-ct2`
- Validated commit: `72ad623a37947395efcc3933132353790e5a12f5`
- Python: 3.12.10
- faster-whisper: 1.2.1
- CTranslate2: 4.8.1
- Device: CPU
- Compute type: `int8`
- Language: `he` (explicit)
- Source: `test_media\hebrew_sample.mp3\02.09.2026 14.52.mp3`
- Format: MP3, stereo, 48 kHz
- Audio duration: 9.048 seconds
- Model load: 2.860 seconds
- Transcription and persistence wall time: 13.188 seconds
- Total validation wall time: 13.610 seconds
- Real-time factor: 1.458
- Segment count: 2
- Persistence: revision 1, status `COMPLETED`, stable UUID evidence IDs after restart
- Reconstruction: transcript survived database/repository recreation
- Rendering: two Hebrew RTL segments with LTR timestamps

Raw model output from the successful clean validation run:

| Position | Start (ms) | End (ms) | Text |
|---:|---:|---:|---|
| 0 | 500 | 5900 | זה מאני טיים. למה אני עף? צריכים הלוואה? במאני טיים, רק יסחקת. |
| 1 | 6600 | 7200 | חופשה? |

Sanity assessment: the output is clearly Hebrew and forms a coherent, speech-like sequence. The
timestamps are monotonic and lie within the source duration. The phrase `רק יסחקת` appears to be
an isolated recognition error, but the output is not severely corrupted. No formal WER is claimed
because no verified reference transcript was supplied.
