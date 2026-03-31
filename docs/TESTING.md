# 🧪 Testing Guide

![Testing](https://img.shields.io/badge/Testing-Stress%20Ready-orange)
![Validation](https://img.shields.io/badge/Validation-Strict-success)

---

## ⚡ Fast Validation

```bash
python -m compileall app agent core services interface voice tests
```

---

## 🧨 Stress Suite

```bash
python -m unittest discover -s tests/stress -p "test_*.py" -v
```

Includes:

* retrieval throughput under repeated query load
* entity extraction stability under repeated passes
* QA engine single-doc and multi-doc output-shape checks
* reasoning payload budget enforcement for large fused content
* ultra-fast deterministic reasoning latency checks
* PDF parser guardrail limits (table-page cap and render short-circuit)
* text-rich fast lane verification (vision/OCR skip when safe)
* app-control resolver/executor verification behavior
* runtime disambiguation for file picker vs file explorer phrasing
* planner/validator/registry contract checks
* connectivity intent routing and deterministic connectivity output
* weather daily forecast/rain-probability handling
* system control max/min brightness and volume canonicalization
* synthesizer fallback readability for app/system control outputs

---

## 🔥 Critical Test Scenarios

### 1. Weather Reliability

* location override from user input
* session location carry-over (`i am in ...` then `weather?`)
* forecast prompt (`forecast for tomorrow`) uses daily weather path
* rain prompt (`will it rain today`) uses precipitation probability
* mismatch recovery behavior

---

### 2. Live-Data Tool Refusal

```text
weather without using tools
```

Must refuse with a safe response.

---

### 3. Search/Factual Accuracy

```text
latest ai news
who won ipl 2025 season
```

Must route through internet evidence and synthesize cleanly.

---

### 4. Document Intelligence Flow

* Trigger with `analyze document` or `summarize this pdf`
* Validate file picker behavior and path validation
* Confirm parser/OCR/vision fallback produces stable summary output
* Run follow-up question without re-selecting file (active-doc QA)
* Compare mode with two selected files

---

### 5. Identity + Personality Safety

* identity queries must return JARVIS identity
* persona drift outputs must be corrected by guardrails
* role prefixes like `assistant:` should be cleaned in final output

---

### 6. Voice/UX Runtime

* TTS starts/stops cleanly across long responses
* SKIP button interrupts active speech and restores listening/processing mode correctly

---

### 7. App Control + File Flow Disambiguation

* `open file explorer` must route to app control (not document picker)
* `open file manager` must route to app control (not document picker)
* `open file picker` must route to document selection flow
* `open document selector` must route to document selection flow
* `open vscode` / `open anaconda` should verify process start without false `execution_failed`

---

### 8. Connectivity + System Control Normalization

* `check internet connectivity` must not route to search-policy feedback
* `max volume` / `min volume` must map to safe `set_volume` actions
* `max brightness` / `min brightness` must map to safe `set_brightness` actions
* app/system fallback responses must remain human-readable (no raw dict payload leakage)

---

## 🚨 Regression Guardrails

* ❌ No stale outputs presented as fresh
* ❌ No duplicate tool calls from planner/executor drift
* ❌ No wrong location weather results
* ❌ No fake real-time claims
* ❌ No unsafe document path handling

---

## 🎯 Goal

> **Break the system responsibly, then harden it.**