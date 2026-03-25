# JARVIS CLI + Desktop

JARVIS supports three maintained run modes:

- Both mode (default): terminal CLI and desktop GUI at the same time.
- GUI voice mode: always-listening voice input in a Python desktop window.
- CLI text mode: terminal prompt with streamed text replies and spoken output.

## Project Structure

```
app/
  main.py         # Unified launcher (default BOTH)
  cli.py          # Terminal mode
  desktop.py      # Desktop mode (pywebview wrapper)

core/
  runtime.py      # Groq streaming orchestration
  settings.py     # Config, prompt, constants
  dependencies.py # Dependency checks
  env.py          # .env loader

voice/
  tts.py          # RealtimeTTS + Piper
  stt.py          # Future Python STT placeholder

interface/
  cli_ui.py       # Terminal rendering/input
  api_bridge.py   # pywebview JS/Python bridge

frontend/
  index.html
  assets/
    styles.css
    main.js

models/
.env
requirements.txt
AI_ASSISTANCE.md
README.md
jarvis.py         # Root compatibility launcher
```

## Setup

1. Activate virtual environment.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Ensure `.env` has valid keys (`GROQ_API_KEY`, `HF_TOKEN`) and model paths.

## Run

### Both Mode (default)

```powershell
python jarvis.py
```

or

```powershell
python app/main.py --mode both
```

### GUI Voice Mode

```powershell
python jarvis.py --gui
```

or

```powershell
python app/main.py --mode gui
```

### CLI Text Mode

```powershell
python app/main.py --mode cli
```

or

```powershell
python jarvis.py --cli
```

## Maintenance Notes

- Keep frontend logic in `frontend/assets/main.js`; avoid embedding long script blocks in HTML.
- Keep tuning values only in `.env` or `core/settings.py` defaults.
- Prefer adding new adapters under `interface/` instead of bloating `core/runtime.py`.
- `voice/stt.py` is reserved for future Python-native STT integration if browser STT is replaced.
