# 🤝 Contributing Guide

![Contributions](https://img.shields.io/badge/Contributions-Welcome-brightgreen)
![Code Style](https://img.shields.io/badge/Code%20Style-Structured-blue)

---

## 🧠 Philosophy

Jarvis is a **reliability-first AI system**.

Contributions must prioritize:

* correctness
* determinism
* system stability

Over:

* adding features blindly

---

## 🚀 Getting Started

1. Fork the repository
2. Clone your fork
3. Create a new branch

```bash
git checkout -b feature/your-feature-name
```

---

## 🧩 Contribution Types

You can contribute:

* 🐛 Bug fixes
* ⚡ Performance improvements
* 🧠 Agent logic enhancements
* 📄 Document intelligence improvements
* 🎤 Voice/runtime stability fixes
* 📄 Documentation improvements

---

## ⚙️ Code Guidelines

* Follow existing project structure
* Keep modules **single-responsibility**
* Avoid mixing logic across layers (`core`, `agent`, `services`, `interface`, `frontend`)
* Maintain clear and readable code
* Keep deterministic tools deterministic (no hidden LLM dependence)
* Keep document file selection system-controlled (no model-triggered UI actions)

---

## 🧭 Commit Style (IMPORTANT)

Use structured commits:

```bash
feat(agent): add planner optimization
fix(weather): correct location mismatch
refactor(search): remove redundant parsing
docs: update README
```

---

## 🛡️ Reliability Rules

All contributions must ensure:

* ❌ No hallucinated real-time data
* 🔁 Tool outputs are validated
* ⚡ Deterministic commands remain stable
* 🧠 Routing logic is not broken
* 🧾 Identity guardrails remain intact
* 🔐 No credentials are introduced in source/docs

---

## 🧪 Before Submitting PR

Checklist:

* [ ] Code runs without errors
* [ ] No breaking changes to existing features
* [ ] Tested key flows (weather, search/news, IP, system)
* [ ] Tested at least one document flow (PDF/DOCX/image) if touching `services/document` or runtime routing
* [ ] Ran stress suite (`python -m unittest discover -s tests/stress -p "test_*.py" -v`) for document-performance-sensitive changes
* [ ] No unnecessary tool calls
* [ ] No duplicate logic introduced
* [ ] Updated docs when behavior or configuration changed

---

## 🔍 Pull Request Process

1. Clearly describe your changes
2. Explain **why** the change is needed
3. Mention affected modules
4. Attach test cases if relevant
5. Mention any `.env` variable changes

---

## 🚨 What Not to Do

* ❌ Do not bypass validation layers
* ❌ Do not hardcode responses
* ❌ Do not introduce hallucinated outputs
* ❌ Do not break routing precedence
* ❌ Do not commit local secrets or private keys
* ❌ Do not add undocumented runtime flags or config keys

---

## 👤 Maintainer

**Deepak Rakshit**
Building reliable AI systems 🚀