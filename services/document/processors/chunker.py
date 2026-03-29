"""Semantic document chunker.

Chunks documents by semantic sections with token limit awareness.
NOT naive splitting — respects section boundaries, paragraph breaks,
and sentence structure for optimal LLM processing.
"""

from __future__ import annotations

import logging
import re

from services.document.models import Chunk, DocumentStructure, Section

logger = logging.getLogger(__name__)

# Token estimation: ~4 characters per token for English text
_CHARS_PER_TOKEN = 4
_DEFAULT_MAX_TOKENS = 2000
_DEFAULT_OVERLAP_TOKENS = 100


def _estimate_tokens(text: str) -> int:
    """Estimate token count from character length."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


class SemanticChunker:
    """Chunk documents by sections with token-aware boundaries.

    Strategy:
    1. Try section-level chunks first (ideal: one section = one chunk)
    2. If a section exceeds token limit, split by paragraphs
    3. If a paragraph exceeds limit, split by sentences
    4. Maintain inter-chunk overlap for context continuity
    """

    def __init__(
        self,
        *,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        overlap_tokens: int = _DEFAULT_OVERLAP_TOKENS,
    ) -> None:
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens
        self._max_chars = max_tokens * _CHARS_PER_TOKEN
        self._overlap_chars = overlap_tokens * _CHARS_PER_TOKEN

    def chunk(self, structure: DocumentStructure) -> list[Chunk]:
        """Produce semantically coherent chunks from a document structure."""
        if not structure.sections:
            return []

        chunks: list[Chunk] = []
        chunk_index = 0

        for section in structure.sections:
            section_chunks = self._chunk_section(section, start_index=chunk_index)
            chunks.extend(section_chunks)
            chunk_index += len(section_chunks)

        if not chunks:
            # Fallback: if no sections produced chunks, create a single chunk
            all_text = "\n\n".join(
                s.content for s in structure.sections if s.content.strip()
            )
            if all_text.strip():
                chunks = [
                    Chunk(
                        index=0,
                        text=all_text,
                        section_heading="Content",
                        token_estimate=_estimate_tokens(all_text),
                    )
                ]

        logger.info("Produced %d chunks from %d sections", len(chunks), len(structure.sections))
        return chunks

    def _chunk_section(self, section: Section, *, start_index: int) -> list[Chunk]:
        """Chunk a single section, respecting token limits."""
        content = section.content.strip()
        if not content:
            return []

        content_tokens = _estimate_tokens(content)

        # Case 1: Section fits in one chunk
        if content_tokens <= self._max_tokens:
            return [
                Chunk(
                    index=start_index,
                    text=content,
                    section_heading=section.heading,
                    token_estimate=content_tokens,
                )
            ]

        # Case 2: Section too large — split by paragraphs
        paragraphs = self._split_paragraphs(content)
        return self._merge_into_chunks(
            paragraphs,
            section_heading=section.heading,
            start_index=start_index,
        )

    def _merge_into_chunks(
        self,
        segments: list[str],
        *,
        section_heading: str,
        start_index: int,
    ) -> list[Chunk]:
        """Merge text segments into chunks, respecting token limits.

        Segments that exceed the limit are further split by sentences.
        """
        chunks: list[Chunk] = []
        current_parts: list[str] = []
        current_chars = 0

        for segment in segments:
            segment_chars = len(segment)

            # If single segment exceeds limit, split by sentences
            if segment_chars > self._max_chars:
                # Flush current buffer
                if current_parts:
                    chunk_text = "\n\n".join(current_parts)
                    chunks.append(
                        Chunk(
                            index=start_index + len(chunks),
                            text=chunk_text,
                            section_heading=section_heading,
                            token_estimate=_estimate_tokens(chunk_text),
                        )
                    )
                    current_parts = []
                    current_chars = 0

                # Split oversized segment by sentences
                sentence_chunks = self._split_by_sentences(segment, section_heading, start_index + len(chunks))
                chunks.extend(sentence_chunks)
                continue

            # Would adding this segment exceed the limit?
            if current_chars + segment_chars > self._max_chars and current_parts:
                chunk_text = "\n\n".join(current_parts)
                chunks.append(
                    Chunk(
                        index=start_index + len(chunks),
                        text=chunk_text,
                        section_heading=section_heading,
                        token_estimate=_estimate_tokens(chunk_text),
                    )
                )

                # Keep overlap from end of previous chunk
                overlap_text = self._extract_overlap(chunk_text)
                current_parts = [overlap_text] if overlap_text else []
                current_chars = len(overlap_text) if overlap_text else 0

            current_parts.append(segment)
            current_chars += segment_chars + 2  # +2 for \n\n join

        # Flush remaining
        if current_parts:
            chunk_text = "\n\n".join(current_parts)
            if chunk_text.strip():
                chunks.append(
                    Chunk(
                        index=start_index + len(chunks),
                        text=chunk_text,
                        section_heading=section_heading,
                        token_estimate=_estimate_tokens(chunk_text),
                    )
                )

        return chunks

    def _split_by_sentences(
        self, text: str, section_heading: str, start_index: int
    ) -> list[Chunk]:
        """Last-resort splitting by sentence boundaries.

        Important: this method must never recurse infinitely for OCR text that
        has no punctuation (single huge sentence). In that case we hard-split
        by character windows.
        """
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if not sentences:
            return self._hard_split(text, section_heading=section_heading, start_index=start_index)

        # If sentence splitting failed to reduce size, enforce hard chunks.
        if len(sentences) == 1 and len(sentences[0]) > self._max_chars:
            return self._hard_split(sentences[0], section_heading=section_heading, start_index=start_index)

        normalized_segments: list[str] = []
        for sentence in sentences:
            if len(sentence) <= self._max_chars:
                normalized_segments.append(sentence)
            else:
                normalized_segments.extend(self._hard_split_segments(sentence))

        return self._merge_into_chunks(
            normalized_segments,
            section_heading=section_heading,
            start_index=start_index,
        )

    def _hard_split(
        self,
        text: str,
        *,
        section_heading: str,
        start_index: int,
    ) -> list[Chunk]:
        """Force-split very long text into bounded chunks."""
        chunks: list[Chunk] = []
        for idx, segment in enumerate(self._hard_split_segments(text)):
            chunks.append(
                Chunk(
                    index=start_index + idx,
                    text=segment,
                    section_heading=section_heading,
                    token_estimate=_estimate_tokens(segment),
                )
            )
        return chunks

    def _hard_split_segments(self, text: str) -> list[str]:
        """Split by character windows with boundary preference for whitespace."""
        normalized = text.strip()
        if not normalized:
            return []

        segments: list[str] = []
        cursor = 0
        length = len(normalized)

        while cursor < length:
            end = min(length, cursor + self._max_chars)
            if end < length:
                candidate = normalized[cursor:end]
                boundary = max(candidate.rfind("\n"), candidate.rfind(" "))
                if boundary > self._max_chars // 3:
                    end = cursor + boundary

            segment = normalized[cursor:end].strip()
            if segment:
                segments.append(segment)

            if end <= cursor:
                # Defensive guard against accidental infinite loops.
                end = min(length, cursor + self._max_chars)
            cursor = end

        return segments

    def _extract_overlap(self, text: str) -> str:
        """Extract the last N characters as overlap context for the next chunk."""
        if len(text) <= self._overlap_chars:
            return ""

        overlap = text[-self._overlap_chars:]
        # Try to start at a sentence or paragraph boundary
        boundary = max(
            overlap.rfind(". "),
            overlap.rfind("? "),
            overlap.rfind("! "),
            overlap.rfind("\n"),
        )
        if boundary > len(overlap) // 3:
            overlap = overlap[boundary + 1:].strip()

        return f"[...] {overlap}" if overlap else ""

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        """Split text into paragraphs, filtering empties."""
        paragraphs = re.split(r"\n{2,}", text)
        return [p.strip() for p in paragraphs if p.strip()]
