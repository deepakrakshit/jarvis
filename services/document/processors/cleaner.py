"""LLM-based document text cleaner.

Uses llama-3.1-8b to remove noise, fix broken sentences, and normalize
formatting. Raw OCR output is NEVER passed directly to higher-level LLMs —
this stage sanitizes it first.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os
import re

from services.document.llm_client import DocumentLLMClient
from services.document.models import CleanedContent, RawExtractionResult

logger = logging.getLogger(__name__)

_CLEAN_SYSTEM_PROMPT = """You are a document text cleaner. Your job is to take raw extracted text from a document and clean it up. Follow these rules strictly:

1. Fix broken sentences and words that were split across lines
2. Remove extraction artifacts (random symbols, page numbers, headers/footers repeated on every page)
3. Normalize whitespace and formatting
4. Preserve ALL meaningful content — do not summarize or shorten
5. Preserve paragraph breaks as double newlines
6. Preserve headings (lines starting with # marks)
7. Remove OCR noise (random characters, garbled text)
8. Fix common OCR errors (e.g., 'l' misread as '1', 'O' as '0')

Return ONLY the cleaned text. No explanations, no commentary."""

_MAX_CHUNK_CHARS_FOR_CLEANING = 6000
_MAX_CLEAN_WORKERS = max(2, min(12, (os.cpu_count() or 4)))


class DocumentCleaner:
    """Clean raw extracted document text using LLM assistance."""

    def __init__(self, llm_client: DocumentLLMClient) -> None:
        self._llm = llm_client

    def clean(self, extraction: RawExtractionResult) -> CleanedContent:
        """Clean the raw extraction text.

        For short documents, clean in a single pass.
        For long documents, split into segments, clean each, and rejoin.
        """
        raw_text = extraction.text.strip()
        if not raw_text:
            return CleanedContent(
                original_text="",
                cleaned_text="",
                cleaning_notes="No text to clean",
            )

        # Apply deterministic pre-cleaning first (fast, no LLM)
        pre_cleaned = self._pre_clean(raw_text)

        # If text is short enough, clean in one LLM call
        if len(pre_cleaned) <= _MAX_CHUNK_CHARS_FOR_CLEANING:
            cleaned = self._llm_clean(pre_cleaned)
            return CleanedContent(
                original_text=raw_text,
                cleaned_text=cleaned or pre_cleaned,
                cleaning_notes="single_pass",
            )

        # Split into segments for parallel cleaning
        segments = self._split_for_cleaning(pre_cleaned)
        if len(segments) == 1:
            cleaned = self._llm_clean(segments[0])
            return CleanedContent(
                original_text=raw_text,
                cleaned_text=cleaned or segments[0],
                cleaning_notes="single_segment",
            )

        cleaned_segments: list[str | None] = [None] * len(segments)
        failed_segments = 0
        workers = min(_MAX_CLEAN_WORKERS, len(segments))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(self._llm_clean, segment): idx
                for idx, segment in enumerate(segments)
            }

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                segment = segments[idx]
                try:
                    cleaned = (future.result() or "").strip()
                except Exception as exc:
                    cleaned = ""
                    logger.warning("LLM cleaning worker failed for segment %d/%d: %s", idx + 1, len(segments), exc)

                if cleaned:
                    cleaned_segments[idx] = cleaned
                else:
                    cleaned_segments[idx] = segment
                    failed_segments += 1
                    logger.warning("LLM cleaning failed for segment %d/%d", idx + 1, len(segments))

        combined = "\n\n".join(part for part in cleaned_segments if part is not None)
        notes = f"multi_pass ({len(segments)} segments"
        if failed_segments:
            notes += f", {failed_segments} fallbacks"
        notes += ")"

        return CleanedContent(
            original_text=raw_text,
            cleaned_text=combined,
            cleaning_notes=notes,
        )

    def clean_extracted_text(self, text: str) -> str:
        """Deterministic cleanup for parser-extracted text."""
        return self._pre_clean(text or "")

    def clean_ocr_text(self, text: str) -> str:
        """Extra cleanup pass for OCR text before fusion and reasoning."""
        normalized = self._pre_clean(text or "")
        if not normalized:
            return ""

        lines: list[str] = []
        for line in normalized.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue

            if re.fullmatch(r"[_\-|~`.,:;]{2,}", stripped):
                continue

            if len(stripped) == 1 and not stripped.isalnum():
                continue

            lines.append(stripped)

        return "\n".join(lines).strip()

    def _llm_clean(self, text: str) -> str:
        """Send text to LLM for cleaning. Returns cleaned text or empty string on failure."""
        if not text.strip():
            return ""

        result = self._llm.complete_fast(
            system_prompt=_CLEAN_SYSTEM_PROMPT,
            user_prompt=f"Clean the following extracted document text:\n\n{text}",
            temperature=0.1,
            max_tokens=max(2048, len(text) // 2),
        )
        return result.strip()

    @staticmethod
    def _pre_clean(text: str) -> str:
        """Deterministic pre-cleaning without LLM.

        Handles common extraction artifacts that don't need AI judgment.
        """
        # Normalize Unicode whitespace
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n")

        # Remove null bytes and control characters (except newlines and tabs)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)

        # Collapse excessive blank lines (3+ → 2)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        # Remove lines that are only whitespace + special characters
        lines = cleaned.split("\n")
        filtered_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            # Keep empty lines (paragraph breaks) and lines with actual content
            if not stripped:
                filtered_lines.append("")
                continue
            # Skip lines that are only special chars (page decorations)
            if re.fullmatch(r"[^\w\s]*", stripped):
                continue
            # Skip standalone page numbers
            if re.fullmatch(r"(?:page\s*)?\d{1,4}(?:\s*of\s*\d{1,4})?", stripped, re.IGNORECASE):
                continue
            filtered_lines.append(line)

        cleaned = "\n".join(filtered_lines)

        # Collapse multiple spaces within lines
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)

        return cleaned.strip()

    @staticmethod
    def _split_for_cleaning(text: str, max_chars: int = _MAX_CHUNK_CHARS_FOR_CLEANING) -> list[str]:
        """Split text into segments for parallel LLM cleaning.

        Respects paragraph boundaries to avoid splitting mid-sentence.
        """
        paragraphs = text.split("\n\n")
        segments: list[str] = []
        current_segment: list[str] = []
        current_length = 0

        for para in paragraphs:
            para_len = len(para)

            if current_length + para_len > max_chars and current_segment:
                segments.append("\n\n".join(current_segment))
                current_segment = []
                current_length = 0

            current_segment.append(para)
            current_length += para_len + 2  # +2 for \n\n

        if current_segment:
            segments.append("\n\n".join(current_segment))

        return segments if segments else [text]
