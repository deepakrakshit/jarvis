# Troubleshooting

## Speed test says module missing

Symptom:
- Jarvis reports speed test module is missing.

Fix:
1. Activate venv.
2. Install dependencies from `requirements.txt`.
3. Retry `run speed test`.

## Search says it cannot fetch live results

Symptom:
- Jarvis asks to verify `SERPER_API_KEY`.

Fix:
1. Add valid `SERPER_API_KEY` in `.env`.
2. Check network connectivity.
3. Retry factual query.

## Query routed to wrong intent

Symptom:
- A command gets interpreted as search-policy feedback or abuse feedback.

Fix:
1. Use direct imperative phrasing (`run speed test`, `what is my current IP`).
2. If issue persists, inspect regex matchers in `core/runtime.py`.

## Current office-holder query seems uncertain

Symptom:
- Reply says it cannot confidently confirm President/PM.

Fix:
1. Ask a country-specific question.
2. Retry with explicit office and country in one line.
3. Ensure search API returns reliable snippets.

## Voice pipeline feels delayed

Symptom:
- TTS starts late or speech chunks feel slow.

Fix:
1. Tune `TTS_*` values in `.env`.
2. Verify Piper model and executable paths.
3. Keep `tts_chunk_chars` moderate to avoid long first chunk waits.
