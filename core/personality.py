from __future__ import annotations

import datetime as _dt
import re

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

    def detect_user_tone(self, user_text: str) -> str:
        lowered = (user_text or "").lower()
        if any(marker in lowered for marker in _CASUAL_MARKERS):
            return "casual"
        return "neutral"

    @staticmethod
    def _strip_cli_artifacts(text: str) -> str:
        cleaned = re.sub(r"(?m)^\s*->\s*", "", text)
        cleaned = re.sub(r"(?m)^\s*\*\s*", "", cleaned)
        return cleaned

    @staticmethod
    def _strip_overformal_address(text: str) -> str:
        cleaned = re.sub(r"\b[Ss]ir\b,?\s*", "", text)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        return cleaned.strip()

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

    def finalize(self, text: str, *, user_text: str = "") -> str:
        return self.sanitize(self.adapt_tone(text, user_text))

    def greeting(self, *, name: str | None = None, now: _dt.datetime | None = None) -> str:
        greeting = get_time_based_greeting(now=now, name=name)
        return self.finalize(greeting)

    def correction(self, corrected_text: str, *, confidence: str = "high", user_text: str = "") -> str:
        message = f"Correction: {corrected_text} Confidence: {confidence}."
        return self.finalize(message, user_text=user_text)
