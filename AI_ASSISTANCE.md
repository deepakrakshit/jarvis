<div align="center">

[![Header](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=160&section=header&text=AI%20Assistance%20Policy&fontSize=36&fontColor=ffffff&animation=twinkling&fontAlignY=50)](.)

[![AI](https://img.shields.io/badge/AI-Assisted%20Development-7C3AED?style=for-the-badge&logo=openai&logoColor=white)](.)
[![Control](https://img.shields.io/badge/Control-Human--in--Loop-00C853?style=for-the-badge)](.)
[![Validation](https://img.shields.io/badge/Validation-Mandatory-F55036?style=for-the-badge)](.)
[![Trust](https://img.shields.io/badge/AI%20Output-Untrusted%20Proposals-F7C948?style=for-the-badge)](.)

</div>

---

## 🧠 Philosophy

JARVIS uses AI as a **development accelerator — not a decision-maker**.

AI tooling increases speed and reduces friction on mechanical tasks. It does not replace engineering judgment, system design thinking, or responsibility for correctness. The human engineer is accountable for every line of code that ships — regardless of whether an AI drafted it.

> **AI suggests. Humans decide. Systems verify.**

---

## ⚙️ Where AI Is Used

AI assistance is appropriate for these categories of work:

| Category | Examples |
|---|---|
| **Code drafting** | Scaffolding new modules, boilerplate, repetitive implementations |
| **Structured refactoring** | Renaming, interface changes, pattern consistency |
| **Prompt engineering** | Iterating on planner system prompts, synthesizer instructions |
| **Document intelligence** | Pipeline tuning, reasoning payload optimization |
| **Documentation** | Writing, formatting, example generation |
| **Test scaffolding** | Generating initial test structures for known behaviors |

---

## 👨‍💻 Human Ownership — Non-Negotiable

The following decisions are always made by a human engineer:

| Decision Area | Why It Must Be Human |
|---|---|
| **System design and architecture** | Architectural decisions have cascading effects AI cannot fully model |
| **Routing logic changes** | Incorrect routing breaks the reliability contract for all users |
| **Debugging and root-cause analysis** | AI-generated diagnoses are hypotheses — humans verify with evidence |
| **Validation of AI output** | All generated code is treated as a proposal until tested |
| **Security and privacy decisions** | Risk tolerance is a human judgment, not an LLM inference |
| **Production readiness** | Shipping requires confidence that no automated tool can provide |
| **Release approval** | Every release tag is explicitly approved by the maintainer |

---

## 🛡️ Engineering Guardrails

All AI-generated code must satisfy these requirements before acceptance:

| Guardrail | Requirement |
|---|---|
| **Determinism** | Deterministic tool functions must remain free of hidden LLM calls |
| **Live data integrity** | Real-time queries must use verifiable external sources — never LLM training data |
| **Connectivity diagnostics** | Must remain deterministic and probe-backed — not inferred |
| **No fabrication** | Weather, IP, system data must come from live APIs only |
| **Memory honesty** | No false claims of memory persistence without actual storage writes |
| **Validation and retry** | All tool outputs must be validated; retry logic must be explicit |
| **Human-readable fallbacks** | No raw tool payload may leak into a user-facing response |
| **Document path safety** | File selection must remain system-controlled; paths must be validated |
| **Secret hygiene** | API keys must never appear in generated code, comments, or logs |

---

## 🔍 Review and Validation Process

Every AI-generated contribution is treated as:

> ⚠️ **An untrusted proposal — never as final truth**

The review process for AI-assisted code:

```
AI generates code
       ↓
Human reads it critically
       ↓
Does it follow module boundaries?
       ↓
Does it introduce hidden LLM calls?
       ↓
Is routing precedence intact?
       ↓
Does it pass the stress test suite?
       ↓
Are edge cases and failure modes handled?
       ↓
Is fallback behavior human-readable?
       ↓
ACCEPTED or REJECTED
```

**No AI-generated code is merged without explicit validation by a human engineer.**

For document pipeline changes, parser/OCR/vision fallback behavior must be validated under stress conditions. For performance changes, the stress suite must be run and results reviewed before merging.

---

## 🚨 Production Safety Boundaries

AI has **zero autonomous control** over the JARVIS system. It cannot:

| Capability | Status |
|---|---|
| Modify runtime behavior independently | ❌ Prohibited |
| Make deployment or release decisions | ❌ Prohibited |
| Execute actions without human validation | ❌ Prohibited |
| Override safety or validation layers | ❌ Prohibited |
| Trigger file-picker UI or bypass document path checks | ❌ Prohibited |
| Decide what constitutes a production-ready change | ❌ Prohibited |

---

## 📌 Why This Policy Exists

JARVIS is a system that users trust to give them accurate, real-time information and to execute OS-level actions correctly. That trust is only possible if every output is backed by validated, deterministic engineering — not probabilistic generation.

This policy ensures:

- The system remains **reliable and predictable** for every user
- Real-time data is **accurate and verifiable**, not hallucinated
- AI tooling is used **responsibly** — as an accelerator, not a replacement for thinking
- The project maintains **production-grade integrity** regardless of how it was built

---

<div align="center">

**Maintained by Deepak Rakshit**  
*Building reliable AI systems with human-first control* 🚀

[![Footer](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=100&section=footer)](.)

</div>