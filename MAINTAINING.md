<div align="center">

[![Header](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=160&section=header&text=Maintaining%20JARVIS&fontSize=38&fontColor=ffffff&animation=twinkling&fontAlignY=50)](.)

[![Maintenance](https://img.shields.io/badge/Maintenance-Active-00C853?style=for-the-badge)](.)
[![Policy](https://img.shields.io/badge/Policy-Reliability--First-0066FF?style=for-the-badge)](.)
[![Architecture](https://img.shields.io/badge/Architecture-Modular-7C3AED?style=for-the-badge)](.)

</div>

---

## 🧠 Core Principle

> **Reliability > Features**

Every merge decision is made through this lens. A feature that makes JARVIS faster but introduces hallucinated output is not an improvement — it is a regression. A refactor that makes code cleaner but breaks deterministic routing must be rejected or redesigned.

Maintainers are the last line of defense for JARVIS's reliability contract.

---

## 🏗️ Module Ownership Boundaries

Each module has a single, strict responsibility. Violations of these boundaries create unpredictable coupling and are grounds for immediate rejection:

| Module | Owns | Must Never |
|---|---|---|
| `app/` | Launchers and venv re-exec | Contain business logic |
| `core/runtime.py` | Intent routing + Gemini streaming | Call tool implementations directly |
| `core/settings.py` | AppConfig + env loading | Contain runtime state |
| `agent/` | Plan → Validate → Execute → Synthesize | Make direct service calls |
| `services/` | Deterministic tool implementations | Call LLMs (except `document/` reasoning stages) |
| `services/document/` | Full document pipeline | Trigger file picker UI |
| `interface/` | Python ↔ UI bridge adapters | Contain routing or agent logic |
| `frontend/` | Three.js GUI + HTML/CSS/JS | Import Python modules |
| `voice/` | TTS engine + queue management | Make network calls |
| `memory/` | JSON-backed key/value store | Know about tools or routing |

---

## ⚙️ Routing-Safe Change Rules

The intent routing system in `core/runtime.py` is the most critical and most fragile component. Changes to routing logic must follow these rules without exception:

### 1 · Maintain Strict Intent Precedence

The priority ordering (1–30) exists for a reason. Higher-priority handlers must not be blocked by lower-priority ones. Adding a new handler requires explicitly choosing a priority number and justifying the placement relative to adjacent handlers.

### 2 · Never Block Valid Executable Intents

Policy/guardrail handlers (priorities 15–17) must not match queries that have a clear tool action available. The pattern `SEARCH_POLICY_RE` must never match `check internet connectivity` — use the test suite to verify this.

### 3 · Keep Operational Commands Deterministic

The following intents must **always** route through their deterministic service paths — they must never fall through to the agent loop or LLM fallback:

| Intent | Required Handler |
|---|---|
| `check internet connectivity` | `NetworkService.describe_connectivity()` |
| `what is my ip` / `public ip` | `NetworkService.describe_public_ip()` |
| `weather in [city]` | `WeatherService.get_weather_brief()` |
| `forecast for tomorrow` | `WeatherService` daily forecast path |
| `will it rain today` | `WeatherService` precipitation probability |
| `run speed test` | `NetworkService.run_speedtest_now()` |
| `system status` | `NetworkService.get_system_status_snapshot()` |
| `what time is it` | `NetworkService.get_temporal_snapshot()` |
| `max volume` / `min volume` | `SystemControlService` → `set_volume` 100 / 0 |
| `max brightness` / `min brightness` | `SystemControlService` → `set_brightness` 100 / 0 |

### 4 · Keep Document File Selection System-Controlled

The LLM **never** triggers `select_files()`. Only `_handle_document()` in `core/runtime.py` may call the file picker, and only after the routing system has confirmed a document intent. Model-triggered file picker is a security violation.

### 5 · Avoid Overly Broad Matchers

Short, common words (`check`, `again`, `open`, `use`) must not appear alone as routing triggers. Every matcher must use constrained, context-aware regex patterns. Run the routing disambiguation tests after any regex change.

---

## 📊 Source Priority Contract

Every response must trace its data to the correct source tier. **Mixing tiers is a regression.**

| Response Type | Required Source | Forbidden |
|---|---|---|
| Real-time / current facts | Web search + synthesis via Gemini Grounding | LLM training data |
| Weather / forecast | Open-Meteo API directly | Cached stale values |
| System / operational | Deterministic service | LLM inference |
| Document analysis | Parser / OCR / Vision fused pipeline | LLM hallucination |
| Follow-up document Q&A | Retrieval from active document index | Re-running full pipeline |
| Conceptual / explanatory | LLM fallback (brief by default) | Real-time APIs |
| User context | Memory-backed retrieval | Session inference |

---

## 📦 Dependency Management

```bash
# Install / update all dependencies
pip install -r requirements.txt

# Verify environment after changes
python -m compileall app agent core services interface voice tests
```

**Dependency policy:**
- Keep the dependency list **minimal** — every package in `requirements.txt` must earn its place
- Document native/binary dependencies explicitly in `TROUBLESHOOTING.md`
- OCR and document dependencies (`paddleocr`, `paddlepaddle`, `PyMuPDF`) are optional at runtime but must be tested in development
- Never add a dependency that cannot be installed in a clean `pip install -r requirements.txt`

---

## 🧪 Mandatory Regression Checklist

**Every merge to `main` must pass all of these.** No exceptions.

### ✅ Syntax and Import Validation

```bash
python -m compileall app agent core services interface voice tests
```

### ✅ Full Stress Suite

```bash
python -m unittest discover -s tests/stress -p "test_*.py" -v
```

### ✅ Critical Manual Scenarios

| Scenario | Expected Result |
|---|---|
| `weather in delhi` | Open-Meteo current weather for Delhi |
| `forecast for tomorrow` | Daily forecast data — NOT current conditions |
| `will it rain today` | Precipitation probability — NOT current conditions |
| `i am in pune` + `weather?` | Session location carries over |
| `check internet connectivity` | Deterministic probe result |
| `run speed test` | Sync speedtest with measurement |
| `what is my ip` | Public IP from ipify/ifconfig |
| `who won ipl 2025 season` | Gemini Grounding web search result |
| `analyze document` (PDF) | File picker → analysis → active doc index |
| Follow-up: `what is the pricing` | Retrieval-backed Q&A from active doc |
| `open file explorer` | App control (NOT document picker) |
| `open file picker` | Document selection flow |
| `max volume` | `set_volume` 100 via system control |
| `min brightness` | `set_brightness` 0 via system control |
| `open chrome` + `close it` | Close uses remembered app name |
| Identity query: `who are you` | JARVIS identity — no persona drift |

### ✅ Safety Checks

| Check | Verification |
|---|---|
| No hallucinated real-time data | Weather/IP/search answers use live APIs |
| No stale cache as fresh data | Speedtest snapshot TTL respected |
| No routing misclassification | Connectivity → deterministic, not search-policy |
| No raw payload leakage | App/system control fallbacks are human-readable |
| No identity drift | `who are you` returns JARVIS identity |
| No persona drift | Forbidden patterns not appearing in responses |

---

## 🚀 Release Checklist

Before every release tag:

1. **Update version** in `core/settings.py` → `VERSION`
2. **Update `README.md`** — verify all examples match current behavior
3. **Sync `.env.example`** — all active keys with their defaults present
4. **Verify settings parity** — every `.env` key has a corresponding `AppConfig` field in `core/settings.py`
5. **Smoke test CLI mode**: `python jarvis.py --cli`
6. **Smoke test GUI mode**: `python jarvis.py --gui`
7. **Smoke test document flow**: `analyze document` with a real PDF
8. **Run full stress suite** and confirm all tests pass
9. **Update `docs/`** if any behavior changed
10. **Tag the release** with a `vX.Y.Z` semver tag

---

## 📚 Documentation Map

| File | Covers |
|---|---|
| [`README.md`](README.md) | Project overview, quick start, feature list |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design, pipeline stages, performance controls |
| [`docs/ROUTING.md`](docs/ROUTING.md) | Intent routing strategy and precedence rules |
| [`docs/COMMANDS.md`](docs/COMMANDS.md) | Full user-facing command reference |
| [`docs/TESTING.md`](docs/TESTING.md) | Testing strategy, stress suite, critical scenarios |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Known issues and resolution steps |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contributor guide, commit conventions, PR process |
| [`SECURITY.md`](SECURITY.md) | Vulnerability reporting and security policy |
| [`AI_ASSISTANCE.md`](AI_ASSISTANCE.md) | AI-assisted development policy |

---

## 🚨 The Golden Rule

> **If you cannot confidently explain why a change is safe — do not merge it.**

When in doubt, revert. A conservative merge policy is not a sign of slow development; it is the foundation that makes JARVIS trustworthy.

---

<div align="center">

*Maintained by **Deepak Rakshit** — Building reliable, production-grade AI systems* 🚀

[![Footer](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=100&section=footer)](.)

</div>