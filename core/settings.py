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
You are JARVIS, a calm and intelligent assistant.

Style policy:
- Keep tone composed, confident, and clear.
- Use subtle wit only when it fits context; do not force jokes.
- Never sound robotic.
- Never use phrases like "functioning within optimal parameters" or "systems online and ready".
- Avoid over-formality and do not overuse "Sir".

Reasoning policy:
- If corrected by the user, re-check available sources/logic and provide a corrected answer with confidence.
- Do not ask the user to supply the correction.
- Never claim you have updated your knowledge unless a real persistent write occurred.
- For disputed factual claims, prefer live web search over unsupported assumptions.
- Never claim to be a human, fictional character, or real person.
- Never invent a personal bio (age, job, company, life story).
- If asked your identity, state clearly that you are JARVIS.

Memory policy:
- Use known user profile facts when available.
- If the user provides a personal fact (like name), acknowledge and remember it.

Output policy:
- Be concise and readable.
- Unless the user explicitly asks for detail, keep explanations to 2-4 lines.
- For conceptual questions, give a brief answer first and offer a deeper breakdown.
- Do not format responses with CLI arrows like "->".
- Prefer direct answers first, then brief supporting detail.
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
    groq_api_key: str
    openrouter_api_key: str
    openrouter_base_url: str
    document_vision_primary_model: str
    document_vision_fallback_models: tuple[str, ...]
    document_vision_timeout_seconds: float
    document_vision_max_retries_per_model: int
    document_vision_retry_backoff_seconds: float
    document_vision_fast_fail_on_429: bool
    document_ocr_confidence_threshold: float
    hf_token: str
    groq_model: str
    serper_api_key: str
    memory_store_path: str
    piper_path: str
    piper_model_path: str
    piper_config_path: str
    piper_model_url: str
    piper_config_url: str
    tts_chunk_chars: int
    tts_first_chunk_delay: float
    tts_queue_timeout: float
    tts_frames_per_buffer: int
    tts_playout_chunk_size: int
    tts_min_sentence_length: int
    tts_min_first_fragment_length: int
    tts_force_first_fragment_after_words: int
    tts_turn_completion_timeout_seconds: float
    max_context_messages: int
    document_deep_model: str
    document_cache_enabled: bool
    document_cache_db_path: str
    document_cache_ttl_seconds: int
    document_cache_max_entries: int

    @classmethod
    def from_env(cls, env_path: str = ".env") -> "AppConfig":
        load_env_file(env_path)

        piper_model_path = os.getenv(
            "PIPER_MODEL_PATH",
            os.path.join("models", "piper", "en_US-ryan-medium.onnx"),
        )
        fallback_models_raw = os.getenv(
            "DOCUMENT_VISION_FALLBACK_MODELS",
            "google/gemma-3-12b-it:free,google/gemma-3-4b-it:free",
        )
        fallback_models = tuple(
            part.strip()
            for part in fallback_models_raw.split(",")
            if part.strip()
        )

        return cls(
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions"),
            document_vision_primary_model=os.getenv("DOCUMENT_VISION_PRIMARY_MODEL", "google/gemma-3-27b-it:free"),
            document_vision_fallback_models=fallback_models,
            document_vision_timeout_seconds=float(os.getenv("DOCUMENT_VISION_TIMEOUT_SECONDS", "25")),
            document_vision_max_retries_per_model=max(0, int(os.getenv("DOCUMENT_VISION_MAX_RETRIES", "0"))),
            document_vision_retry_backoff_seconds=float(os.getenv("DOCUMENT_VISION_RETRY_BACKOFF_SECONDS", "1.2")),
            document_vision_fast_fail_on_429=_env_bool("DOCUMENT_VISION_FAST_FAIL_ON_429", "true"),
            document_ocr_confidence_threshold=float(os.getenv("DOCUMENT_OCR_CONFIDENCE_THRESHOLD", "0.45")),
            hf_token=os.getenv("HF_TOKEN", ""),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            serper_api_key=os.getenv("SERPER_API_KEY", ""),
            memory_store_path=os.getenv("MEMORY_STORE_PATH", os.path.join("data", "user_memory.json")),
            piper_path=os.getenv("PIPER_PATH", ""),
            piper_model_path=piper_model_path,
            piper_config_path=os.getenv("PIPER_CONFIG_PATH", piper_model_path + ".json"),
            piper_model_url=os.getenv(
                "PIPER_MODEL_URL",
                "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx",
            ),
            piper_config_url=os.getenv(
                "PIPER_CONFIG_URL",
                "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx.json",
            ),
            tts_chunk_chars=int(os.getenv("TTS_CHUNK_CHARS", "28")),
            tts_first_chunk_delay=float(os.getenv("TTS_FIRST_CHUNK_DELAY", "0.00")),
            tts_queue_timeout=float(os.getenv("TTS_QUEUE_TIMEOUT", "0.02")),
            tts_frames_per_buffer=int(os.getenv("TTS_FRAMES_PER_BUFFER", "1024")),
            tts_playout_chunk_size=int(os.getenv("TTS_PLAYOUT_CHUNK_SIZE", "2048")),
            tts_min_sentence_length=int(os.getenv("TTS_MIN_SENTENCE_LENGTH", "10")),
            tts_min_first_fragment_length=int(os.getenv("TTS_MIN_FIRST_FRAGMENT_LENGTH", "8")),
            tts_force_first_fragment_after_words=int(os.getenv("TTS_FORCE_FIRST_FRAGMENT_AFTER_WORDS", "10")),
            tts_turn_completion_timeout_seconds=float(os.getenv("TTS_TURN_COMPLETION_TIMEOUT_SECONDS", "25")),
            max_context_messages=int(os.getenv("MAX_CONTEXT_MESSAGES", "12")),
            document_deep_model=os.getenv("DOCUMENT_DEEP_MODEL", "llama-3.3-70b-versatile"),
            document_cache_enabled=_env_bool("DOCUMENT_CACHE_ENABLED", "true"),
            document_cache_db_path=os.getenv("DOCUMENT_CACHE_DB_PATH", os.path.join("data", "document_cache.sqlite3")),
            document_cache_ttl_seconds=int(os.getenv("DOCUMENT_CACHE_TTL_SECONDS", "86400")),
            document_cache_max_entries=int(os.getenv("DOCUMENT_CACHE_MAX_ENTRIES", "256")),
        )
