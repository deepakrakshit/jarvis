<div align="center">

[![Header](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=140&section=header&text=Changelog&fontSize=44&fontColor=ffffff&animation=twinkling&fontAlignY=50)](.)

[![Keep a Changelog](https://img.shields.io/badge/Keep%20a-Changelog-F7C948?style=for-the-badge)](https://keepachangelog.com)
[![Semantic Versioning](https://img.shields.io/badge/Semantic-Versioning-0066FF?style=for-the-badge)](https://semver.org)

</div>

All notable changes to JARVIS are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned
- Plugin tool packs (extensible tool registry)
- Deeper multi-agent planning strategies
- Expanded multilingual voice + TTS safety controls
- Document pipeline benchmark suite
- Optional cloud memory sync
- Linux / macOS platform support
- Wake-word activation

---

## [1.7.0] — 2026-04-03 — Autonomous Vision & Reliability Upgrade

### Added
- **Multi-Turn Re-Act Planner**: `AgentLoop.run()` now feeds tool execution history back into Planner turns, enabling self-correction during multi-step requests.
- **Context-Aware Agent Loop**: Planner and Synthesizer now consume recent conversation turns and user profile context.
- **LLM-Powered Intent Classification**: Agent loop now performs fast Gemini intent checks for non-obvious tool requests.
- **Memory Save Tool**: Added explicit `memory_save` tool contract for controlled user fact persistence.
- **Production Screen Processor**: Added `services/actions/screen_processor.py` with local-first screen/camera analysis, frame memory, lightweight object tracking, and structured result payloads.
- **Deterministic Visual Routing**: Added direct routing for `view_now` and `view_latest` style screen/camera requests.
- **Computer Automation Coverage**: Added deterministic browser/UI automation routing and stress tests for `computer_control` autonomous flows.
- **Expanded Stress Coverage**: Added tests for screen pipeline, screen routing, computer-control routing, tool accuracy confidence, and provider config.

### Changed
- **Planner Guardrails**: `_prepare_plan_for_execution()` now normalizes incomplete planner steps for `computer_control` and `document` before validation.
- **Weather Validation Robustness**: location matching now accepts city-only tool outputs when requests include city/state/country labels.
- **Document Tool Hardening**: document tool now validates `file_path` before analysis and supports active-document sentinel routing.
- **Search Resilience**: search flow now supports Gemini-based query reformulation fallback when first-pass grounded results are empty.
- **Synthesizer Resilience**: improved fallback rendering for search, computer actions, and screen processing outputs.
- **Release Docs + Config Sync**: refreshed README/docs provider references and aligned `.env.example` key coverage/order with `.env`.

### Fixed
- **Plan Rejection Noise**: fixed repeated "missing required field 'action'" warnings for planner-generated `computer_control` steps.
- **Weather False Mismatch Warnings**: fixed false `location_mismatch` warnings for labels like `Nagpur, Maharashtra, India` vs `Nagpur`.
- **Document Validation Warning Spam**: reduced warning noise from invalid planner-provided document paths.
- **Brightness EDID Warning Noise**: suppressed non-actionable `screen_brightness_control.windows` EDID warnings during runtime.

---

## [1.6.0] — 2026-04-01 — Control + Conversation Quality Upgrade

### Added
- **App Control**: deterministic open/close with Start Menu indexing (`Get-StartApps`), rapidfuzz WRatio resolution (>85 resolved, 70–85 ambiguous), OS process verification before reporting success, `close it` pronoun follow-up via persistent memory, canonical alias map (browser → chrome, coding → code), non-fuzzy fallback
- **System Control**: full stack for volume (pycaw + keyboard fallback), brightness (screen-brightness-control), window management (pygetwindow), desktop control, and screen lock — with `SystemControlValidator`, `_BLOCKED_ACTIONS` safety set, rate limiting (30/min), and action audit log
- **Natural language system control**: `max volume`, `min brightness`, `set brightness to 50`, `lower the brightness`, `it's still 50, i want 35 for brightness` all canonicalize correctly
- **Contextual humor system**: `HumorEngine` with 7 weather condition buckets, anti-repetition deck with sliding window, context-aware category routing (greeting, weather, ip, connectivity, etc.)
- **Query-specific temporal responses**: `what time`, `what date`, `what day`, `what month`, `what year` each return a focused response instead of a combined snapshot

### Changed
- Expanded stress test coverage: system control normalization, app control resolver/executor, volume keyboard fallback, synthesizer fallback readability
- Synced all docs (`ROUTING.md`, `COMMANDS.md`, `TROUBLESHOOTING.md`, `TESTING.md`) with new control capabilities

---

## [1.5.0] — 2026-03-31 — Document Intelligence Upgrade (Q&A + Compare)

### Added
- **Document Q&A engine**: retrieval-first answering over active analyzed documents using `SemanticRetriever` with lexical + semantic + number + synonym scoring
- **Multi-document comparison**: cross-document evidence synthesis for pricing, risk, and feature decisions — fast model first, deep model fallback when schema is invalid
- **Entity extraction**: deterministic extraction of prices, dates, companies, plans, features, and names from fused document content
- **Structured document insights**: key points, risks, metrics, and entities in every analysis result
- **Active document index**: up to 8 concurrent documents held in memory for follow-up Q&A without re-processing

### Changed
- OCR + vision + fusion pipeline reliability improved with better fallback behavior
- `DocumentService` now exposes `has_active_documents()` and `active_document_names()` for runtime routing decisions

---

## [1.4.0] — 2026-03-31 — Document Intelligence System

### Added
- **Hybrid document pipeline**: PDF (PyMuPDF + pdfplumber tables), DOCX (python-docx + embedded images), image (direct vision) parsing
- **PaddleOCR integration**: scanned PDF and low-text page extraction with confidence thresholding and `max_image_side` resize
- **Groq Vision integration**: Llama 4 Scout with fallback model chain, rate-limit fast-fail, and second-pass retry
- **FusionProcessor**: unified text + OCR + vision payload merging into structured `DocumentIntelligence`
- **Four reasoning modes**: ultra-fast deterministic / text-primary LLM / fast LLM (8b) / deep LLM (70b) — selected by content length, query depth, and vision signal
- **Two-tier document cache**: SQLite WAL persistent cache + In-Memory LRU hot cache with per-key request locks
- **File validation**: type, size (≤100MB), and path validation before any parsing begins
- **`SemanticChunker`**: token-aware section → paragraph → sentence → hard-split chunking for reasoning payloads

### Changed
- Search service refactored into unified raw-output design for agent synthesis
- Mode-wave visualization panel added to frontend
- Voice TTS skip control (SKIP button + Three.js orb) added to desktop UI
- Network news service merged into unified `SearchService`
- Application entrypoints hardened with venv re-exec logic

---

## [1.3.0] — 2026-03-29 — UI and Real-Time Telemetry

### Added
- **Live system telemetry streaming**: CPU, RAM, Disk, Battery, Network up/down Mbps, latency (socket probe), and uptime pushed to frontend every 0.9s via `JarvisBridge._metrics_worker`
- **Three.js mode-wave renderer**: animated bar visualization that reacts to LISTENING / PROCESSING / SPEAKING mode and mic volume
- **Full-message transcript buffering**: last 5 conversation turns displayed in the HUD
- **SKIP button**: safely interrupts active TTS mid-stream via `turn_id` invalidation

### Changed
- Frontend network panel replaced with mode-wave panel
- Transcript display improved with readability and word-wrap fixes

---

## [1.2.0] — 2026-03-27 — Autonomous Agent Architecture

### Added
- **Agent loop**: full Planner → Validator → Executor → Synthesizer cycle in `agent/`
- **Groq-backed planner**: JSON-mode plan generation with tool schema awareness, deduplication, and `response_format: json_object`
- **Plan validator**: schema checking, tool existence verification, max 8 steps, max 3 `system_control` actions per request
- **Async/parallel executor**: per-tool timeout, one-shot retry, parallel execution for `parallel_safe=True` tools
- **Synthesizer**: relevance-filtered tool output → final response with identity guardrails and tone policy
- **Tool registry**: all tool definitions in `build_default_tool_registry()` factory with `ToolDefinition` contracts
- Agent loop integrated with priority intent router — agent only runs when local router finds no match
- `should_use_agent()` fast-path gating with exact-match bypass set and tool-hint markers

### Changed
- Search service refactored to return raw structured data — synthesis delegated to `Synthesizer`

---

## [1.1.0] — 2026-03-26 — Real-Time AI Assistant Upgrade

### Added
- **Internet search**: live web + news evidence via Serper.dev with query normalization, variant generation, and trusted-source flagging
- **Weather service**: current conditions via Open-Meteo with IP-based location fallback and geocoding via open-meteo geocoding API
- **Public IP**: ipify + ifconfig.me with chain fallback
- **IP geolocation**: ip-api.com + ipinfo.io resolution chain
- **Internet connectivity diagnostics**: latency-measured probe with public IP verification
- **Speedtest**: synchronous execution with country-benchmarked assessment and background async mode
- **System status snapshot**: CPU, RAM, uptime via psutil
- **Persistent memory**: thread-safe JSON-backed `MemoryStore` — user name, session location, last search query
- **Voice pipeline improvements**: improved mic handling, API bridge synchronization, UI feedback

### Changed
- Jarvis transformed from static CLI assistant to real-time tool-backed AI system
- Modular services architecture established (`services/weather_service.py`, `services/network_service.py`, `services/search_service.py`)

---

## [1.0.0] — 2026-03-26 — Initial Release

### Added
- Base CLI assistant with Groq streaming (`llama-3.1-8b-instant`)
- Core runtime orchestrator (`core/runtime.py`) with priority intent router skeleton
- `AppConfig` dataclass with full `.env` loading via `core/env.py`
- `PersonalityEngine` with forbidden-pattern sanitization and tone adaptation
- `TextCleaner` for query normalization and filler-word stripping
- `RealtimePiperTTS` streaming engine with Piper subprocess + PyAudio playback
- pywebview desktop GUI with Three.js adaptive plasma sphere
- Time-of-day greeting system
- Session-based context (greetings, wellbeing, identity queries handled locally)

---

<div align="center">

[![Footer](https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=2,3,30&height=100&section=footer)](.)

</div>