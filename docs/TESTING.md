<div align="center">

[![Header](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=160&section=header&text=Testing%20Guide&fontSize=44&fontColor=ffffff&animation=twinkling&fontAlignY=50)](.)

[![Testing](https://img.shields.io/badge/Testing-Stress%20Ready-F55036?style=for-the-badge)](.)
[![Stress Suite](https://img.shields.io/badge/Stress%20Suite-Comprehensive-7C3AED?style=for-the-badge)](.)
[![Validation](https://img.shields.io/badge/Validation-Mandatory-00C853?style=for-the-badge)](.)

</div>

---

## 🧭 Testing Philosophy

> **Break the system responsibly — then harden it.**

JARVIS has no unit test suite that mocks away behavior. Its test strategy is built around **stress tests** that exercise real logic paths: routing decisions, planning contracts, tool output shapes, reasoning budgets, and latency bounds.

Every test in `tests/stress/` exists because a real bug was either found or anticipated.

---

## ⚡ Fast Syntax Validation

Run this first — before anything else. Takes under 5 seconds.

```bash
python -m compileall app agent core services interface voice tests
```

This catches import errors, syntax mistakes, and broken module boundaries before you spend time running the full suite.

---

## 🧨 Full Stress Suite

```bash
python -m unittest discover -s tests/stress -p "test_*.py" -v
```

All stress test files run. Expected output: zero failures, zero errors.

---

## 📋 Stress Suite Coverage Map

| Test File | What It Validates |
|---|---|
| `test_agent_contracts.py` | Tool registry schema · Validator rejection · Planner dedup · AgentLoop gating for file/picker/IP |
| `test_agent_system_control_followup.py` | System control follow-up ("you set it to 35") with brightness topic context |
| `test_app_control.py` | Alias resolution · File explorer alias · vscode process hints · Ambiguous/not-found thresholds · Open verification · Compact matching · Short hint safety · Non-fuzzy fallback · "close it" memory |
| `test_compare_model_routing.py` | Fast model first for compare · Deep model fallback when fast schema is invalid |
| `test_entities_stress.py` | Entity extraction stability under 80 iterations on large text · Execution time bound |
| `test_fast_path_latency.py` | Ultra-fast reasoning skips LLM entirely · Completes in <150ms |
| `test_pdf_parser_limits.py` | Table extraction respects page cap · Can be fully disabled with max_pages=0 |
| `test_personality_controlled_humor.py` | Humor appended · Idempotent on double-call · Variety across 6 consecutive turns |
| `test_pipeline_fast_lane.py` | Text-rich flow calls vision support but NOT OCR for non-scanned documents |
| `test_pipeline_reasoning_budget.py` | All five char budgets respected · Text primary context present |
| `test_pipeline_vision_limits.py` | Vision capped at TEXT_PRIMARY_MAX_VISION_SUPPORT_IMAGES=3 · second_pass=False |
| `test_qa_engine.py` | Single-doc answer shape · Multi-doc compare shape · Citations present |
| `test_retriever_stress.py` | Build 220 chunks + query 540 times < 20s total throughput |
| `test_runtime_interaction_flows.py` | Compare phrase → picker flow · File manager → app control · Explicit picker → document flow · Location declaration · IPL winner extraction · Skip interruption · Desktop CLI fallback behavior |
| `test_speedtest_query_behavior.py` | Default → sync · Result query → cached result · Background → async · Assessment path · Render format · Minimum duration enforcement |
| `test_synthesizer_fallback.py` | App control fallback human-readable · System control unverified wording |
| `test_system_control.py` | Clamping · Blocked actions · Window name required · Natural language canonicalization · Max/min normalization · Multi-action guard · Action logging · Safe mode sleep block |
| `test_temporal_query_specific.py` | Time/date/day/month/year queries each return the correct focused response |
| `test_tool_registry_app_control.py` | Registered · non-parallel · 35s timeout · Schema valid |
| `test_tool_registry_system_control.py` | Registered · non-parallel · Schema requires action |
| `test_vision_model_selection.py` | Model chain preserved · `:free` suffixes rejected · No duplicates |
| `test_volume_control.py` | Keyboard fallback works when pycaw + nircmd unavailable |
| `test_weather_service_forecast.py` | Forecast uses daily data (not current) · Rain probability correct |
| `test_file_controller.py` | Workspace boundary safety · bulk file generation · content-filter moves · open-path resolution |
| `test_cmd_control.py` | Command guardrails · blocked token chains · cwd boundary enforcement · env redaction |
| `test_coding_assist.py` | Project scaffolding · run-file/run-project orchestration · dependency comparison |
| `test_agent_observability.py` | Agent loop event emission lifecycle and planner route telemetry |
| `test_executor_observability.py` | Executor event sink behavior across success/failure/unknown-tool flows |
| `test_browser_automation.py` | Browser automation placeholder module presence for suite completeness |

---

## 🔥 Critical Test Scenarios

These scenarios must be **manually verified** before merging to `main`. They cannot be fully automated because they depend on live API responses and OS behavior.

### 1 · Weather Reliability

```bash
weather in delhi              # → Open-Meteo current for Delhi
i am in pune                  # → Store session location
weather?                      # → Uses Pune (session carry-over)
forecast for tomorrow         # → Daily data (NOT current conditions)
will it rain today            # → Precipitation probability (NOT condition text)
```

**Failure pattern to watch for:** forecast/rain queries accidentally returning current conditions instead of daily forecast data.

### 2 · Live-Data Tool Refusal

```bash
weather without using tools   # → Must refuse with safe message
latest news without any tools # → Must refuse with safe message
```

### 3 · Search / Factual Accuracy

```bash
who won ipl 2025 season       # → Gemini Grounding web search result (not LLM guess)
latest ai news                # → Live news results
who is the PM of India        # → Live web result
```

### 4 · Document Intelligence Flow

```bash
analyze document              # → File picker opens → select PDF → analysis runs
# Wait for completion, then:
what is the pricing           # → Q&A from active document (no re-processing)
list all risks                # → Retrieval-backed answer
# Then:
compare these documents       # → Picker opens for 2 files → cross-doc compare
```

### 5 · File Flow Disambiguation

```bash
open file explorer            # → Opens Windows Explorer (NOT document picker)
open file manager             # → Same
open file picker              # → Opens document selection flow
open document selector        # → Same
```

### 6 · System Control Max/Min Normalization

```bash
max volume                    # → set_volume level=100 (not "unsupported action")
min volume                    # → set_volume level=0
max brightness                # → set_brightness level=100
min brightness                # → set_brightness level=0
set brightness to 50          # → set_brightness level=50
```

### 7 · App Control + Memory

```bash
open chrome                   # → Chrome launches, process verified
close it                      # → Closes Chrome using remembered name
open vscode                   # → VSCode launches
close vscode                  # → Closes VSCode directly
close it                      # → Should clear memory or report not found
```

### 8 · Connectivity Routing

```bash
check internet connectivity   # → Deterministic probe result (NOT search policy feedback)
am i online                   # → Same
check network connectivity    # → Same
```

### 9 · Identity and Persona Safety

```bash
who are you                   # → "I am JARVIS" — no persona drift
are you human                 # → JARVIS identity
what is your name             # → JARVIS identity
```

### 10 · Voice / UX Runtime (GUI mode)

- TTS starts and stops cleanly on long responses
- SKIP button interrupts mid-sentence and restores `listening` mode
- Mode indicator (LISTENING / PROCESSING / SPEAKING) updates correctly
- Mode wave reacts visually to voice input and TTS output

---

## ⚠️ Regression Guardrails

These are the behaviors that **must never regress**:

| Guardrail | Why It Matters |
|---|---|
| Forecast/rain uses daily data | Current conditions lack tomorrow's forecast |
| Connectivity → deterministic probe | Not search policy feedback — critical routing |
| File explorer → app_control | Not document picker — different user expectation |
| `max volume` → `set_volume 100` | Natural language must not result in "unsupported action" |
| Document picker → system-initiated only | LLM never triggers file picker — security invariant |
| Verified=True required before success claim | App/system control must OS-verify before reporting success |
| `close it` resolves from memory | Last opened app must carry over correctly |
| IPL winner answer from search evidence | Not from LLM training data |
| Stale speedtest not served as fresh | 15-minute TTL + requested_at timestamp enforced |
| No raw dict payload in responses | Synthesizer/fallback always renders human-readable text |

---

## 🏋️ Running Document Performance Stress Tests

For any change touching `services/document/`, run the full stress suite **and** check these specific tests:

```bash
# Reasoning budget enforcement
python -m unittest tests.stress.test_pipeline_reasoning_budget -v

# Ultra-fast latency (<150ms)
python -m unittest tests.stress.test_fast_path_latency -v

# Text-rich fast lane (vision support, no OCR)
python -m unittest tests.stress.test_pipeline_fast_lane -v

# Vision input capping
python -m unittest tests.stress.test_pipeline_vision_limits -v

# Retriever throughput
python -m unittest tests.stress.test_retriever_stress -v

# PDF parser page limits
python -m unittest tests.stress.test_pdf_parser_limits -v
```

---

<div align="center">

[![Footer](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=100&section=footer)](.)

</div>