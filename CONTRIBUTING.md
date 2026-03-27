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
* 📄 Documentation improvements

---

## ⚙️ Code Guidelines

* Follow existing project structure
* Keep modules **single-responsibility**
* Avoid mixing logic across layers (`core`, `agent`, `services`)
* Maintain clear and readable code

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

---

## 🧪 Before Submitting PR

Checklist:

* [ ] Code runs without errors
* [ ] No breaking changes to existing features
* [ ] Tested key flows (weather, search, IP, system)
* [ ] No unnecessary tool calls
* [ ] No duplicate logic introduced

---

## 🔍 Pull Request Process

1. Clearly describe your changes
2. Explain **why** the change is needed
3. Mention affected modules
4. Attach test cases if relevant

---

## 🚨 What Not to Do

* ❌ Do not bypass validation layers
* ❌ Do not hardcode responses
* ❌ Do not introduce hallucinated outputs
* ❌ Do not break routing precedence

---

## 👤 Maintainer

**Deepak Rakshit**
Building reliable AI systems 🚀