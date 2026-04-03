<div align="center">

[![Header](https://capsule-render.vercel.app/api?type=waving&color=0D1117,0066FF,00E1FF&height=160&section=header&text=Security%20Policy&fontSize=40&fontColor=ffffff&animation=twinkling&fontAlignY=50)](.)

[![Security](https://img.shields.io/badge/Security-Policy%20Active-00C853?style=for-the-badge&logo=shieldsdotio&logoColor=white)](.)
[![Disclosure](https://img.shields.io/badge/Disclosure-Private%20First-F55036?style=for-the-badge)](.)
[![Validation](https://img.shields.io/badge/Inputs-Assume%20Untrusted-F7C948?style=for-the-badge)](.)

</div>

---

## 🔭 Scope

JARVIS interacts with:
- **External APIs** (Gemini, Gemini Grounding, Open-Meteo, ipify)
- **System-level OS tools** (PowerShell, pycaw, screen-brightness-control, pygetwindow)
- **Local user-selected documents** (PDF, DOCX, images)
- **Microphone input** and **user text input**
- **A local HTTP server** serving the pywebview frontend

All of these represent potential attack surfaces. This policy defines how security issues are handled and what engineering guarantees are in place.

---

## 🚨 Reporting a Vulnerability

> **Do NOT open a public GitHub issue for security vulnerabilities.**  
> Public disclosure before a fix is available puts all users at risk.

### Preferred Channel

Use **[GitHub Security Advisories](../../security/advisories/new)** — this creates a private, encrypted channel between you and the maintainer.

### Alternative

Contact the maintainer directly via trusted channels (listed in GitHub profile).

### What to Include

Please provide as much of the following as possible:

| Field | Description |
|---|---|
| **Summary** | Clear description of the vulnerability |
| **Reproduction** | Step-by-step steps to reproduce |
| **Impact** | What an attacker could achieve |
| **Affected files** | Which modules or files are involved |
| **Suggested fix** | If you have one (optional but appreciated) |

### Response Timeline

| Stage | Target Timeline |
|---|---|
| Acknowledgement | Within 48 hours |
| Initial assessment | Within 5 business days |
| Fix or mitigation | Depends on severity and complexity |
| Public disclosure | After fix is released and users have had time to update |

---

## ⚠️ Sensitive Areas

These components receive heightened scrutiny in all reviews:

### 🔑 API Key Handling

- API keys are loaded exclusively from `.env` via `core/env.py`
- Keys are **never logged**, never embedded in code, never committed
- The `.gitignore` excludes `.env` and all credential files
- `GEMINI_API_KEY` and `HF_TOKEN` are treated as production secrets

### 🖥️ System Command Execution

- All system control actions pass through `SystemControlValidator` before execution
- Dangerous actions (`shutdown`, `restart`, `reboot`, `delete`, `format`, `exec`) are **permanently blocked** in the validator's `_BLOCKED_ACTIONS` set
- `sleep` is blocked in safe mode (default on)
- Rate limiting (30 actions/minute) prevents automated abuse
- Action logs are maintained for audit trail

### 🔧 Tool Execution Safety

- Every planned tool call passes through `agent/validator.py` before execution
- Tool output is validated post-execution; failed validation triggers a retry or refusal
- The synthesizer never upgrades tool errors into claimed successes
- Tool functions are deterministic and stateless — no hidden LLM calls

### 📡 External API Responses

- API responses are parsed defensively — unexpected shapes return safe fallbacks
- Weather, IP, and search results are never stored as authoritative facts without re-verification
- The synthesizer's relevance filter removes semantically unrelated results before synthesis

### 📄 Document Pipeline

- File selection is **always user/system initiated** — the LLM cannot trigger the file picker
- `validate_file_path()` runs before any parsing begins: existence, type, and size (max 100 MB) are all checked
- Unsupported file types are rejected with a clear error message
- Fail-open behavior: pipeline failures return structured errors, never partial or unsafe execution
- The document cache stores derived intelligence only — original file bytes are never cached

### 🌐 Local HTTP Server

- The static server binding `127.0.0.1` (loopback only) — not accessible from the network
- Port is OS-assigned (ephemeral) to prevent predictable targeting
- Handler suppresses all access logging to avoid sensitive path disclosure

---

## 🔑 Secrets Management

```
✅  DO   Store secrets in .env (never committed)
✅  DO   Use .env.example as a safe public reference template
✅  DO   Rotate compromised keys immediately via provider console
✅  DO   Treat all three API keys as production secrets

❌  DON'T  Commit .env to version control
❌  DON'T  Log API keys in debug output
❌  DON'T  Hardcode keys in source files
❌  DON'T  Share keys in GitHub issues or PRs
```

---

## 🛡️ Engineering Guarantees

The following are **architectural security properties** enforced in code, not just by policy:

| Property | Enforced By |
|---|---|
| No LLM-triggered file picker | `_handle_document()` gating in `core/runtime.py` |
| No dangerous system actions | `SystemControlValidator._BLOCKED_ACTIONS` |
| No unauthenticated remote access | Local HTTP server binds `127.0.0.1` only |
| No raw tool payload in responses | `Synthesizer._render_*_fallback()` methods |
| No identity drift | `_enforce_assistant_identity()` on every LLM response |
| No hallucinated real-time data | Tool refusal for disallowed-tool real-time requests |
| Path traversal prevention | `pathlib.Path.resolve()` + existence checks in `validate_file_path()` |
| Input length limits | App names max 80 chars, file sizes max 100 MB |

---

## ⚡ Known Limitations

Being transparent about what we do **not** currently protect against:

| Limitation | Notes |
|---|---|
| **No full process sandboxing** | System tool execution is validated but not containerized |
| **Third-party API trust** | We validate responses but cannot guarantee upstream API integrity |
| **OCR/Vision model quality** | Output accuracy depends on external Gemini model behavior |
| **Microphone access** | Requires OS-level permission; no server-side audio processing |
| **User supervision required** | JARVIS is designed for interactive use, not unattended automation |
| **Windows-only system controls** | Volume/brightness/window control uses Windows APIs |

---

## 🧭 Security Principle

> **Assume all inputs are untrusted. Validate everything.**

This is not a suggestion — it is an architectural requirement. Every module that accepts external input (user text, file paths, API responses, browser STT transcripts) must validate and sanitize before acting.

---

<div align="center">

*Maintained by **Deepak Rakshit***

[![Footer](https://capsule-render.vercel.app/api?type=waving&color=0D1117,0066FF,00E1FF&height=100&section=footer)](.)

</div>