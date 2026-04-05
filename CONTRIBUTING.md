<div align="center">

[![Header](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=160&section=header&text=Contributing%20to%20JARVIS&fontSize=36&fontColor=ffffff&animation=twinkling&fontAlignY=50)](.)

[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-E91E7F?style=for-the-badge&logo=github&logoColor=white)](.)
[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-2.1-4BADE8?style=for-the-badge)](.)
[![Philosophy](https://img.shields.io/badge/Philosophy-Reliability%20First-00C853?style=for-the-badge)](.)

</div>

---

## 🧠 Philosophy

JARVIS is a **reliability-first AI system**.

Before writing a single line of code, internalize this:

> **Correctness and determinism always outweigh feature velocity.**

A new feature that introduces hallucinated output, breaks routing precedence, or bypasses validation will be rejected — not because of preference, but because the entire value proposition of JARVIS rests on users being able to **trust every response**.

---

## 📋 Before You Start

1. **Read the architecture** — [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
2. **Understand routing** — [`docs/ROUTING.md`](docs/ROUTING.md)
3. **Know the test requirements** — [`docs/TESTING.md`](docs/TESTING.md)
4. **Check open issues** — look for `good first issue` or `help wanted` labels
5. **For significant changes** — open an issue first and discuss the approach

---

## 🚀 Getting Started

```bash
# 1. Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/jarvis.git
cd jarvis

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

# 3. Install all dependencies
pip install -r requirements.txt

# 4. Set up environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY (required) and HF_TOKEN (optional)

# 5. Create your feature branch
git checkout -b feat/your-feature-name
```

---

## 🧩 Contribution Types

| Type | Description | Examples |
|---|---|---|
| 🐛 **Bug Fix** | Fix incorrect behavior | Wrong routing, incorrect output, crashes |
| ⚡ **Performance** | Make things faster or leaner | Reduce LLM calls, optimize OCR workers |
| 🧠 **Agent Logic** | Improve planning or synthesis | Better planner prompts, smarter tool selection |
| 📄 **Document Pipeline** | Parser, OCR, vision, or Q&A improvements | Better table extraction, entity recognition |
| 🎤 **Voice / UX** | TTS stability, UI improvements | Chunk tuning, skip behavior, UI polish |
| 📖 **Documentation** | Improve clarity or coverage | Fix outdated examples, add missing commands |
| 🧪 **Tests** | Add stress tests or fix flaky ones | New routing tests, edge case coverage |

---

## ⚙️ Code Guidelines

### Module Boundaries

**Never mix responsibilities across these layers:**

```
core/         →  Orchestration, routing policy, settings
agent/        →  Planning, validation, execution, synthesis
services/     →  Tool implementations and external integrations
services/document/  →  Document intelligence pipeline
services/actions/coding_assist.py → Bounded coding/scaffolding orchestration
interface/    →  CLI / GUI bridge adapters
frontend/     →  Static assets and UI rendering only
voice/        →  Speech pipeline internals
memory/       →  Session and persistent context
```

### Rules

- ✅ Keep every module **single-responsibility**
- ✅ Keep **deterministic tools deterministic** — no hidden LLM calls inside tool functions
- ✅ If a service intentionally uses LLM reasoning (document reasoning/coding assist), keep prompts explicit and outputs schema-validated
- ✅ Keep **file selection system-controlled** — the LLM never triggers the file picker
- ✅ Validate tool outputs before synthesis — never assume a tool succeeded
- ✅ Handle errors gracefully with **human-readable fallbacks** — no raw dict/payload leakage in responses
- ✅ Add `.env` documentation when introducing new environment variables
- ❌ Do not bypass the validator in `agent/validator.py`
- ❌ Do not hardcode real-time data (IP addresses, weather values, prices)
- ❌ Do not add hidden global mutable state to `services/` tools

---

## 📝 Commit Message Convention

JARVIS uses **Conventional Commits**. This is strictly enforced in PR reviews.

### Format

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

### Types

| Type | When to Use |
|---|---|
| `feat` | A new feature or capability |
| `fix` | A bug fix |
| `refactor` | Code restructuring without behavior change |
| `perf` | A performance improvement |
| `test` | Adding or updating tests |
| `docs` | Documentation only changes |
| `style` | Formatting, whitespace (no logic change) |
| `chore` | Build process, dependency updates |

### Scope Examples

```bash
feat(agent): add planner step deduplication for multi-tool queries
fix(weather): correct session location fallback for "weather again" queries
fix(runtime): prevent connectivity phrases from routing to search-policy handler
perf(document): reduce OCR worker idle time with adaptive chunking
test(stress): add ultra-fast reasoning latency regression test
docs(routing): document explicit picker vs file manager disambiguation
refactor(synthesizer): extract relevance filtering into standalone method
```

---

## ✅ PR Checklist

Before submitting, confirm **every applicable item**:

### 🔧 Code Quality
- [ ] Code runs without errors in a clean venv
- [ ] No `print()` debug statements left in
- [ ] No unnecessary imports added
- [ ] No breaking changes to existing public interfaces

### 🧪 Testing
- [ ] Fast validation passes: `python -m compileall app agent core services interface voice tests`
- [ ] Stress suite passes: `python -m unittest discover -s tests/stress -p "test_*.py" -v`
- [ ] For document-perf changes: stress suite run and results reviewed
- [ ] For routing changes: critical test scenarios manually verified

### 🔁 Flow Verification (check all that apply)
- [ ] Weather query (current + forecast + rain probability)
- [ ] Connectivity query (`check internet connectivity`)
- [ ] Search/factual query (`who won ipl 2025 season`)
- [ ] Document flow (`analyze document` → select file → Q&A)
- [ ] `open file explorer` → routes to app control (**not** document picker)
- [ ] `open file picker` → routes to document selection flow
- [ ] `max volume` / `min brightness` → maps to safe `set_*` action
- [ ] App `open` → `close it` → uses remembered app name

### 📄 Documentation
- [ ] Updated `docs/COMMANDS.md` if new commands were added
- [ ] Updated `docs/ROUTING.md` if routing rules changed
- [ ] Updated `.env.example` if new environment variables were added
- [ ] Updated `docs/TROUBLESHOOTING.md` if a new known failure mode exists

---

## 🔍 Pull Request Process

1. **Title**: Use the same `type(scope): description` format as commit messages
2. **Description**: Explain *what* changed and *why* it was needed
3. **Affected modules**: List every module touched
4. **Test evidence**: Paste relevant stress suite output or manual test results
5. **Breaking changes**: Explicitly call out any backward-incompatible behavior
6. **`.env` changes**: List any new or removed environment variables

---

## 🚫 What Will Be Rejected

| ❌ Anti-pattern | Reason |
|---|---|
| Bypassing `agent/validator.py` | Removes safety contract |
| Hardcoding real-time responses | Breaks reliability guarantee |
| LLM calls inside tool `fn` functions | Breaks determinism |
| Model-triggered file picker | Breaks system-controlled file selection |
| Raw tool payload in user-facing response | Leaks internal structure |
| Undocumented `runtime` flags | Breaks maintainability |
| Committing `.env` or API keys | Security violation |
| Broad regex matchers (`check`, `again`) in routing | Creates routing collisions |

---

## 🙏 Thank You

Every contribution — from fixing a typo to adding a new document parser — makes JARVIS more reliable for everyone.

If you're unsure whether your idea fits, open an issue and ask. The worst that can happen is a clarifying conversation.

---

<div align="center">

**Built with reliability. Improved with community.**

[![Footer](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=100&section=footer)](.)

</div>