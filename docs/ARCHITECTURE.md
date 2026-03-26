# Architecture Overview

Jarvis is a hybrid assistant that combines:
- deterministic local services
- realtime web search
- model-based conversational fallback

## High-level flow

1. Input enters `core/runtime.py`.
2. Query is normalized (`utils/text_cleaner.py`).
3. Priority intent routing runs (`services/intent_router.py`).
4. If routed locally, a service handles the request:
   - network and system status
   - weather and location
   - speed test and IP
   - internet search synthesis
5. If unresolved, Groq streaming handles conversational fallback.
6. Personality sanitizer formats the final reply (`core/personality.py`).

## Key modules

- `core/runtime.py`: central orchestrator and intent source-of-truth.
- `services/search_service.py`: web retrieval + consensus synthesis.
- `services/network_service.py`: IP, speed test, system/temporal snapshots.
- `services/weather_service.py`: local/city weather via Open-Meteo.
- `memory/store.py`: persistent user/profile runtime facts.

## Reliability model

Jarvis intentionally prefers deterministic local execution for actionable tasks.

- Factual/current-affairs -> web search synthesis.
- Conceptual explanations -> concise model response by default.
- Operational commands (speed test, IP, status) -> local services.
- Correction turns -> rerun best available factual source.

## State and memory

Persistent memory is JSON-backed (`data/user_memory.json`) and stores:
- user name/profile
- last city and country hints
- last search query context
- speed test snapshots and error state
