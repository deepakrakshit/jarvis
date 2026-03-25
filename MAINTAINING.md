# Maintaining Guide

## Code Ownership Boundaries

- `app/`: orchestration and entrypoints only.
- `core/`: runtime logic, prompting, config, env/dependency checks.
- `voice/`: TTS/STT internals only.
- `interface/`: transport adapters (CLI rendering, pywebview bridge).
- `frontend/`: visual layer and browser-side voice/reactivity logic.

## Rules for New Features

1. Add new runtime behavior in `core/runtime.py` only when it is model-agnostic.
2. Keep UI-specific signaling in `interface/api_bridge.py`, not in `core/runtime.py`.
3. Keep tuning knobs in `.env` and `core/settings.py` defaults.
4. If adding browser visuals, edit `frontend/assets/main.js` and `frontend/assets/styles.css`.
5. Avoid placing long scripts/styles inside `frontend/index.html`.

## Run Matrix

- BOTH (default): `python jarvis.py`
- GUI only: `python jarvis.py --gui`
- CLI only: `python jarvis.py --cli`
- Direct launcher: `python app/main.py --mode both|gui|cli`

## Dependency Management

- Install/update via `pip install -r requirements.txt`
- Keep `requirements.txt` minimal and runtime-focused.
- Add comments in PR/commit notes for any dependency with native binaries.

## Stability Checklist Before Shipping

1. `python -m py_compile` for all `app/core/voice/interface` modules.
2. Smoke test GUI launch.
3. Smoke test CLI query + TTS response.
4. Validate `.env` path values for `models/`.
