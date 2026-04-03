<div align="center">

[![Header](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=160&section=header&text=Troubleshooting&fontSize=44&fontColor=ffffff&animation=twinkling&fontAlignY=50)](.)

[![Debug](https://img.shields.io/badge/Debug-Guide-F7C948?style=for-the-badge)](.)
[![Coverage](https://img.shields.io/badge/Issues-18%2B%20Covered-0066FF?style=for-the-badge)](.)

</div>

> **Golden Rule:** If output looks correct but feels wrong — trace routing + tool evidence first.

---

## 🚦 Quick Diagnostics

Before diving into specific issues, run these in order:

```bash
# 1. Verify syntax and imports are intact
python -m compileall app agent core services interface voice

# 2. Confirm .env is set correctly
python -c "from core.settings import AppConfig; c = AppConfig.from_env('.env'); print('Gemini API key:', bool(c.gemini_api_key), '| Search model set:', bool(c.gemini_search_model))"

# 3. Run full stress suite
python -m unittest discover -s tests/stress -p "test_*.py" -v
```

---

## 🌦️ Wrong Weather Location

**Symptoms:** Weather response shows a different city than requested.

**Common causes:**
- IP-derived fallback resolved to a different city
- Session location was set previously and is overriding the query

**Fixes:**
1. Provide explicit location: `weather in pune`
2. Reset session location: `i am in pune` then retry
3. If still wrong, check `data/user_memory.json` → `last_city` key

---

## 🌧️ Forecast / Rain Query Returns Current Weather

**Symptoms:** `forecast for tomorrow` or `will it rain today` returns current conditions, not forecast data.

**Common causes:**
- Using a generic `weather` prompt instead of forecast/rain phrasing
- Open-Meteo daily endpoint temporarily unavailable

**Fixes:**
1. Use explicit forecast phrasing: `forecast for tomorrow` or `will it rain today`
2. Retry after 30 seconds if Open-Meteo is slow
3. Verify the test passes: `python -m unittest tests.stress.test_weather_service_forecast -v`

---

## 🌐 Search / News Not Working

**Symptoms:** "I could not complete that web search request" or empty results.

**Common causes:**
- Missing or invalid `GEMINI_API_KEY` in `.env`
- Gemini Grounding rate limit exceeded (free tier: 2,500 queries/month)
- Network connectivity issue

**Fixes:**
1. Verify key: `python -c "import os; from dotenv import load_dotenv; load_dotenv(); print(os.getenv('GEMINI_API_KEY', 'MISSING'))"`
2. Test connectivity: `check internet connectivity`
3. Get a free key at [ai.google.dev/gemini-api/docs/grounding](https://ai.google.dev/gemini-api/docs/grounding)

---

## 📄 Document Analysis Unavailable

**Symptoms:** "Document analysis is not available. Install the required dependencies first."

**Common causes:**
- Optional document dependencies not installed
- Dependency import failure due to wrong interpreter

**Fixes:**
```bash
pip install PyMuPDF pdfplumber python-docx paddleocr paddlepaddle Pillow
```

If install succeeds but still fails, verify you're using the project venv:
```bash
python -c "import fitz; import pdfplumber; import docx; import paddleocr; print('All OK')"
```

---

## 📄 Unsupported File Type

**Symptoms:** "Unsupported file type" error when analyzing a document.

**Supported formats:** `.pdf` · `.docx` · `.doc` · `.png` · `.jpg` · `.jpeg` · `.tiff` · `.tif` · `.bmp` · `.webp`

**For `.doc` files:** Save as `.docx` in Microsoft Word and retry. Legacy `.doc` format requires COM automation not available cross-platform.

**File size limit:** 100 MB. Files larger than this are rejected before parsing begins.

---

## 📁 File Explorer Opens Document Picker (or Vice Versa)

**Expected behavior:**

| Phrase | Result |
|---|---|
| `open file picker` | Document selection flow |
| `open document selector` | Document selection flow |
| `select a document` | Document selection flow |
| `open file explorer` | Windows File Explorer (app control) |
| `open file manager` | Windows File Explorer (app control) |

**If file explorer is triggering document picker:** Verify your phrase uses "explorer" or "manager" — not "picker" or "selector".

---

## ❓ Document Q&A Says No Active Context

**Symptoms:** "I could not find enough supporting evidence in the active document."

**Common causes:**
- No document has been analyzed in this session
- Runtime was restarted, clearing the in-memory active document index

**Fix:**
1. Run `analyze document` or `summarize this pdf` first
2. Once complete, the document is indexed and follow-up questions will work

---

## ⚖️ Compare Mode Doesn't Trigger

**Symptoms:** Compare query opens single-file picker or returns error.

**Common causes:**
- Only one document is currently active in the session
- Phrase uses explicit "these two files" but only one file was active

**Fixes:**
1. Use explicit multi-file phrasing: `compare these documents for pricing and risks`
2. If no active docs exist, the picker will open — select 2+ files
3. If active docs exist, compare works directly from memory without re-selecting

---

## 👁️ Vision Stage Skipped or Weak

**Symptoms:** Document analysis missing visual content, tables, or layout information.

**Common causes:**
- Missing or invalid `GEMINI_API_KEY`
- Vision API rate limit (HTTP 429)
- Text-rich fast lane skipping vision for non-visual content (expected behavior)

**Fixes:**
1. Verify `GEMINI_API_KEY` is set and valid
2. For rate limits, retry after 60 seconds or adjust: `DOCUMENT_VISION_FAST_FAIL_ON_429=false`
3. For non-visual documents, vision skip is expected — OCR and text extraction handle them

---

## ⚙️ Tool Not Executing

**Symptoms:** Agent returns "I could not safely execute that plan" or tool appears to do nothing.

**Common causes:**
- Planner emitted an invalid schema (wrong argument types)
- Tool name not registered in the registry
- Validator rejected the plan (too many steps, invalid args)

**Fixes:**
1. Enable logging: `export PYTHONPATH=.; python -c "import logging; logging.basicConfig(level=logging.INFO); from core.runtime import JarvisRuntime; ..."`
2. Check `agent/tool_registry.py` for the tool's input schema
3. Run: `python -m unittest tests.stress.test_agent_contracts -v`

---

## 🌐 Connectivity Check Gives Wrong Response Type

**Symptoms:** `check internet connectivity` triggers search-policy feedback ("Understood. I will verify...") instead of a probe result.

**Cause:** Routing regression — `SEARCH_POLICY_RE` is matching connectivity phrases.

**Fix:**
1. Update to latest build
2. Verify: `python -m unittest tests.stress.test_runtime_interaction_flows.RuntimeInteractionFlowsTest.test_connectivity_phrase_not_treated_as_search_policy_feedback -v`

---

## 🔊 Max/Min Volume or Brightness Rejected

**Symptoms:** `max volume` returns "Unsupported system action" or "Invalid system action request."

**Cause:** Routing regression — `SystemControlValidator` not canonicalizing max/min phrases.

**Fix:**
1. Update to latest build
2. Verify: `python -m unittest tests.stress.test_system_control.SystemControlValidatorTest.test_max_min_volume_and_brightness_are_canonicalized -v`
3. Fallback: Use explicit form: `set volume to 100` or `set brightness to 0`

---

## 🧩 App Control Returns Ambiguous

**Symptoms:** "I found multiple matching apps. Please specify one."

**Cause:** Multiple installed apps score similarly against the query.

**Fixes:**
1. Use a more specific name: `open google chrome` instead of `open browser`
2. Use the exact app name from your Start Menu
3. Try canonical aliases: `open browser` → Chrome · `open coding` → VS Code

---

## ✅ App Open/Close Not Verified

**Symptoms:** App launches but JARVIS reports "I could not verify completion."

**Common causes:**
- App process name doesn't match resolver hints
- App launches a subprocess with a different process name
- OS blocked the launch (permissions, antivirus)

**Fixes:**
1. Retry with the exact app name from Start Menu
2. Ensure JARVIS is running with sufficient OS permissions
3. Verify the app can be launched manually without JARVIS

---

## 🧠 Wrong Response Type

**Symptoms:** Expected a web search result but got a local response, or vice versa.

**Common causes:**
- A new regex pattern is too broad and matches unintended queries
- A new handler was registered at the wrong priority

**Fixes:**
1. Check `core/runtime.py` intent router registration order
2. Run routing tests: `python -m unittest tests.stress.test_runtime_interaction_flows -v`
3. Check for overly broad regex patterns (avoid single words like `check`, `open`, `again` as standalone matchers)

---

## 🎤 Voice Delay or Choppy Playback

**Common causes:**
- TTS chunk size too large (audio gap between chunks)
- PyAudio buffer size mismatch
- First-chunk delay setting too high

**Tuning guide** (`.env`):

| Problem | Tune This |
|---|---|
| Long pause before first word | Lower `TTS_CHUNK_CHARS` to 28–35 |
| Audio gaps mid-sentence | Lower `TTS_CHUNK_CHARS`, raise `TTS_FORCE_FIRST_FRAGMENT_AFTER_WORDS` |
| Choppy/distorted audio | Raise `TTS_FRAMES_PER_BUFFER` to 2048 or 4096 |
| Response feels slow to start | Set `TTS_FIRST_CHUNK_DELAY=0.00` |

Use the **SKIP** button in the desktop UI to interrupt long responses safely.

---

## 🎙️ Microphone Input Not Working

**Symptoms:** GUI shows "MIC PERMISSION REQUIRED FOR VOICE MODE" or no transcripts appear.

**Common causes:**
- OS-level microphone permission not granted to the browser/webview
- PyAudio not installed

**Fixes:**
```bash
pip install PyAudio
```

For Windows: Settings → Privacy → Microphone → allow access for desktop apps.

Check the browser console (F12 in webview debug mode) for `getUserMedia` errors.

---

## ⚡ Document Processing Feels Slow

Tune these `.env` variables to improve throughput:

| Variable | Suggested Range | Effect |
|---|---|---|
| `DOCUMENT_OCR_MAX_WORKERS` | 4–8 | More parallel OCR threads |
| `DOCUMENT_VISION_MAX_WORKERS` | 2–6 | More parallel vision requests |
| `DOCUMENT_PDF_RENDER_DPI` | 96–140 | Lower DPI = faster render, less detail |
| `DOCUMENT_PDF_MAX_VISION_IMAGES` | 5–10 | Fewer pages sent to vision |
| `DOCUMENT_PDF_MAX_OCR_IMAGES` | 8–16 | Fewer pages sent to OCR |
| `DOCUMENT_PDF_TABLE_MAX_PAGES` | 4–8 | Fewer pages for table extraction |
| `DOCUMENT_REASONING_DEFAULT_FAST` | `true` | Use 8b model (much faster) |
| `DOCUMENT_ULTRA_FAST_ENABLED` | `true` | Skip LLM entirely for simple docs |
| `DOCUMENT_SKIP_VISION_FOR_TEXT_RICH` | `true` | Skip vision on text-heavy PDFs |

For repeat analysis of the same file, the SQLite cache (`DOCUMENT_CACHE_ENABLED=true`) eliminates re-processing entirely.

---

## 🧾 Identity / Persona Drift in Replies

**Symptoms:** JARVIS claims to be a human, fictional character, or gives personal biographical details.

**Common causes:**
- `_enforce_assistant_identity()` guard not triggering on edge-case phrasing
- System prompt was modified incorrectly

**Fixes:**
1. Verify `core/settings.py` → `SYSTEM_PROMPT` contains identity enforcement instructions
2. Verify `core/runtime.py` → `_enforce_assistant_identity()` and `_looks_like_identity_hallucination()` are intact
3. Add the triggering phrase to `_FORBIDDEN_PATTERNS` in `core/personality.py` if it's a repeatable case

---

<div align="center">

[![Footer](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=100&section=footer)](.)

</div>