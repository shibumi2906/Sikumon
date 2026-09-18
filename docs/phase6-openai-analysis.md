# Phase 6 OpenAI Analysis

## Provider contract

- Default provider: `openai`
- Default model: `gpt-4.1-mini-2025-04-14`
- Prompt version: `1`
- Schema version: `1`
- SDK method: `OpenAI(...).responses.parse(...)`
- Structured output binding: `text_format=MeetingAnalysisPayload`
- Provider-side response storage: `store=False`
- SDK request retries: disabled; Sikumon owns the single semantic correction retry
- Request timeout: 60 seconds

The pinned GPT-4.1 Mini snapshot was selected because OpenAI documents support for the Responses
endpoint and Structured Outputs, a 1,047,576-token context window, low latency, and text output.
The model does not support audio, and Sikumon passes no file or audio input.

## Input-size policy

Sikumon serializes every persisted segment without truncation. The estimator counts each UTF-8
byte as one token, a conservative dependency-free upper estimate for byte-pair tokenization. The
request is rejected above 200,000 estimated tokens, leaving substantial headroom for instructions,
structured output, and model behavior within the documented context window. Chunking is not
implemented.

## Validation and persistence

The response must first validate against the strict Pydantic v2 schema. Every decision and action
item then must reference at least one ID from the exact captured meeting transcript. Schema or
evidence failure permits one correction request containing the failure category and the complete
valid-ID set. A second failure ends the operation as `FAILED`.

After validation, one SQLite transaction checks that the meeting revision still equals the
captured source revision, inserts the analysis, decisions, action items, and evidence references,
updates `current_analysis_id`, and sets the operation to `COMPLETED`. Any failure rolls back the
new graph and preserves the previous current analysis.

## Real API validation status

On 2026-09-02, Sikumon checked Windows Credential Manager and the development environment without
printing credential material. No OpenAI API key was configured, so no real API request was made.
The production request path is covered by a fake SDK client assertion and provider-boundary tests;
Hebrew output quality and live account/model access remain to be validated once a credential is
explicitly configured.
