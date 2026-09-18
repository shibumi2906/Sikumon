# Phase 8 failure recovery

Phase 8 hardens existing Phase 1–7 recovery paths without adding durable states or automatic
network retries.

| Failure | Recovery behavior |
| --- | --- |
| Stale transcription/analysis `RUNNING` | Startup transaction changes only stale operations to `FAILED`; transcript, revision, and current analysis remain intact. |
| Transcription failure/cancellation | Candidate segments are never canonical; cancellation restores `NOT_STARTED` or the previous `COMPLETED` transcript state, while failure becomes `FAILED`. |
| Model interruption | Candidate and backup directories remain separate from the verified model; startup recovery keeps or restores the last valid model and removes invalid candidates. |
| Missing audio/model | Startup and browsing remain available; derived UI disables audio/model-dependent actions while persisted transcript and analysis remain visible. |
| OpenAI network/API failure | Network, authentication/access, rate-limit, and provider-server categories receive actionable Hebrew messages; transcript and previous current analysis are unchanged. |
| Invalid output/evidence | Exactly one correction retry is allowed; a second invalid result becomes `FAILED` with no partial analysis graph. |
| Revision or database race | The transaction rejects stale or partial replacement data and preserves the previous current aggregate. |
| Import/deletion filesystem failure | Import staging is compensated; DB-first deletion remains authoritative and UUID-owned leftovers are retried at startup. |
| Unexpected worker exception | Worker boundaries log the exception, emit a controlled application error, normalize durable state, and always emit completion. |

## Shutdown

Closing while model download, transcription, or analysis is active requires explicit Hebrew
confirmation. Sikumon requests cooperative cancellation and remains responsive until each Qt
worker finishes before completing shutdown. Analysis cancellation can take effect only after the
current SDK call returns or reaches the configured 60-second request timeout. Transcription and
model download cancellation occur at their next safe cooperative checkpoint; unsafe thread
termination is intentionally not used.

## Validation

Automated tests inject offline/network failures, HTTP 401/403/429/5xx, timeouts, schema and
evidence failures, persistence failures, missing files/models, worker crashes, and interrupted
durable states. These tests use isolated temporary application data and never mutate the real
validated HCSH001 meeting.
