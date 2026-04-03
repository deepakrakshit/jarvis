from __future__ import annotations

import datetime as _dt
import re

from core.humor import HumorEngine
from core.time_utils import get_time_based_greeting


_FORBIDDEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bfunctioning within optimal parameters\b", re.IGNORECASE), "running smoothly"),
    (re.compile(r"\bsystems online and ready\b", re.IGNORECASE), "ready when you are"),
    (
        re.compile(r"\bI(?: have|'ve) noted your informal greeting\.?\s*", re.IGNORECASE),
        "",
    ),
    (
        re.compile(r"\bI(?:'ll| will) make sure to update (?:my )?(?:knowledge|database)(?: accordingly)?\.?", re.IGNORECASE),
        "You're right. I had outdated information.",
    ),
    (
        re.compile(
            r"\bFor\s+[A-Za-z][A-Za-z\s\-']{1,60},\s*I(?:'ve| have|'ll| will)\s+added\s+[^.]{0,220}knowledge\s+base\.?",
            re.IGNORECASE,
        ),
        "",
    ),
    (
        re.compile(r"\bI(?:'ve| have|'ll| will)\s+added\s+[^.]{0,220}knowledge\s+base\.?", re.IGNORECASE),
        "",
    ),
)

_CASUAL_MARKERS = (
    "bro",
    "hey",
    "yo",
    "nah",
    "nope",
    "cool",
    "buddy",
    "dude",
)


class PersonalityEngine:
    """Central response style policy for local assistant responses."""

    def __init__(self, *, humor_engine: HumorEngine | None = None, controlled_humor: bool = False) -> None:
        self._humor = humor_engine or HumorEngine()
        self._controlled_humor = bool(controlled_humor)

    def detect_user_tone(self, user_text: str) -> str:
        lowered = (user_text or "").lower()
        if any(marker in lowered for marker in _CASUAL_MARKERS):
            return "casual"
        return "neutral"

    @staticmethod
    def _strip_cli_artifacts(text: str) -> str:
        cleaned = re.sub(r"(?m)^\s*->\s*", "", text)
        cleaned = re.sub(r"(?m)^\s*\*\s*", "", cleaned)
        cleaned = re.sub(r"(?im)^\s*assistant\s*:?\s*", "", cleaned)
        cleaned = re.sub(r"(?im)^\s*jarvis\s*:?\s*", "", cleaned)
        return cleaned

    @staticmethod
    def _strip_overformal_address(text: str) -> str:
        # Preserve respectful address terms when explicitly preferred by the user.
        return text

    def sanitize(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""

        cleaned = self._strip_cli_artifacts(cleaned)

        for pattern, replacement in _FORBIDDEN_PATTERNS:
            cleaned = pattern.sub(replacement, cleaned)

        cleaned = self._strip_overformal_address(cleaned)
        cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
        cleaned = re.sub(r"([.?!])\s*\1+", r"\1", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        return cleaned.strip()

    def adapt_tone(self, text: str, user_text: str = "") -> str:
        tone = self.detect_user_tone(user_text)
        adapted = text

        if tone == "casual":
            casual_replacements = (
                ("I could not", "I couldn't"),
                ("I did not", "I didn't"),
                ("I am", "I'm"),
                ("cannot", "can't"),
            )
            for src, dst in casual_replacements:
                adapted = re.sub(rf"\b{re.escape(src)}\b", dst, adapted)

        return adapted

    @staticmethod
    def _humor_category(text: str) -> str:
        lowered = str(text or "").lower()

        if re.search(
            r"\b(could not|couldn't|unable|failed|failure|error|unavailable|blocked|not found|cannot|can't|did not|didn't)\b",
            lowered,
        ):
            return "error"

        if "?" in str(text or ""):
            return "question"

        if re.search(r"\b(done|completed|complete|success|successfully|started|ready|set to|now open|has been)\b", lowered):
            return "success"

        return "neutral"

    @staticmethod
    def _humor_context(text: str, user_text: str = "") -> str:
        probe = f"{user_text or ''} {text or ''}".lower()
        if re.search(r"\b(good morning|good afternoon|good evening|good night|hello|hi|hey|yo)\b", probe):
            return "greeting"
        if re.search(r"\b(how are you|how are you feeling|hru|how ru|doing great)\b", probe):
            return "wellbeing"
        if re.search(r"\b(time|date|day|month|year|today)\b", probe) or "local time is" in probe:
            return "time"
        if "public ip" in probe or "external ip" in probe or re.search(r"\bmy ip\b", probe):
            return "ip"
        if "network location" in probe or "coordinates" in probe or re.search(r"\bwhere am i\b", probe):
            return "location"
        if "connectivity" in probe or "online" in probe:
            return "connectivity"
        if "speed test" in probe or "internet speed" in probe:
            return "speedtest"
        if "weather" in probe or "forecast" in probe or "temperature" in probe or "precipitation" in probe:
            return "weather"
        if "system status" in probe or "cpu" in probe or "ram" in probe or "uptime" in probe:
            return "system"
        if re.search(r"\b(help|commands|what can you do|capabilities)\b", probe):
            return "help"
        return "generic"

    def _apply_controlled_humor(self, text: str, *, user_text: str = "") -> str:
        base = str(text or "").strip()
        if not base:
            return ""

        if not self._controlled_humor:
            return base

        if self._humor.has_known_reply_line_suffix(base):
            return base

        category = self._humor_category(base)
        context = self._humor_context(base, user_text=user_text)
        line = self._humor.reply_line(category=category, context=context)
        if not line:
            return base

        separator = "\n\n" if "\n" in base else " "
        return f"{base}{separator}{line}"

    def finalize(self, text: str, *, user_text: str = "") -> str:
        adapted = self.adapt_tone(text, user_text)
        cleaned = self.sanitize(adapted)
        return self._apply_controlled_humor(cleaned, user_text=user_text)

    def greeting(self, *, name: str | None = None, now: _dt.datetime | None = None) -> str:
        greeting = get_time_based_greeting(now=now, name=name)
        return self.finalize(greeting)

    def correction(self, corrected_text: str, *, confidence: str = "high", user_text: str = "") -> str:
        message = f"Correction: {corrected_text} Confidence: {confidence}."
        return self.finalize(message, user_text=user_text)