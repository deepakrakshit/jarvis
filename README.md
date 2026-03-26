# 🤖 Jarvis CLI

Jarvis is a hybrid AI assistant that combines **deterministic local tools**, **real-time web search**, and a **conversational fallback LLM**.

Built for reliability and practical usage:

* ⚡ Commands execute deterministically
* 🌐 Real-time queries use live search
* 🧠 Conversational responses stay concise and useful

---

## ✨ Features

* 🧠 Intelligent query routing (command vs search vs conversation)
* 🌐 Real-time internet search (Serper API)
* 💾 Persistent memory (context-aware interactions)
* 🖥️ System tools (IP, speed test, system status)
* 🌦️ Weather and location services
* 🎤 Voice support (TTS + STT)
* 🧩 CLI + GUI hybrid runtime
* 🔁 Correction workflow with confidence output

---

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/deepakrakshit/jarvis.git
cd jarvis
```

### 2. Create virtual environment

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

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file:

```
GROQ_API_KEY=your_key_here
SERPER_API_KEY=your_key_here
```

### 5. Run Jarvis

```bash
python jarvis.py
```

---

## 🧪 Run Modes

```bash
python jarvis.py --cli   # Terminal mode
python jarvis.py --gui   # Desktop UI
```

---

## 💬 Example Usage

### 🔍 Search

```
search on internet who won IPL 2025
who is the current PM of India
```

### ⚙️ System Commands

```
run speed test
what is my current IP
give me system status
```

### 🧠 Context Awareness

```
who won IPL 2025
which team won that season
that's wrong
```

---

## 📁 Project Structure

```
app/         entrypoints and runtime modes
core/        orchestration and configuration
services/    tools (search, weather, network)
memory/      persistent storage
interface/   CLI bridge
frontend/    GUI assets
voice/       speech systems
utils/       helpers
docs/        documentation
```

---

## 🛠️ Tech Stack

* Python
* Groq (LLM inference)
* Serper (search API)
* PyWebView (GUI)
* Piper TTS / RealtimeTTS
* psutil (system monitoring)

---

## 📌 Roadmap

* [ ] Plugin system for tools
* [ ] Multi-agent task execution
* [ ] Offline fallback LLM
* [ ] Mobile companion app

---

## 🤝 Contributing

Pull requests are welcome. For major changes, open an issue first.

---

## 📄 License

This project is licensed under the **MIT License**.

```
MIT License

Copyright (c) 2026 Jarvis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files...
```

*(Replace "Jarvis" with your name or GitHub username if needed)*

---

## ⚠️ Disclaimer

This project is intended for educational and personal productivity use.
It is not a fully autonomous system and may require supervision for critical tasks.

---

## ⭐ Support

If you find this project useful:

* ⭐ Star the repo
* 🍴 Fork it
* 🧠 Suggest improvements

---
