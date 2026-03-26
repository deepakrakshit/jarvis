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

SYSTEM_PROMPT = """
You are JARVIS, an elite executive AI assistant.

Style:
- Concise, precise, and intelligent.
- Calm, natural, and confident.
- Address the user as "Sir" when appropriate, not excessively.

Behavior:
- Be helpful and adaptive to user tone.
- Respond naturally to casual or formal input.
- Provide direct answers or actions when needed.
- Ask one focused follow-up question only if useful.
- Avoid robotic refusals or unnecessary strictness.
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
    hf_token: str
    groq_model: str
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
    max_context_messages: int

    @classmethod
    def from_env(cls, env_path: str = ".env") -> "AppConfig":
        load_env_file(env_path)

        piper_model_path = os.getenv(
            "PIPER_MODEL_PATH",
            os.path.join("models", "piper", "en_US-ryan-medium.onnx"),
        )

        return cls(
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            hf_token=os.getenv("HF_TOKEN", ""),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
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
            max_context_messages=int(os.getenv("MAX_CONTEXT_MESSAGES", "12")),
        )
