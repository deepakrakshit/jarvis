# 🏗️ Architecture Overview

![Architecture](https://img.shields.io/badge/System-Agent%20Architecture-purple)
![Flow](https://img.shields.io/badge/Flow-Deterministic%20%2B%20AI-blue)
![Validation](https://img.shields.io/badge/Validation-Enforced-success)

---

## 🧠 System Overview

Jarvis is a **modular AI agent system** combining:

* ⚙️ Deterministic local services
* 🌐 Real-time web search evidence
* 🧠 LLM-based reasoning & synthesis
* 📄 Multimodal document intelligence (parse + OCR + vision)

Unlike traditional assistants, Jarvis follows a **plan → validate → execute → synthesize** pipeline.

---

## 🔄 High-Level Flow

```text
User Input
  ↓
Intent Router (priority local intents)
  ↓ (if not handled)
Planner → Validator → Executor → Tools
   ↓
Synthesizer
  ↓
Personality + Identity Guardrails
   ↓
Final Response
```

---

## 📄 Document Flow

```text
Document Intent
  ↓
File Selector + Path Validation
  ↓
DocumentService
  ↓
Parser + OCR + Vision + Fusion
  ↓
Structured Intelligence + Display Summary
```

---

## ⚙️ Execution Pipeline

### 1. Smart Routing

Handled in `core/runtime.py`

* Priority local intents (correction, greeting, wellbeing, profile, document)
* Agent loop for tool-capable and factual queries
* Final fallback to streamed Groq completion

---

### 2. Planner (`agent/planner.py`)

* Converts user query → structured plan
* Selects optimal tools
* Avoids redundant steps
* Produces reasoning (internal only)

---

### 3. Validator (`agent/validator.py`)

* Validates:

  * tool names
  * input schema
  * output correctness
* Detects mismatches (e.g., wrong weather location)
* Triggers retry if needed

---

### 4. Executor (`agent/executor.py`)

* Executes tools:

  * sequential OR parallel (async)
* Handles:

  * timeouts
  * exceptions
  * retries

---

### 5. Tools (`services/`)

* Weather
* Internet search (including news-style queries)
* System status
* Public IP
* Speed test
* Temporal snapshot
* Document analysis (optional when dependencies are available)

All tools return **raw structured data (no summarization)**

---

### 6. Synthesizer (`agent/synthesizer.py`)

* Converts tool outputs → final response
* Applies:

  * relevance filtering
  * tone/personality
  * safety rules

---

### 7. Voice + UI Bridge (`interface/`, `frontend/`, `voice/`)

* Realtime TTS chunk queue and playback
* API activity + speaking/listening mode events
* Desktop skip control for active speech interruption
* Live telemetry surface in frontend

---

## 🧩 Key Modules

* `core/runtime.py` → orchestration + routing
* `agent/` → full AI agent system
* `services/` → deterministic tool layer
* `services/document/` → document intelligence pipeline modules
* `memory/` → session & persistent context
* `voice/` → speech pipeline
* `interface/` + `frontend/` → desktop UI bridge and rendering

---

## 🛡️ Reliability Model

Jarvis enforces strict reliability:

* ❌ No hallucinated real-time data
* 🔁 Retry on invalid tool outputs
* 🎯 Deterministic execution for system commands
* 🌐 Verified sources for factual queries
* 🧾 Identity enforcement on final assistant output
* 📄 Safe document path validation before analysis

---

## 💾 State & Memory

Stored in:

```text
data/user_memory.json
```

Includes:

* user preferences
* session location
* last query context
* system state snapshots
* last speedtest snapshot metadata

---

## 🚨 Golden Rule

> **Never trust raw tool output without validation.**