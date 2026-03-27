# 🧪 Testing Guide

![Testing](https://img.shields.io/badge/Testing-Stress%20Ready-orange)
![Validation](https://img.shields.io/badge/Validation-Strict-success)

---

## ⚡ Fast Validation

```bash
python -m compileall agent core services
```

---

## 🔥 Critical Test Scenarios

### 1. Weather Reliability

* location override
* session memory
* mismatch retry

---

### 2. Tool Refusal

```text
weather without tools
```

👉 Must refuse

---

### 3. Multi-Tool Execution

```text
weather + news + ip
```

👉 Must run in parallel

---

### 4. Routing Accuracy

* greeting → no agent
* factual → search
* system → tool

---

### 5. Synthesizer Quality

* no irrelevant data
* no hallucination
* clean formatting

---

## 🚨 Regression Guardrails

* ❌ No stale outputs
* ❌ No duplicate tool calls
* ❌ No wrong location data
* ❌ No fake real-time responses

---

## 🎯 Goal

> **Break the system — then fix it.**