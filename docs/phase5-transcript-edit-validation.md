# Phase 5 Transcript Edit Validation

The manual validation uses the exact two-segment transcript produced during the real Phase 4
Hebrew STT run, without loading or rerunning faster-whisper. It imports the original MP3 into
isolated Sikumon storage, persists the original transcript as revision 1, opens it in
`TranscriptView`, changes one Hebrew segment, saves through `TranscriptEditService`, disposes and
recreates the database engine/repository, and reloads the transcript.

Validated invariants:

- the editor becomes dirty only after the text changes;
- canonical reload clears dirty state;
- revision advances exactly once, from 1 to 2;
- corrected Hebrew text survives restart;
- both segment UUIDs remain unchanged;
- positions and millisecond timestamps remain unchanged;
- segment `created_at` values remain unchanged;
- transcription status remains `COMPLETED`.

Manual run on 2026-09-02:

- source: `test_media/hebrew_sample.mp3.mp3`;
- edited text: `רק יסחקת` to `רק משחקת`;
- persisted revision after save: `2`;
- restart reload: succeeded;
- segment IDs, positions, timestamps, and `created_at`: stable.
