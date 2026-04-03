<div align="center">

[![Header](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=160&section=header&text=Intelligent%20Routing&fontSize=38&fontColor=ffffff&animation=twinkling&fontAlignY=50)](.)

[![Routing](https://img.shields.io/badge/Routing-Priority--Based-0066FF?style=for-the-badge)](.)
[![Correctness](https://img.shields.io/badge/Principle-Correct%20%3E%20Fast-F55036?style=for-the-badge)](.)
[![Determinism](https://img.shields.io/badge/Deterministic-Enforced-00C853?style=for-the-badge)](.)

</div>

---

## 🧠 Routing Strategy

JARVIS uses a **four-tier, priority-ordered routing system** implemented in `core/runtime.py`. Queries descend through each tier until a handler claims them.

```mermaid
flowchart TD
    A(["User Query"]) --> B["1️⃣ TextCleaner\nNormalize · strip fillers\nCapture location declarations"]
    B --> C{"2️⃣ Priority Intent Router\n30+ handlers · strict ordering"}
    C -->|"Matched (P1–P30)"| D(["Direct Handler Response"])
    C -->|"No match"| E{"3️⃣ Agent Loop\nshould_use_agent()"}
    E -->|"True — tool hints detected"| F["Plan → Validate\n→ Execute → Synthesize"]
    F --> G(["Tool-Backed Response"])
    E -->|"False — conversational"| H["4️⃣ Gemini LLM Stream\ngemini-3.1-flash-lite-preview\nTemperature 0.3"]
    H --> I(["LLM Response"])

    style D fill:#00C853,color:#fff,stroke:none
    style G fill:#0066FF,color:#fff,stroke:none
    style I fill:#374151,color:#fff,stroke:none
```

---

## ⚡ Tier 1 — Priority Intent Router

The router is a **sorted list of `IntentRoute` objects**, each with a matcher function, handler function, and numeric priority. The first handler whose matcher returns `True` wins — all others are skipped.

### Handler Registry (Priority Order)

| Priority | Route Name | Matcher Trigger | Handler |
|---|---|---|---|
| 5 | `correction` | "that's wrong" · "incorrect" · bare "no" | Re-run last fact source |
| 8 | `set_user_name` | "my name is X" · "call me X" | Store name in MemoryStore |
| 9 | `query_user_name` | "what's my name" · "who am I" | Recall stored name |
| 10 | `greeting` | "hi" · "hello" · "good morning/evening" (≤8 words, no tool markers) | Time-aware greeting |
| 11 | `set_session_location` | "i am in X" (no other tool marker, no ?) | Update session location |
| 12 | `wellbeing` | "how are you" · "hru" · "how r u" | Wellbeing response |
| 13 | `capabilities` | "what can you do" · "your capabilities" | Capability summary |
| 14 | `help` | Exact: "help" · "commands" · "list commands" | Quick command reference |
| 15 | `search_policy` | "check internet" · "verify online" (non-query form) | Acknowledge + store preference |
| 16 | `abuse_feedback` | Abuse words without tool markers | Redirect constructively |
| 17 | `ambiguous_season` | Bare "2025 season" with no sport context | Ask for clarification |
| 18 | `speedtest` | "speed test" · "internet speed" · speedtest follow-up | SpeedTest service |
| 19 | `connectivity` | "check internet connectivity" · "am i online" | Deterministic probe |
| 20 | `public_ip` | "my ip" · "public ip" · "external ip" | ipify / ifconfig probe |
| 21 | `network_location` | "where am i" · "network location" (no IP marker) | IP geolocation |
| 22 | `weather` | "weather" · "temperature" · "forecast" anywhere in query | Open-Meteo |
| 23 | `system_status` | "system status" · "pc status" · "how is my device" | psutil snapshot |
| 24 | `temporal` | "current time" · "what time" · "today's date" | datetime.now() |
| 25 | `update_status` | "system update" · "version" · "patch" | Build version info |
| 26 | `document_qa` | Has active docs + QA hint markers (no explicit upload) | Retrieval-backed Q&A |
| 27 | `document` | "analyze document" · "open file picker" · "pdf" / "docx" | Full pipeline |
| 30 | `search_factual` | "search" · "news" · factual who/what/when patterns | Agent loop + Gemini Grounding |

---

## 🤖 Tier 2 — Agent Loop Gating

After the router passes, `AgentLoop.should_use_agent()` decides whether to enter the planner:

```mermaid
flowchart TD
    A(["Normalized Query"]) --> B{Exact fast-path\nchat match?}
    B -->|"hi · hello · thanks\nhow are you..."| Z1(["❌ LLM fallback"])

    B -->|"No"| C{Matches app\nopen/close pattern?}
    C -->|"Yes"| Y1(["✅ Use agent"])

    C -->|"No"| D{Contains\ntool hint?}
    D -->|"weather · news · ip\nspeed · volume · document\napp · brightness · window..."| Y2(["✅ Use agent"])

    D -->|"No"| E{System control\nfollow-up?}
    E -->|"'set it to 35'\nwith remembered topic"| Y3(["✅ Use agent"])

    E -->|"No"| F{Short query\n≤5 words?}
    F -->|"Yes"| Z2(["❌ LLM fallback"])
    F -->|"No"| Z3(["❌ LLM fallback"])

    style Y1 fill:#0066FF,color:#fff,stroke:none
    style Y2 fill:#0066FF,color:#fff,stroke:none
    style Y3 fill:#0066FF,color:#fff,stroke:none
    style Z1 fill:#374151,color:#fff,stroke:none
    style Z2 fill:#374151,color:#fff,stroke:none
    style Z3 fill:#374151,color:#fff,stroke:none
```

---

## 📄 Document Routing — Detailed

Document routing has critical disambiguation logic that prevents the file picker from opening when the user asks for a regular file browser.

```mermaid
flowchart TD
    A(["Query with\ndocument/file keywords"]) --> B{FILE_MANAGER_RE?\n"file explorer"\n"file manager"\n"windows explorer"}
    B -->|"Yes"| C(["→ app_control\nOpen File Explorer"])

    B -->|"No"| D{DOCUMENT_PICKER_RE?\n"open file picker"\n"open document selector"\n"select document"\n"choose pdf"...}
    D -->|"Yes"| E(["→ document branch\nOpen file picker"])

    D -->|"No"| F{Has active docs?\n_active_documents non-empty}
    F -->|"No"| G{DOCUMENT_RE?\n"analyze · summarize · read\npdf · docx · document"}
    G -->|"Yes"| E
    G -->|"No"| H(["→ LLM / agent fallback"])

    F -->|"Yes"| I{Explicit multi-file\ncompare request?\n"compare the 2 documents"\n"compare these two files"}
    I -->|"Yes"| E

    I -->|"No"| J{DOCUMENT_QA_HINT_RE?\n"pricing · risk · feature\nplan · entities · cost\nfind all · in this document"}
    J -->|"Yes"| K(["→ document_qa\nRetrieval-backed Q&A"])
    J -->|"No"| L{Last fact source\nis document?\n+ question word}
    L -->|"Yes"| K
    L -->|"No"| G

    style C fill:#0078D6,color:#fff,stroke:none
    style E fill:#7C3AED,color:#fff,stroke:none
    style K fill:#00C853,color:#fff,stroke:none
```

---

## 🌐 Factual and Search Routing

```mermaid
flowchart TD
    A(["Factual / Search Query"]) --> B{Matches any\ndeterministic service?\nweather · IP · speedtest\nconnectivity · status · temporal}
    B -->|"Yes"| C(["→ Deterministic handler\n(not search)"])

    B -->|"No"| D{Document intent?}
    D -->|"Yes"| E(["→ Document branch"])

    D -->|"No"| F{_is_search_request()?\nexplicit 'search' keyword\n'latest news' · 'who won'+'factual'}
    F -->|"Yes"| G["_build_effective_search_query()\n→ IPL year normalization\n→ follow-up context injection"]

    F -->|"No"| H{_is_factual_query()?\noffice holder · IPL season\nholiday · 'is X still the PM'}
    H -->|"Yes"| G

    G --> I["agent_loop.run(query)\nPlanner → Gemini Grounding → Synthesizer"]
    I --> J(["Web-evidence response"])
    H -->|"No"| K(["→ LLM fallback"])
```

---

## 🚫 Anti-Collision Rules

These rules prevent routing ambiguity across similar-sounding intents:

| Collision Risk | Resolution |
|---|---|
| `check internet connectivity` → search policy | `SEARCH_POLICY_RE` checks for `CONNECTIVITY_RE` and excludes it explicitly |
| `open file explorer` → document picker | `FILE_MANAGER_RE` checked before `DOCUMENT_PICKER_RE`; routes to `app_control` |
| `i am in pune, weather?` → location only | `?` in query disables `set_session_location` handler; routes to `weather` |
| `open document selector` → app control | `DOCUMENT_PICKER_RE` is checked explicitly before app control routing |
| `max volume` → unknown action | `SystemControlValidator` maps `max volume` → `set_volume level=100` |
| `2025 season` → wrong sport | `AMBIGUOUS_SEASON_RE` catches bare season queries; asks for sport context |
| `close it` → no target | `AppControlService` falls back to `memory.get('last_opened_app')` |
| `weather again` → weather without city | `TextCleaner.had_again` injects `memory.get('last_city')` before routing |

---

## 🎤 Voice Echo Guard

The `JarvisBridge` implements an echo guard to prevent the microphone from picking up JARVIS's own speech:

```mermaid
flowchart LR
    A(["STT Transcript"]) --> B{Mode is\n'speaking' or\n'processing'?}
    B -->|"Yes"| Z(["❌ Drop"])

    B -->|"No"| C{Within voice\ngate_until\ncooldown?}
    C -->|"Yes"| Z2(["❌ Drop"])

    C -->|"No"| D{Echo guard\nactive? ≤3 words?}
    D -->|"Yes"| Z3(["❌ Drop"])

    D -->|"No"| E{Looks like\nassistant echo?\ntokenized similarity ≥0.78}
    E -->|"Yes"| Z4(["❌ Drop"])

    E -->|"No"| F{Duplicate within\n3.4 seconds?}
    F -->|"Yes"| Z5(["❌ Drop"])

    F -->|"No"| G(["✅ Accept\n→ submit_voice()"])
```

---

## 📊 Routing Performance Profile

| Tier | Latency | When Used |
|---|---|---|
| Local handler (P1–P30) | ~0ms | Greetings, wellbeing, memory, deterministic services |
| Deterministic service (P18–P27) | 50–800ms | Weather, IP, speedtest, connectivity, document QA |
| Agent loop + tools | 1–5s | Factual queries, multi-tool requests, app control |
| LLM stream fallback | 0.5–3s TTFT | General knowledge, conceptual questions |
| Document pipeline (first run) | 5–45s | PDF/DOCX/image analysis (cached on second run) |

---

<div align="center">

> **Design Goal: Correct routing > fast routing.**  
> A slow but correct answer builds trust. A fast but wrong answer destroys it.

[![Footer](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=100&section=footer)](.)

</div>