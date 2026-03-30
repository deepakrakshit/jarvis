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

---

## 🔥 Critical Test Scenarios

### 1. Weather Reliability

* location override from user input
* session location carry-over (`i am in ...` then `weather?`)
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

## 🚨 Regression Guardrails

* ❌ No stale outputs presented as fresh
* ❌ No duplicate tool calls from planner/executor drift
* ❌ No wrong location weather results
* ❌ No fake real-time claims
* ❌ No unsafe document path handling

---

## 🎯 Goal

> **Break the system responsibly, then harden it.**