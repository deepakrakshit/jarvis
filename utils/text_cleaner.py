# ==============================================================================
# File: utils/text_cleaner.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    User Input Text Normalizer — Filler Word Removal & Normalization
#
#    - Strips filler words: again, now, please, bro, jarvis, hey.
#    - Compiled regex patterns for efficient repeated matching.
#    - CleanedText dataclass: original_text, cleaned_text, had_again flag.
#    - had_again tracking enables weather re-query detection in runtime.
#    - Whitespace normalization: collapses multiple spaces and tabs.
#    - Punctuation cleanup: removes trailing/leading punctuation noise.
#    - Preserves original text alongside cleaned version for context.
#    - Used by runtime, weather service, and agent loop for input normalization.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

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
