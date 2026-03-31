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
* session location declaration
* connectivity diagnostics
* search-policy feedback
* abuse feedback redirect
* document QA follow-up intent (active document context)
* document intent (when document service is available)

---

## ⚙️ Agent/Tool Routing

Triggered when query involves:

* weather
* connectivity
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

Weather-specific forecast and rain-probability requests are resolved through the deterministic weather service using daily forecast data.

---

## 📄 Document Routing

Document-like prompts (analyze/summarize/read PDF/DOCX/image) are routed to the document branch:

* file selection is system-controlled
* path/type/size validation runs first
* parser/OCR/vision/fusion pipeline generates final summary

Follow-up prompts (for example, pricing/risk/feature questions) are routed to
document QA when active document context is available. Compare prompts can route
to multi-document comparison when at least two active documents are present.

App commands (open/launch/start/close/terminate) are routed through the planner
to `app_control`, where deterministic resolver + OS verification decide outcome.

Explicit phrases like `open file picker` and `open document selector` route to
document selection flow. Phrases like `open file explorer` or `open file manager`
route to app control.

If optional dependencies are unavailable, Jarvis returns a graceful availability message.

---

## 🧮 Routing Precedence

When multiple tools could satisfy a prompt, Jarvis applies intent precedence:

1. explicit local-intent handlers (safe deterministic shortcuts)
2. app lifecycle verbs (`open`, `launch`, `close`, `terminate`) → `app_control`
3. explicit document picker/selector phrasing → document selection flow
4. factual/news queries → internet search evidence flow
5. generalized tool planning through planner/validator/executor

This ordering minimizes collisions between app control, document flow, and search tools.

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