# 🧭 Intelligent Routing

![Routing](https://img.shields.io/badge/Routing-Smart%20Agent-blue)
![Priority](https://img.shields.io/badge/Priority-Enforced-success)

---

## 🧠 Routing Strategy

Jarvis uses **priority-based routing**:

1. ⚡ Local intent router (fast-path)
2. ⚙️ Agent loop (plan → validate → execute → synthesize)
3. 🌐 Tool-backed factual answer synthesis
4. 🧠 Streamed LLM fallback when no tool route is suitable

---

## ⚡ Local Intent Router

Handled before the agent loop:

* correction feedback
* user name set/query
* greetings and wellbeing
* search-policy feedback
* abuse feedback redirect
* document intent (when document service is available)

---

## ⚙️ Agent/Tool Routing

Triggered when query involves:

* weather
* internet/news lookups
* factual verification
* speed test
* IP/location
* system status/time snapshots
* update checks

The agent planner emits minimal tool plans, validator enforces schemas, and executor handles retries/timeouts.

---

## 🌐 Factual Routing

Jarvis routes current/factual questions through internet evidence and synthesis, for example:

* office holder queries
* recent events
* season winners/results
* breaking/news-like prompts

---

## 📄 Document Routing

Document-like prompts (analyze/summarize/read PDF/DOCX/image) are routed to the document branch:

* file selection is system-controlled
* path/type/size validation runs first
* parser/OCR/vision/fusion pipeline generates final summary

If optional dependencies are unavailable, Jarvis returns a graceful availability message.

---

## 🛡️ Anti-Hallucination Rules

* Real-time/factual data must come from tools or web evidence
* Assistant identity is enforced on final responses
* Disallowed-tool requests for live data are refused
* Ambiguous prompts should request clarification

---

## 🤯 Ambiguity Handling

Example:

```text
2025 season
```

Jarvis asks for context (for example, IPL 2025 season) instead of guessing.

---

## 🎯 Design Goal

> **Correct routing > fast routing**