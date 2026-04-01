<div align="center">

[![Header](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=160&section=header&text=Architecture&fontSize=44&fontColor=ffffff&animation=twinkling&fontAlignY=50)](.)

[![System](https://img.shields.io/badge/System-Agent%20Architecture-7C3AED?style=for-the-badge)](.)
[![Flow](https://img.shields.io/badge/Flow-Deterministic%20%2B%20AI-0066FF?style=for-the-badge)](.)
[![Validation](https://img.shields.io/badge/Validation-Enforced%20at%20Every%20Stage-00C853?style=for-the-badge)](.)

</div>

---

## 🔭 System Overview

JARVIS is a **modular AI agent system** that combines three execution modes under a unified orchestrator:

1. **Local fast-path** — deterministic handlers for identity, greetings, and conversational turns (~0ms)
2. **Agent loop** — Planner → Validator → Executor → Synthesizer for tool-backed queries
3. **LLM stream fallback** — direct Groq streaming for general knowledge queries

The architecture is explicitly designed so that real-time data **always comes from tools**, never from LLM training data.

---

## 🔄 High-Level Request Flow

```mermaid
flowchart TD
    A(["🎙️ User Input"]) --> B["🧹 TextCleaner\n+ Location Capture"]
    B --> C{"⚡ Priority Intent Router\n30+ handlers · priorities 1–30"}

    C -->|"P1–P17\nCorrection · Name\nGreeting · Wellbeing\nLocation · Help\nSearch Policy · Abuse"| D(["✅ Local Handler\n~0ms · No API call"])

    C -->|"P18–P27\nSpeedtest · Connectivity\nPublic IP · Network Location\nWeather · System Status\nTemporal · Update\nDocument QA · Document"| E["🔧 Deterministic\nService Layer"]

    C -->|"P30\nSearch / Factual"| F["🌐 Agent Loop\n+ Web Evidence"]

    C -->|"No match"| G["💬 Groq Stream\nllama-3.1-8b-instant\nTemperature 0.3"]

    E --> H["🎭 Personality Engine\n+ Identity Guardrails"]
    F --> H
    D --> H
    G --> H
    H --> I(["🔊 Final Response\n+ Piper TTS"])

    style A fill:#0066ff,color:#fff,stroke:#00e1ff,stroke-width:2px
    style I fill:#0066ff,color:#fff,stroke:#00e1ff,stroke-width:2px
    style D fill:#00C853,color:#fff,stroke:none
    style H fill:#7C3AED,color:#fff,stroke:none
    style G fill:#374151,color:#fff,stroke:none
```

---

## 🧠 Agent Loop — Deep Dive

The agent loop is the intelligence core for all tool-backed requests.

```mermaid
sequenceDiagram
    participant R as Runtime
    participant AL as AgentLoop
    participant PL as Planner
    participant VA as Validator
    participant EX as Executor
    participant T as Tools
    participant SY as Synthesizer

    R->>AL: should_use_agent(query)
    AL-->>R: true

    R->>AL: run(query)
    AL->>PL: plan(query)
    Note over PL: Groq JSON mode<br/>llama-3.1-8b<br/>Temperature 0

    PL-->>AL: PlanDraft {steps, reasoning}
    AL->>AL: _prepare_plan_for_execution()<br/>(inject session location for weather)

    AL->>VA: validate(plan_steps)
    Note over VA: Schema check<br/>Tool existence<br/>Max 8 steps<br/>Max 3 system_control
    VA-->>AL: ValidationResult {approved}

    AL->>EX: execute(plan_steps)
    Note over EX: Parallel if all steps<br/>parallel_safe=True<br/>Retry once on failure<br/>Timeout per tool

    EX->>T: call tool functions
    T-->>EX: raw structured outputs
    EX->>EX: ToolOutputValidator<br/>(location match · schema check)
    EX-->>AL: tool_outputs dict

    AL->>SY: synthesize(query, tool_outputs)
    Note over SY: Relevance filtering<br/>Identity guardrails<br/>Temperature 0.2
    SY-->>AL: final response text

    AL-->>R: AgentLoopResult {handled, response}
```

### Fast-Path Bypass

Before invoking the planner, `AgentLoop.should_use_agent()` gates the query:

```mermaid
flowchart LR
    A(["Query"]) --> B{Exact match\nfast-path set?}
    B -->|hi, hello, thanks...| Z(["❌ Skip agent"])
    B -->|No| C{Matches\ntool hint?}
    C -->|weather, news, ip\ndocument, volume...| Y(["✅ Use agent"])
    C -->|No| D{Short\n≤5 words?}
    D -->|Yes| Z2(["❌ Skip agent"])
    D -->|No| Z3(["❌ Skip agent\n→ LLM fallback"])
```

---

## 📄 Document Intelligence Pipeline

The document pipeline is a self-contained multimodal processing system with multiple quality tiers.

```mermaid
flowchart TD
    A(["📄 Document Request"]) --> B["📁 File Selector\nTkinter GUI / CLI fallback\nSystem-controlled only"]
    B --> C["🛡️ validate_file_path()\nExistence · Type · Size ≤100MB"]
    C --> D{"Extension"}

    D -->|".pdf"| E["PyMuPDF\n+ pdfplumber tables"]
    D -->|".docx / .doc"| F["python-docx\n+ embedded images"]
    D -->|"image"| G["Direct Vision\n→ skip parse stage"]

    E & F --> H{"Text\nLength"}

    H -->|"> TEXT_RICH_MIN_CHARS\n(default 1800)"| I["📝 Text Primary\nllama-3.1-8b\nParallel with Vision"]
    H -->|"Scanned / Images"| J["👁️ Vision API\nLlama 4 Scout"]
    J -->|"Vision fails"| K["🔠 PaddleOCR\nFallback"]

    I & J & K & G --> L["🔀 FusionProcessor\nMerge text + OCR + vision"]

    L --> M{"Ultra-Fast\nEligible?"}
    M -->|"Yes — no LLM needed"| N["⚡ Deterministic\nSummary + Key Points"]
    M -->|"No"| O{"Reasoning\nTier"}
    O -->|"Default fast"| P["llama-3.1-8b\nmax_tokens 1600"]
    O -->|"Deep / asks_depth"| Q["llama-3.3-70b\nmax_tokens 2500"]

    N & P & Q --> R["🗂️ Active Document Index\n+ SQLite Cache\n+ In-Memory LRU"]
    R --> S(["📊 DocumentIntelligence\nsummary · insights · key_points\ntables · metrics · risks · entities\nretrieval_chunks"])
```

### Cache Architecture

```mermaid
flowchart LR
    A(["Analyze Request"]) --> B{L1 Memory\nCache Hit?}
    B -->|Hit| C(["Return Cached"])
    B -->|Miss| D{Request Lock\nfor cache_key}
    D --> E{L2 SQLite\nCache Hit?}
    E -->|Hit| F["Populate L1\nReturn Cached"]
    E -->|Miss| G["Run Pipeline\n(parse→OCR→vision→reason)"]
    G --> H{"Result\nCacheable?"}
    H -->|"success=True\nno 429 errors"| I["Write SQLite\n+ Write L1"]
    H -->|"Degraded result"| J["Return Fresh\n(no cache write)"]
    I --> C
    F --> C
    J --> C
```

---

## ⚙️ App Control Flow

```mermaid
flowchart TD
    A(["open chrome"]) --> B["AppControlService.control()"]
    B --> C["AppResolver.resolve('chrome')"]
    C --> D["Check alias map\n'chrome' → 'chrome'"]
    D --> E["Get-StartApps\n(PowerShell · 300s TTL)"]
    E --> F["rapidfuzz WRatio\nscoring + ranking"]
    F --> G{Confidence}
    G -->|"> 85"| H["ResolvedApp\n{name, app_id, process_hints}"]
    G -->|"70–85"| I(["ambiguous\nask user to specify"])
    G -->|"< 70"| J(["not_found"])
    H --> K["AppExecutor._open_app()"]
    K --> L["Snapshot baseline PIDs\nfor process_hints"]
    L --> M["Try launch commands:\n1. shell:AppsFolder\\{app_id}\n2. Start-Process {name}\n3. Start-Process {hint[0]}"]
    M --> N["Poll for new PID\nup to 15s"]
    N -->|"New PID found"| O(["status=success\nverified=true"])
    N -->|"Timeout"| P(["status=error\nreason=execution_failed"])
```

---

## 🎤 Voice Pipeline

```mermaid
flowchart LR
    A(["Text Response"]) --> B["_first_speech_chunk()\n14–26 chars"]
    B --> C["enqueue_text()\n+ turn_id check"]
    C --> D["TTS Worker Thread\nQueue consumer"]
    D --> E["stream.feed(text)"]
    E --> F["AdaptivePiperEngine\nsubprocess piper.exe"]
    F --> G["WAV → PyAudio\nrate-converted if needed"]
    G --> H(["🔊 Speaker Output"])

    A --> I["_next_speech_chunk()\n28–36 chars on boundaries"]
    I --> C

    subgraph Interrupt
        J(["Skip Button"]) --> K["tts.interrupt()\nincrement turn_id"]
        K --> L["stream.stop()"]
        L --> M["Clear queue\nEmit listening mode"]
    end
```

---

## 🖥️ Desktop UI Architecture

```mermaid
flowchart TD
    A(["Frontend\nThree.js + HTML"]) <-->|"pywebview JS API"| B["JarvisApi\n{ui_ready · submit_voice\n skip_current_reply}"]
    B --> C["JarvisBridge\n{echo guard · mode gate\n assistant text tracking}"]
    C --> D["JarvisRuntime\n(core orchestrator)"]
    D --> E["Voice Worker Thread\nqueue consumer"]
    D --> F["Metrics Worker Thread\n0.9s poll cycle"]
    F --> G["psutil + socket\n{CPU · RAM · Disk · Battery\n Network · Latency · Uptime}"]
    G -->|"setSystemMetrics(payload)"| A
    D -->|"setMode(mode)"| A
    D -->|"onAssistantDelta(delta)"| A
    D -->|"setApiActivity(bool)"| A
```

---

## ⚡ Performance Controls

All document throughput is tunable via `.env` — no code changes required.

| Variable | Default | Effect |
|---|---|---|
| `DOCUMENT_OCR_MAX_WORKERS` | `6` | Parallel PaddleOCR threads |
| `DOCUMENT_VISION_MAX_WORKERS` | `4` | Parallel Groq Vision requests |
| `DOCUMENT_PDF_RENDER_DPI` | `140` | Page image resolution for vision/OCR |
| `DOCUMENT_PDF_MAX_VISION_IMAGES` | `10` | Cap on pages sent to vision model |
| `DOCUMENT_PDF_MAX_OCR_IMAGES` | `16` | Cap on pages sent to OCR |
| `DOCUMENT_PDF_TABLE_MAX_PAGES` | `8` | Pages scanned for table extraction |
| `DOCUMENT_REASONING_DEFAULT_FAST` | `true` | Use 8b model unless depth requested |
| `DOCUMENT_ULTRA_FAST_ENABLED` | `true` | Skip LLM for simple summaries |
| `DOCUMENT_ULTRA_FAST_MIN_CHARS` | `700` | Minimum chars to qualify for ultra-fast |
| `DOCUMENT_SKIP_VISION_FOR_TEXT_RICH` | `true` | Skip vision when text extraction is sufficient |
| `DOCUMENT_TEXT_RICH_MIN_CHARS` | `1800` | Text length threshold for "text-rich" classification |
| `DOCUMENT_REASONING_TEXT_CHAR_BUDGET` | `22000` | Max chars sent to reasoning from text |
| `DOCUMENT_REASONING_OCR_CHAR_BUDGET` | `9000` | Max chars sent to reasoning from OCR |
| `DOCUMENT_REASONING_VISION_VISIBLE_CHAR_BUDGET` | `7000` | Max visible text from vision |
| `DOCUMENT_CACHE_TTL_SECONDS` | `86400` | SQLite cache entry lifetime |
| `DOCUMENT_CACHE_MAX_ENTRIES` | `256` | Max SQLite cache entries before pruning |

---

## 🛡️ Reliability Model

| Guarantee | Enforcement |
|---|---|
| No hallucinated real-time data | Tool refusal for disallowed-tool real-time requests |
| Retry on invalid tool output | `ToolOutputValidator` + `ToolExecutor` retry loop |
| Correct tool selection | `PlanValidator` schema enforcement |
| Deterministic system commands | `SystemControlValidator` with `_BLOCKED_ACTIONS` set |
| Verified source for factual queries | Synthesizer requires successful Serper results |
| Identity on final output | `_enforce_assistant_identity()` on every LLM response |
| Safe document path handling | `validate_file_path()` before any parsing |
| Bounded active document context | LRU eviction at `_active_documents_max_entries = 8` |
| OS-verified app open/close | `AppExecutor` polls for process existence before reporting success |
| No ambiguous connectivity routing | `CONNECTIVITY_RE` never matches `SEARCH_POLICY_RE` |
| Max/min volume/brightness safety | `SystemControlValidator` maps to explicit `set_*` actions |
| Synthesizer never claims unverified success | App/system control checks `verified=True` before confirming |

---

## 💾 State and Memory

```
data/user_memory.json
├── user_name          — stored name (e.g., "Deepak")
├── last_city          — last used weather city
├── last_search_query  — last search for follow-up resolution
├── last_speedtest     — {download_mbps, upload_mbps, ping_ms, timestamp, ...}
├── last_speedtest_error — last error string for correction handler
├── last_speedtest_requested_at — timestamp for freshness check
├── last_opened_app    — for "close it" pronoun resolution
├── user_country       — resolved from IP for speedtest benchmarking
└── prefer_web_for_facts — set when user gives search-policy feedback
```

---

<div align="center">

[![Footer](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=100&section=footer)](.)

</div>