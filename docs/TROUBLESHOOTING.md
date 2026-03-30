# 🛠️ Troubleshooting

![Debug](https://img.shields.io/badge/Debug-Guide-yellow)

---

## 🌦️ Wrong Weather Location

**Common causes:**

* IP-derived fallback is different from user city
* session location was never set

**Fix:**

* provide explicit location (`weather in pune`)
* set context once (`i am in pune`) then retry

---

## 🌐 Search/News Not Working

**Common causes:**

* missing or invalid `SERPER_API_KEY`
* network timeouts

**Fix:**

* verify `.env` and restart runtime
* confirm internet access and retry

---

## 📄 Document Analysis Unavailable

**Common causes:**

* optional document dependencies are missing
* unsupported file type
* selected file path failed validation

**Fix:**

* install dependencies from `requirements.txt`
* use supported file types (PDF, DOCX, DOC, PNG/JPG/TIFF/BMP/WEBP)
* retry with a smaller file if size limits are hit

---

## ❓ Document Q&A Says No Active Context

**Common causes:**

* no document has been successfully analyzed in the current session
* runtime restarted and active context was cleared

**Fix:**

* run `analyze document` first
* then ask follow-up questions (pricing, risk, entities, etc.)

---

## ⚖️ Compare Mode Doesn’t Trigger

**Common causes:**

* only one document is currently active
* compare prompt explicitly asks to upload/select files but only one is chosen

**Fix:**

* choose at least two files in compare flow
* use prompts like `compare these documents for pricing and risks`

---

## 👁️ Vision Stage Skipped or Weak

**Common causes:**

* missing `GROQ_API_KEY`
* Vision API rate limit (`429`)

**Fix:**

* set valid `GROQ_API_KEY`
* retry later or adjust vision retry settings in `.env`
* pipeline will still attempt OCR fallback when possible

---

## ⚙️ Tool Not Executing

**Common causes:**

* planner emitted invalid schema
* tool not registered/available

**Fix:**

* inspect planner output and validator result
* confirm tool registration in `agent/tool_registry.py`

---

## 🧠 Wrong Response Type

**Common causes:**

* intent overlap or weak matcher pattern
* missing context from prior turn

**Fix:**

* inspect routing logic in `core/runtime.py`
* tighten matcher patterns and rerun tests

---

## 🎤 Voice Delay or Choppy Playback

**Fix:**

* tune TTS settings (`TTS_CHUNK_CHARS`, queue and fragment parameters)
* use the UI **SKIP** control to interrupt long replies safely

---

## 🎙️ Microphone Input Not Working

**Common causes:**

* `PyAudio` is missing in the active virtual environment
* OS-level microphone permission is disabled

**Fix:**

* reinstall dependencies with `pip install -r requirements.txt`
* verify microphone permission for terminal/desktop runtime

---

## ⚡ Document Processing Feels Slow

Tune the following environment variables in `.env`:

* `DOCUMENT_OCR_MAX_WORKERS`
* `DOCUMENT_VISION_MAX_WORKERS`
* `DOCUMENT_PDF_RENDER_DPI`
* `DOCUMENT_PDF_MAX_VISION_IMAGES`
* `DOCUMENT_PDF_MAX_OCR_IMAGES`
* `DOCUMENT_PDF_TABLE_MAX_PAGES`
* `DOCUMENT_REASONING_DEFAULT_FAST`
* `DOCUMENT_ULTRA_FAST_ENABLED`
* `DOCUMENT_ULTRA_FAST_MIN_CHARS`
* `DOCUMENT_SKIP_VISION_FOR_TEXT_RICH`
* `DOCUMENT_TEXT_RICH_MIN_CHARS`
* `DOCUMENT_REASONING_FAST_PATH_THRESHOLD_CHARS`
* `DOCUMENT_REASONING_*_CHAR_BUDGET`

---

## 🧾 Identity/Persona Drift in Replies

**Fix:**

* verify identity guardrail methods in `core/runtime.py`
* confirm system prompt safety rules in `core/settings.py`
* test with explicit identity prompts

---

## 🚨 Golden Rule

> If output looks correct but feels wrong, trace routing + tool evidence first.