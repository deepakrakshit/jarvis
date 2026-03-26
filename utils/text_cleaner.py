from __future__ import annotations

import re
from dataclasses import dataclass


_FILLER_WORDS = ("again", "now", "please", "bro", "jarvis", "hey")
_FILLER_RE = re.compile(r"\b(" + "|".join(re.escape(word) for word in _FILLER_WORDS) + r")\b", re.IGNORECASE)


@dataclass(frozen=True)
class CleanedText:
    original_text: str
    cleaned_text: str
    had_again: bool


class TextCleaner:
    """Normalize user queries before intent parsing."""

    def clean(self, text: str) -> CleanedText:
        original = (text or "").strip()
        if not original:
            return CleanedText(original_text="", cleaned_text="", had_again=False)

        had_again = bool(re.search(r"\bagain\b", original, flags=re.IGNORECASE))
        cleaned = _FILLER_RE.sub(" ", original)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"\s+([,.;!?])", r"\1", cleaned)
        cleaned = cleaned.strip(" .,!?;:")
        cleaned = cleaned.strip()

        return CleanedText(
            original_text=original,
            cleaned_text=cleaned,
            had_again=had_again,
        )
