# Testing Guide

## Fast validation

Run syntax checks on critical modules after edits:

- `core/runtime.py`
- `services/search_service.py`
- `services/network_service.py`

Use editor diagnostics or `python -m py_compile` for targeted files.

## Behavioral replay checklist

Validate these flows after routing changes:

1. Factual search auto-routing
   - PM/President queries
   - holiday queries
2. Search command execution
   - `search on internet ...`
   - `then search on internet`
3. Speed test reliability
   - start test
   - immediate result follow-up
   - missing-module handling
4. Contextual follow-up
   - `that season` / `which team won`
5. Conceptual brevity
   - brief answer by default
   - deeper explanation only when requested

## Regression guardrails

- Do not let policy-feedback routes hijack actionable commands.
- Do not return stale speed snapshots as fresh results.
- Do not force unrelated search fallbacks when relevance filtering fails.
