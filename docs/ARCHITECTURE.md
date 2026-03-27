# 🏗️ Architecture Overview

![Architecture](https://img.shields.io/badge/System-Agent%20Architecture-purple)
![Flow](https://img.shields.io/badge/Flow-Deterministic%20%2B%20AI-blue)
![Validation](https://img.shields.io/badge/Validation-Enforced-success)

---

## 🧠 System Overview

Jarvis is a **modular AI agent system** combining:

* ⚙️ Deterministic local services
* 🌐 Real-time web search
* 🧠 LLM-based reasoning & synthesis

Unlike traditional assistants, Jarvis follows a **plan → validate → execute → synthesize** pipeline.

---

## 🔄 High-Level Flow

```text
User Input
   ↓
Smart Router (fast-path vs agent)
   ↓
Planner → Validator → Executor → Tools
   ↓
Synthesizer
   ↓
Final Response
```

---

## ⚙️ Execution Pipeline

### 1. Smart Routing

Handled in `core/runtime.py`

* Fast-path for simple queries (greetings, identity)
* Agent loop for tool-capable queries

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
* News
* Internet search
* System status
* Public IP
* Speed test

All tools return **raw structured data (no summarization)**

---

### 6. Synthesizer (`agent/synthesizer.py`)

* Converts tool outputs → final response
* Applies:

  * relevance filtering
  * tone/personality
  * safety rules

---

## 🧩 Key Modules

* `core/runtime.py` → orchestration + routing
* `agent/` → full AI agent system
* `services/` → deterministic tool layer
* `memory/` → session & persistent context
* `voice/` → speech pipeline

---

## 🛡️ Reliability Model

Jarvis enforces strict reliability:

* ❌ No hallucinated real-time data
* 🔁 Retry on invalid tool outputs
* 🎯 Deterministic execution for system commands
* 🌐 Verified sources for factual queries

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

---

## 🚨 Golden Rule

> **Never trust raw tool output without validation.**