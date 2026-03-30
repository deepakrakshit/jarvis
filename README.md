# 🤖 Jarvis — Autonomous AI Assistant

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Status](https://img.shields.io/badge/Status-Active-success)
![AI](https://img.shields.io/badge/AI-Agent%20%2B%20Document%20Intelligence-purple)
![Build](https://img.shields.io/badge/Build-Validated-brightgreen)

> A real-time, production-style assistant with deterministic tools, agent planning, and multimodal document intelligence.

<p align="center">
  <img src="assets/jarvis_ui.gif" width="700"/>
</p>

---

## 🚀 Overview

Jarvis is a modular assistant runtime that combines:

* 🧠 Local intent routing for fast responses
* ⚙️ Agent loop for tool planning and execution
* 📄 Document intelligence pipeline (PDF, DOCX, image)
* 🎤 Realtime voice output + desktop telemetry UI

It is designed around reliability-first behavior: deterministic tools where required, validation before synthesis, and clear fallback paths.

---

## ✨ Core Highlights

* 🧭 **Priority intent routing** (local fast-path + agent fallback)
* 🧠 **Planner → Validator → Executor → Synthesizer** loop
* 🌐 **Live internet evidence** via Serper (including news-style queries)
* 📄 **Hybrid document pipeline** (text parsing + OCR + vision + reasoning)
* 🧩 **Retrieval-first document Q&A** with active-document follow-up context
* 🔍 **Multi-document comparison** with evidence-backed citations
* 🔁 **Validation and retry controls** for external integrations
* 🚫 **Identity and hallucination guardrails** for assistant responses
* 💾 **Session-aware memory** (name, location, search context)
* ⏭️ **Skip current voice reply** control in desktop UI

---

## 🏗️ Architecture

```text
User Input
   ↓
Intent Router (fast local intents)
   ↓ (if not handled)
Agent Loop: Planner → Validator → Executor → Tools
   ↓
Synthesizer + Personality + Identity Guardrails
   ↓
Final Response (Text + Realtime TTS)
```

Document requests follow a dedicated branch:

```text
Document Intent
   ↓
File Selection + Validation
   ↓
Parser/OCR/Vision Fusion Pipeline
   ↓
Structured Intelligence + Active Document Index
   ↓
Follow-up Q&A / Multi-document Compare
```

---

## ⚙️ Features

### 🧠 Intelligence Runtime

* Priority intent routing for greetings, wellbeing, correction, and profile memory
* Agent planning for multi-tool or factual queries
* Identity enforcement to prevent persona drift in final output

### 🌐 Real-Time Tooling

* 🌦️ Weather (location-aware, session-supported)
* 🔍 Internet search (web + news result surfaces via Serper)
* 🌍 Public IP + IP-based location
* ⚙️ System status snapshots
* 📶 Speedtest workflow with follow-up interpretation
* 🕒 Temporal snapshots (time/date)

### 📄 Document Intelligence

* PDF, DOCX, DOC (with `.doc` conversion guidance), and image support
* OCR with PaddleOCR + scanned-PDF handling
* Vision extraction via Groq vision model chain (default: Llama 4 Scout)
* Fused reasoning pipeline with structured output (summary, insights, key points, tables, entities)
* Follow-up Q&A over active documents without forcing full reprocessing
* Multi-document compare mode for pricing/risk/feature decisions
* SQLite + in-memory cache layers for repeat analyses
* Configurable high-throughput tuning knobs for OCR, vision workers, and reasoning payload budgets

### 🎤 Voice + Desktop UX

* Realtime Piper TTS playback
* CLI and desktop modes
* Live metrics and transcript view in frontend
* UI skip button to interrupt active speech safely

---

## 🧪 Example Queries

```bash
weather in delhi
latest ai news
who is the prime minister of india
what is my ip
run speed test
i am in greater noida
weather?
analyze document
summarize this pdf
compare these documents
what is the pricing in this document
list risks from the file I uploaded
how r u
```

---

## 🚀 Getting Started

### 1. Clone

```bash
git clone https://github.com/deepakrakshit/jarvis.git
cd jarvis
```

---

### 2. Create Virtual Environment

```bash
python -m venv venv
```

Activate:

```bash
# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

---

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 4. Configure Environment

Use the project template:

```bash
# Windows
copy .env.example .env

# macOS/Linux
cp .env.example .env
```

Minimum required keys:

* `GROQ_API_KEY`
* `SERPER_API_KEY`

Optional but recommended:

* `HF_TOKEN` (voice model file download support)

See `.env.example` for the complete configuration set, including document cache, OCR/vision worker scaling, parser image limits, and adaptive reasoning budgets.

---

### 5. Run Jarvis

```bash
python jarvis.py
```

---

## 🖥️ Run Modes

```bash
python jarvis.py --cli
python jarvis.py --gui
python app/main.py --mode both
python app/main.py --mode cli
python app/main.py --mode gui
```

---

## 📁 Project Structure

```text
agent/              planner, validator, executor, synthesizer, loop
app/                launchers for CLI/GUI/both
core/               runtime orchestration, policy, settings
frontend/           desktop webview UI assets
interface/          Python ↔ UI bridge APIs
memory/             persistent memory store
services/           weather/search/network + document intelligence
services/document/  parser, OCR, vision, fusion, cache pipeline
voice/              STT/TTS runtime
docs/               architecture, routing, commands, testing, troubleshooting
```

---

## 🧠 Design Principles

* ❌ No blind trust in external outputs
* ✅ Validate before finalizing responses
* 🔁 Retry only where safe and meaningful
* 🚫 Do not fabricate real-time data
* 🎯 Keep deterministic flows deterministic
* ⚡ Optimize for reliability before novelty

---

## 🛠️ Tech Stack

* **Python 3.10+**
* **Groq API** (planner/synthesis/general completion)
* **Serper API** (internet/news evidence retrieval)
* **Groq Vision** (document vision extraction)
* **PaddleOCR + PyMuPDF + pdfplumber + python-docx + Pillow** (document processing)
* **RealtimeTTS + Piper + PyAudio** (voice output/input)
* **pywebview + Three.js frontend** (desktop UI)

---

## 📚 Documentation Map

* `docs/ARCHITECTURE.md`
* `docs/ROUTING.md`
* `docs/COMMANDS.md`
* `docs/TESTING.md`
* `docs/TROUBLESHOOTING.md`

---

## 🧪 Stress Validation

Run stress-focused checks:

```bash
python -m unittest discover -s tests/stress -p "test_*.py" -v
```

Current stress suite includes:

* retrieval throughput
* entity extraction stability
* QA engine output-shape checks
* reasoning payload budget enforcement
* ultra-fast deterministic reasoning latency checks
* PDF parser limits (table-page cap + render short-circuit)
* text-rich fast lane behavior (skip vision/OCR when query is non-visual)

---

## 🗺️ Roadmap

* [ ] Plugin tool packs
* [ ] Deeper multi-agent planning strategies
* [ ] Expanded multilingual voice + TTS safety controls
* [ ] Document pipeline benchmark suite
* [ ] Optional cloud memory sync

---

## 📜 License

This project is licensed under the **MIT License**.

---

### ⚠️ AI & Usage Disclaimer

* Jarvis is AI-assisted, not an autonomous operator.
* Live answers depend on external APIs and network quality.
* Validate critical decisions with independent confirmation.

---

## 🤝 Contributing

Contributions are welcome. For significant changes, open an issue first and use structured commits (`feat`, `fix`, `refactor`, `docs`, etc.).

---

## ⭐ Support

If this project helps you:

* ⭐ Star the repo
* 🍴 Fork it
* 🧠 Share improvement ideas

---

## 👤 Author

**Deepak Rakshit**
Building reliable real-world AI systems 🚀