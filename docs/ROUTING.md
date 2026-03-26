# Intelligent Routing

This document explains how Jarvis decides where an answer should come from.

## Source priority

1. Local deterministic intents
2. Realtime web search for factual/time-sensitive questions
3. LLM fallback for conversational or conceptual tasks

## Deterministic intents

Handled directly by local services:
- speed test and follow-ups
- IP and location
- weather and news wrappers
- system status and local time/date
- user-name memory operations

## Factual routing

Jarvis routes to web search when prompts are likely factual, including:
- current office-holder questions (PM/President)
- sports winners/seasons
- holiday confirmation
- replacement/campaign verification prompts

### Contextual query shaping

Before hitting search, query text is normalized:
- typo rescue for common tokens (for example IPL misspellings)
- follow-up anchoring ("that season", "that winner")
- noisy prefix cleanup ("I said check on internet that ...")

## Safety against intent hijacking

To keep UX stable:
- search-policy feedback cannot override actionable commands.
- abuse language does not block executable intents.
- speed-test follow-ups require speed-specific markers.

## Ambiguity handling

Short ambiguous prompts like `2025 season` trigger clarification instead of guesses.

## Concise conceptual mode

For conceptual prompts, Jarvis keeps responses brief by default and offers deeper follow-up when needed.
