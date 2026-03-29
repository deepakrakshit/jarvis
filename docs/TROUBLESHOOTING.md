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

## 👁️ Vision Stage Skipped or Weak

**Common causes:**

* missing `OPENROUTER_API_KEY`
* OpenRouter rate limit (`429`)

**Fix:**

* set valid `OPENROUTER_API_KEY`
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

## 🧾 Identity/Persona Drift in Replies

**Fix:**

* verify identity guardrail methods in `core/runtime.py`
* confirm system prompt safety rules in `core/settings.py`
* test with explicit identity prompts

---

## 🚨 Golden Rule

> If output looks correct but feels wrong, trace routing + tool evidence first.