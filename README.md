# 🤖 Jarvis — Autonomous AI Assistant

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Status](https://img.shields.io/badge/Status-Active-success)
![AI](https://img.shields.io/badge/AI-Agent%20Architecture-purple)
![Build](https://img.shields.io/badge/Build-Passing-brightgreen)

> A real-time, production-style AI assistant powered by tool reasoning, validation, and structured decision-making.

<p align="center">
  <img src="assets/jarvis_ui.gif" width="700"/>
</p>

---

## 🚀 Overview

Jarvis is not just a chatbot.

It is a **modular AI agent system** that:

* 🧠 Plans actions (Planner)
* 🛡️ Validates outputs (Validator)
* ⚙️ Executes tools (Executor)
* 🧾 Synthesizes responses (Synthesizer)

All orchestrated in a **real-time intelligent runtime**.

---

## ✨ Core Highlights

* 🧠 **AI-based reasoning (not just commands)**
* ⚡ **Parallel tool execution (async)**
* 🌍 **Real-time data (weather, news, IP, search)**
* 🧩 **Modular agent architecture**
* 🔁 **Retry + validation system (no blind trust)**
* 🚫 **No hallucination policy for real-time data**
* 🧭 **Smart routing (fast-path vs agent loop)**
* 💾 **Session-aware memory (location, context)**

---

## 🏗️ Architecture

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

## ⚙️ Features

### 🧠 Intelligence

* Query understanding & routing
* Multi-step planning
* Context-aware responses

### 🌐 Real-time Tools

* 🌦️ Weather (validated + retry)
* 📰 News (filtered + relevant)
* 🔍 Internet search (raw + AI synthesis)
* 🌍 Public IP
* 📊 System status / speed test

### 🧩 System Capabilities

* CLI + GUI modes
* Voice support (TTS + STT)
* Persistent memory
* Correction workflow

---

## 🧪 Example Queries

```bash
weather in delhi
latest ai news
what is my ip
weather in delhi and latest ai news
i am in greater noida
weather?
```

---

## 🚀 Getting Started

### 1. Clone

```bash
git clone https://github.com/deepakrakshit/jarvis.git
cd jarvis
```

---

### 2. Setup Environment

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

Create `.env`:

```env
GROQ_API_KEY=your_key_here
SERPER_API_KEY=your_key_here
```

---

### 5. Run Jarvis

```bash
python jarvis.py
```

---

## 🖥️ Run Modes

```bash
python jarvis.py --cli   # Terminal mode
python jarvis.py --gui   # Desktop UI
```

---

## 📁 Project Structure

```text
agent/        AI agent system (planner, executor, synthesizer, loop)
core/         runtime orchestration
services/     external tools (weather, search, news)
memory/       session & persistence
voice/        speech systems
frontend/     GUI
interface/    CLI bridge
utils/        helpers
docs/         documentation
```

---

## 🧠 Design Principles

* ❌ No blind trust in tools
* ✅ Always validate outputs
* 🔁 Retry on failure
* 🚫 No fake real-time answers
* ⚡ Prefer parallel execution
* 🎯 Minimal, correct, deterministic actions

---

## 🛠️ Tech Stack

* **Python**
* **Groq API** (LLM inference)
* **Serper API** (search)
* **PyAutoGUI / system tools**
* **psutil** (system monitoring)
* **TTS/STT engines**

---

## 🗺️ Roadmap

* [ ] Plugin system for custom tools
* [ ] Multi-agent collaboration
* [ ] Vision integration (screen understanding)
* [ ] Mobile companion app
* [ ] Autonomous task execution

---

## 📜 License

This project is licensed under the **MIT License**.

---

### ⚠️ AI & Usage Disclaimer

* Jarvis is an **AI-assisted system**, not fully autonomous.
* Real-time outputs depend on external APIs.
* Users should verify critical information before acting.

---

## 🤝 Contributing

PRs are welcome.

For major changes:

* Open an issue first
* Keep commits structured (`feat`, `fix`, `refactor`)

---

## ⭐ Support

If you like this project:

* ⭐ Star the repo
* 🍴 Fork it
* 🧠 Suggest improvements

---

## 👤 Author

**Deepak Rakshit**
Building real-world AI systems 🚀