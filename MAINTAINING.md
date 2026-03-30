# 🛠️ Maintaining Guide

![Maintenance](https://img.shields.io/badge/Maintenance-Active-success)
![Policy](https://img.shields.io/badge/Policy-Reliability--First-blue)
![Validation](https://img.shields.io/badge/Validation-Required-important)
![Architecture](https://img.shields.io/badge/Architecture-Modular-purple)

---

## 🧠 Core Principle

> **Reliability > Features**

All changes must preserve **deterministic behavior, correctness, and system stability**.

If a feature compromises reliability, it must be rejected or redesigned.

---

## 🧩 Ownership Boundaries

Each module has strict responsibilities:

* `app/` → launchers and runtime entrypoints
* `core/` → orchestration, routing, and global policy
* `agent/` → planning, validation, execution, synthesis loop
* `services/` → deterministic tools and external integrations
* `services/document/` → parsing, OCR, vision, fusion, cache pipeline
* `interface/` → CLI / UI bridges
* `frontend/` → GUI layer only
* `voice/` → speech pipeline internals
* `memory/` → session and persistent context

👉 Do not mix responsibilities across layers.

---

## ⚙️ Routing-Safe Change Rules

All routing logic must remain **explicit and predictable**.

Rules:

1. Maintain strict intent precedence in `core/runtime.py`
2. Never allow policy/guardrails to block valid executable intents
3. Route factual/current queries through **internet search + synthesis**
4. Keep operational commands deterministic:

   * weather
   * public IP / network location
   * system status
   * speed test
   * temporal snapshot
5. Keep document requests in the document service branch with file validation
6. Avoid overly broad matching:

   * ❌ `check`, `again`, vague keywords
   * ✅ use constrained, context-aware patterns

---

## 🌐 Source Priority Contract

Every response must follow this hierarchy:

| Type                     | Source                          |
| ------------------------ | ------------------------------- |
| Real-time / factual      | Web search + synthesis          |
| System / operational     | Deterministic services          |
| Document analysis        | Parser/OCR/Vision fused pipeline |
| Conceptual / explanation | LLM fallback (brief by default) |
| User context             | Memory-backed retrieval         |

> ⚠️ Violating this contract = regression

---

## 🛡️ Reliability Guarantees

All changes must preserve:

* ❌ No hallucinated real-time data
* 🔁 Retry + validation for tool outputs
* 🎯 Correct tool selection and routing
* ⚡ Deterministic execution where required
* 🧠 Session consistency (e.g., location memory)
* 🧾 Assistant identity enforcement for final responses
* 📄 Safe document analysis behavior (path validation + graceful fallback)

---

## 📦 Dependency Management

* Install/update via:

  ```bash
  pip install -r requirements.txt
  ```

* Keep dependencies:

  * minimal
  * production-relevant
  * documented if native/binary required
* Treat OCR/document dependencies as optional at runtime but tested in CI/dev where enabled

---

## ▶️ Run Matrix

```bash
python jarvis.py            # Default (CLI + GUI)
python jarvis.py --cli      # CLI only
python jarvis.py --gui      # GUI only
python app/main.py --mode both|cli|gui
```

---

## 🧪 Regression Checklist (MANDATORY)

Before merging any change:

### ✅ Functional Checks

* Syntax validation across modified files
* No runtime errors
* Stress suite run for document performance-sensitive changes

### 🔥 Critical Scenarios

* Factual query (e.g., office holder)
* Real-time query (weather/news via internet search)
* Speed test (start → result flow)
* Internet search + follow-up query
* Context correction flow
* Document analysis (PDF or DOCX) with file select + summary output
* Document follow-up Q&A using active context
* Multi-document compare flow with at least two files

### ⚠️ Safety Checks

* No stale or cached results returned as fresh
* No hallucinated outputs
* No routing misclassification
* No duplicated confidence/response artifacts
* No identity/persona drift in assistant responses

---

## 🚀 Release Checklist

Before every release:

1. Update docs in `docs/`
2. Sync `README.md` examples with behavior
3. Verify `.env` variables match `core/settings.py`
4. Verify `.env.example` includes all active keys and defaults
5. Smoke test:

   * CLI mode
   * GUI mode
   * document flow
6. Stress test:

   * `python -m unittest discover -s tests/stress -p "test_*.py" -v`

---

## 📚 Documentation Map

* `docs/ARCHITECTURE.md` → system design
* `docs/ROUTING.md` → intent routing rules
* `docs/COMMANDS.md` → supported commands
* `docs/TESTING.md` → validation strategy
* `docs/TROUBLESHOOTING.md` → common issues

---

## 🚨 Golden Rule

> **If you cannot confidently explain why a change is safe — do not merge it.**

---

## 👤 Maintained By

**Deepak Rakshit**
Building reliable, production-grade AI systems 🚀