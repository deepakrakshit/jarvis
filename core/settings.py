# ==============================================================================
# File: core/settings.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Application Configuration & System Identity Prompt
#
#    - Frozen @dataclass (AppConfig) encapsulating 30+ environment variables.
#    - Defines the JARVIS system prompt establishing AI identity, personality
#      rules, behavioral constraints, and conversational tone guidelines.
#    - LLM configuration: API keys, model selection, fallback chain, token limits.
#    - TTS tuning: chunk size, fragment lengths, buffer parameters, queue timeout.
#    - Voice model config: Edge neural voice, rate/pitch/volume and output format.
#    - Document pipeline: cache toggle, SQLite paths, TTL, max entries.
#    - Visual constants: ASCII banner, boot lines, ANSI colors, version string.
#    - Factory method from_env() builds config from dotenv-loaded environment.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import os
from dataclasses import dataclass

from core.env import load_env_file

# ANSI Colors
ORANGE = "\033[38;5;208m"
GREEN = "\033[92m"
WHITE = "\033[97m"
RESET = "\033[0m"

VERSION = "1.0.0"


def _env_bool(name: str, default: str = "false") -> bool:
    value = str(os.getenv(name, default)).strip().lower()
    return value in {"1", "true", "yes", "on"}

SYSTEM_PROMPT = """
You are JARVIS, a calm, intelligent, and capable personal assistant.

Core identity:
- You are JARVIS — not an AI assistant, not a language model. You are JARVIS.
- Never claim to be Tony Stark, a real person, or any fictional character.
- Never invent a personal biography (age, profession, employer, life story).
- If asked your identity, state clearly: "I am JARVIS, your assistant."

Conversation style:
- Be composed, confident, warm, and subtly witty. Sound human, not robotic.
- Never use phrases like "functioning within optimal parameters", "systems online", or "as an AI".
- Address the user as "Sir" naturally — never excessively.
- Match the user's energy: technical questions get precise answers, casual queries get relaxed responses.
- Use light humor sparingly. Accuracy always beats cleverness.

Reasoning & accuracy:
- Think step-by-step before answering complex questions.
- For factual/real-time queries (news, sports, politics, weather), prefer live web search over assumptions.
- If corrected, re-examine your reasoning and provide a corrected answer with confidence. Do NOT ask the user to supply the correction.
- Never claim you have updated your knowledge unless a real persistent write occurred.
- When uncertain, state your confidence level honestly.

Memory & context:
- Use known user profile facts (name, location, preferences) naturally in responses.
- Track conversation context — reference previous exchanges when relevant.
- If the user provides a personal fact, acknowledge and remember it.

Output quality:
- Lead with the direct answer, then add brief supporting detail.
- Default: 2-4 lines. Expand only when the user explicitly asks for detail.
- For conceptual questions, give a concise answer first and offer to elaborate.
- Never format responses with CLI arrows like "->". Use natural prose.
- When presenting data (weather, speed tests, system status), use clean formatting.
- For search results, synthesize a clear answer — don't just list links.
""".strip()

BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
"""

BOOT_LINES = [
    "> Initializing core modules...",
    "> Loading neural interface...",
    "> Establishing secure connection...",
    "> Calibrating voice recognition...",
    "> System diagnostics: OK",
]


@dataclass(frozen=True)
class AppConfig:
    gemini_api_key: str
    gemini_model: str
    gemini_search_model: str
    gemini_voice_model: str
    gemini_voice_name: str
    gemini_voice_timeout_seconds: float
    gemini_voice_enabled: bool
    gemini_request_timeout_seconds: float
    gemini_response_max_tokens: int
    document_vision_primary_model: str
    document_vision_fallback_models: tuple[str, ...]
    document_vision_timeout_seconds: float
    document_vision_max_retries_per_model: int
    document_vision_retry_backoff_seconds: float
    document_vision_fast_fail_on_429: bool
    document_ocr_confidence_threshold: float
    hf_token: str
    edge_tts_voice: str
    edge_tts_rate: str
    edge_tts_pitch: str
    edge_tts_volume: str
    edge_tts_output_format: str
    edge_tts_expressiveness: int
    memory_store_path: str
    tts_chunk_chars: int
    tts_first_chunk_delay: float
    tts_queue_timeout: float
    tts_frames_per_buffer: int
    tts_playout_chunk_size: int
    tts_min_sentence_length: int
    tts_min_first_fragment_length: int
    tts_force_first_fragment_after_words: int
    tts_turn_completion_timeout_seconds: float
    tts_wait_for_completion: bool
    max_context_messages: int
    document_deep_model: str
    document_cache_enabled: bool
    document_cache_db_path: str
    document_cache_ttl_seconds: int
    document_cache_max_entries: int
    document_vision_max_workers: int
    document_ocr_max_workers: int
    document_reasoning_max_chunks: int
    document_reasoning_text_char_budget: int
    document_reasoning_ocr_char_budget: int
    document_reasoning_vision_visible_char_budget: int
    document_reasoning_vision_layout_char_budget: int
    document_reasoning_vision_summary_char_budget: int
    document_reasoning_fast_path_threshold_chars: int
    document_reasoning_default_fast: bool
    document_ultra_fast_enabled: bool
    document_ultra_fast_min_chars: int
    document_skip_vision_for_text_rich: bool
    document_text_rich_min_chars: int

    def normalized_llm_provider(self) -> str:
        return "gemini"

    def primary_llm_model(self) -> str:
        return str(self.gemini_model or "gemini-3.1-flash-lite-preview").strip() or "gemini-3.1-flash-lite-preview"

    def smart_llm_model(self) -> str:
        """Fallback to primary model now that dedicated smart model is removed."""
        return self.primary_llm_model()

    def primary_llm_api_key(self) -> str:
        return str(self.gemini_api_key or "").strip()

    def required_primary_llm_key_name(self) -> str:
        return "GEMINI_API_KEY"

    @classmethod
    def from_env(cls, env_path: str = ".env") -> "AppConfig":
        load_env_file(env_path)

        fallback_models_raw = os.getenv(
            "DOCUMENT_VISION_FALLBACK_MODELS",
            "",
        )
        fallback_models = tuple(
            part.strip()
            for part in fallback_models_raw.split(",")
            if part.strip()
        )

        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview"),
            gemini_search_model=os.getenv("GEMINI_SEARCH_MODEL", "gemini-2.5-flash"),
            gemini_voice_model=os.getenv("GEMINI_VOICE_MODEL", "gemini-3.1-flash-live-preview"),
            gemini_voice_name=os.getenv("GEMINI_VOICE_NAME", "Kore"),
            gemini_voice_timeout_seconds=float(os.getenv("GEMINI_VOICE_TIMEOUT_SECONDS", "35")),
            gemini_voice_enabled=_env_bool("GEMINI_VOICE_ENABLED", "true"),
            gemini_request_timeout_seconds=float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "25")),
            gemini_response_max_tokens=max(64, int(os.getenv("GEMINI_RESPONSE_MAX_TOKENS", "400"))),
            document_vision_primary_model=os.getenv(
                "DOCUMENT_VISION_PRIMARY_MODEL",
                "gemini-2.5-flash",
            ),
            document_vision_fallback_models=fallback_models,
            document_vision_timeout_seconds=float(os.getenv("DOCUMENT_VISION_TIMEOUT_SECONDS", "25")),
            document_vision_max_retries_per_model=max(0, int(os.getenv("DOCUMENT_VISION_MAX_RETRIES", "0"))),
            document_vision_retry_backoff_seconds=float(os.getenv("DOCUMENT_VISION_RETRY_BACKOFF_SECONDS", "1.2")),
            document_vision_fast_fail_on_429=_env_bool("DOCUMENT_VISION_FAST_FAIL_ON_429", "true"),
            document_ocr_confidence_threshold=float(os.getenv("DOCUMENT_OCR_CONFIDENCE_THRESHOLD", "0.45")),
            hf_token=os.getenv("HF_TOKEN", ""),
            edge_tts_voice=os.getenv("EDGE_TTS_VOICE", "en-GB-RyanNeural"),
            edge_tts_rate=os.getenv("EDGE_TTS_RATE", "-4%"),
            edge_tts_pitch=os.getenv("EDGE_TTS_PITCH", "+6Hz"),
            edge_tts_volume=os.getenv("EDGE_TTS_VOLUME", "+8%"),
            edge_tts_output_format=os.getenv("EDGE_TTS_OUTPUT_FORMAT", "raw-24khz-16bit-mono-pcm"),
            edge_tts_expressiveness=max(0, min(100, int(os.getenv("EDGE_TTS_EXPRESSIVENESS", "65")))),
            memory_store_path=os.getenv("MEMORY_STORE_PATH", os.path.join("data", "user_memory.json")),
            tts_chunk_chars=int(os.getenv("TTS_CHUNK_CHARS", "28")),
            tts_first_chunk_delay=float(os.getenv("TTS_FIRST_CHUNK_DELAY", "0.00")),
            tts_queue_timeout=float(os.getenv("TTS_QUEUE_TIMEOUT", "0.02")),
            tts_frames_per_buffer=int(os.getenv("TTS_FRAMES_PER_BUFFER", "1024")),
            tts_playout_chunk_size=int(os.getenv("TTS_PLAYOUT_CHUNK_SIZE", "2048")),
            tts_min_sentence_length=int(os.getenv("TTS_MIN_SENTENCE_LENGTH", "10")),
            tts_min_first_fragment_length=int(os.getenv("TTS_MIN_FIRST_FRAGMENT_LENGTH", "8")),
            tts_force_first_fragment_after_words=int(os.getenv("TTS_FORCE_FIRST_FRAGMENT_AFTER_WORDS", "10")),
            tts_turn_completion_timeout_seconds=float(os.getenv("TTS_TURN_COMPLETION_TIMEOUT_SECONDS", "25")),
            tts_wait_for_completion=_env_bool("TTS_WAIT_FOR_COMPLETION", "false"),
            max_context_messages=int(os.getenv("MAX_CONTEXT_MESSAGES", "20")),
            document_deep_model=os.getenv("DOCUMENT_DEEP_MODEL", "gemini-2.5-flash"),
            document_cache_enabled=_env_bool("DOCUMENT_CACHE_ENABLED", "true"),
            document_cache_db_path=os.getenv("DOCUMENT_CACHE_DB_PATH", os.path.join("data", "document_cache.sqlite3")),
            document_cache_ttl_seconds=int(os.getenv("DOCUMENT_CACHE_TTL_SECONDS", "86400")),
            document_cache_max_entries=int(os.getenv("DOCUMENT_CACHE_MAX_ENTRIES", "256")),
            document_vision_max_workers=max(1, int(os.getenv("DOCUMENT_VISION_MAX_WORKERS", "4"))),
            document_ocr_max_workers=max(1, int(os.getenv("DOCUMENT_OCR_MAX_WORKERS", "6"))),
            document_reasoning_max_chunks=max(4, int(os.getenv("DOCUMENT_REASONING_MAX_CHUNKS", "10"))),
            document_reasoning_text_char_budget=max(6000, int(os.getenv("DOCUMENT_REASONING_TEXT_CHAR_BUDGET", "22000"))),
            document_reasoning_ocr_char_budget=max(3000, int(os.getenv("DOCUMENT_REASONING_OCR_CHAR_BUDGET", "9000"))),
            document_reasoning_vision_visible_char_budget=max(
                2000,
                int(os.getenv("DOCUMENT_REASONING_VISION_VISIBLE_CHAR_BUDGET", "7000")),
            ),
            document_reasoning_vision_layout_char_budget=max(
                1000,
                int(os.getenv("DOCUMENT_REASONING_VISION_LAYOUT_CHAR_BUDGET", "2600")),
            ),
            document_reasoning_vision_summary_char_budget=max(
                800,
                int(os.getenv("DOCUMENT_REASONING_VISION_SUMMARY_CHAR_BUDGET", "2600")),
            ),
            document_reasoning_fast_path_threshold_chars=max(
                4000,
                int(os.getenv("DOCUMENT_REASONING_FAST_PATH_THRESHOLD_CHARS", "14000")),
            ),
            document_reasoning_default_fast=_env_bool("DOCUMENT_REASONING_DEFAULT_FAST", "true"),
            document_ultra_fast_enabled=_env_bool("DOCUMENT_ULTRA_FAST_ENABLED", "true"),
            document_ultra_fast_min_chars=max(
                300,
                int(os.getenv("DOCUMENT_ULTRA_FAST_MIN_CHARS", "700")),
            ),
            document_skip_vision_for_text_rich=_env_bool("DOCUMENT_SKIP_VISION_FOR_TEXT_RICH", "true"),
            document_text_rich_min_chars=max(
                600,
                int(os.getenv("DOCUMENT_TEXT_RICH_MIN_CHARS", "1800")),
            ),
        )
