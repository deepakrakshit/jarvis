# Maintaining Guide

This project is reliability-first. Preserve deterministic behavior when adding capabilities.

## Ownership Boundaries

- `app/`: launchers and mode wiring only.
- `core/`: runtime orchestration, policy, and global flow control.
- `services/`: feature execution units and external integrations.
- `interface/`: transport/UI bridge adapters.
- `frontend/`: desktop web UI only.
- `voice/`: speech pipeline internals.

## Routing-Safe Change Rules

1. Keep intent precedence explicit in `core/runtime.py`.
2. Do not allow policy or abusive-input handlers to block executable intents.
3. Keep factual/current-affairs prompts routed through search synthesis.
4. Keep operational commands deterministic (speed test, IP, status, weather).
5. Avoid broad regexes (`check`, `again`, generic fragments) without negative guards.

## Source Priority Contract

- Factual or time-sensitive: web search synthesis
- Operational/local state: deterministic services
- Conceptual: LLM fallback (brief by default)
- User profile/context: memory-backed retrieval

If a change violates this contract, treat it as a regression.

## Dependency Management

- Install/update via `pip install -r requirements.txt`.
- Keep `requirements.txt` runtime-focused.
- Call out any native/binary dependencies in release notes.

## Run Matrix

- BOTH (default): `python jarvis.py`
- GUI only: `python jarvis.py --gui`
- CLI only: `python jarvis.py --cli`
- Direct launcher: `python app/main.py --mode both|gui|cli`

## Regression Checklist Before Merge

1. Validate syntax/errors in modified Python files.
2. Replay intent-critical turns:
	- factual office-holder query
	- holiday verification query
	- speed test start + result follow-up
	- generic `search on internet` follow-up query
3. Confirm no stale speed snapshot is returned as fresh test output.
4. Confirm conceptual answer brevity still applies when detail is not requested.
5. Confirm correction flow still removes duplicate confidence suffixes.

## Release Checklist

1. Update docs in `docs/` for behavior changes.
2. Update `README.md` command examples if user-facing behavior changed.
3. Keep `.env` variable docs aligned with `core/settings.py`.
4. Smoke test both CLI and GUI launches.

## Documentation Map

- `docs/ARCHITECTURE.md`
- `docs/ROUTING.md`
- `docs/COMMANDS.md`
- `docs/TESTING.md`
- `docs/TROUBLESHOOTING.md`
