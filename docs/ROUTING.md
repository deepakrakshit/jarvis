# 🧭 Intelligent Routing

![Routing](https://img.shields.io/badge/Routing-Smart%20Agent-blue)
![Priority](https://img.shields.io/badge/Priority-Enforced-success)

---

## 🧠 Routing Strategy

Jarvis uses **priority-based routing**:

1. ⚡ Fast-path (no agent)
2. ⚙️ Deterministic tools
3. 🌐 Web search + synthesis
4. 🧠 LLM fallback

---

## ⚡ Fast-Path (Bypass Agent)

Handled instantly:

* greetings
* identity
* casual conversation

---

## ⚙️ Tool Routing

Triggered when query involves:

* weather
* IP
* system status
* speed test
* news
* internet search

---

## 🌐 Factual Routing

Jarvis uses search for:

* current events
* politics
* sports results
* verification queries

---

## 🛡️ Anti-Hallucination Rules

* Real-time data MUST use tools
* If tools are forbidden → REFUSE
* No guessing allowed

---

## 🤯 Ambiguity Handling

Example:

```text
"2025 season"
```

👉 Jarvis asks clarification instead of guessing

---

## 🎯 Design Goal

> **Correct routing > fast routing**