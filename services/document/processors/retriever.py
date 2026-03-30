"""Lightweight semantic retrieval for document question answering.

The goal is fast, dependency-free chunk retrieval with robust lexical and
semantic heuristics suitable for runtime Q&A.
"""

from __future__ import annotations

import re
from typing import Any


_WS_RE = re.compile(r"\s+")
_PARA_SPLIT_RE = re.compile(r"\n{2,}")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}

_SYNONYM_GROUPS: tuple[set[str], ...] = (
    {"price", "pricing", "cost", "fee", "amount", "rate"},
    {"risk", "risks", "issue", "issues", "concern", "concerns"},
    {"plan", "plans", "tier", "tiers", "package", "packages"},
    {"feature", "features", "capability", "capabilities", "support", "supports"},
    {"compare", "comparison", "versus", "vs", "difference", "differences"},
)


class SemanticRetriever:
    """Builds retrieval chunks and returns top relevant passages for a query."""

    def __init__(self, *, max_chunk_chars: int = 720, overlap_chars: int = 120) -> None:
        self._max_chunk_chars = max(280, int(max_chunk_chars))
        self._overlap_chars = max(40, min(int(overlap_chars), self._max_chunk_chars // 2))
        self._stemmed_synonym_groups = tuple(
            {self._stem(item) for item in group}
            for group in _SYNONYM_GROUPS
        )
        self._feature_cache: dict[str, dict[str, Any]] = {}

    def build_chunks(
        self,
        text_blocks: list[tuple[str, str]],
        *,
        max_chunks: int = 220,
    ) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        chunk_index = 0

        for source, block in text_blocks:
            if not str(block or "").strip():
                continue

            paragraphs = self._split_paragraphs(block)
            for paragraph in paragraphs:
                for segment in self._segment_text(paragraph):
                    if not segment:
                        continue
                    payload = {
                        "id": f"{source}-{chunk_index}",
                        "source": source,
                        "text": segment,
                    }
                    self._prime_chunk_cache(payload)
                    chunks.append(payload)
                    chunk_index += 1
                    if len(chunks) >= max_chunks:
                        return chunks

        return chunks

    def retrieve(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        *,
        top_k: int = 6,
        min_score: float = 0.08,
    ) -> list[dict[str, Any]]:
        cleaned_query = self._normalize_space(query)
        if not cleaned_query:
            return []

        query_lower = cleaned_query.lower()
        query_tokens = self._expand_tokens(self._tokenize(query_lower))
        if not query_tokens:
            return []
        query_numbers = self._extract_numbers(query_lower)
        query_groups = self._query_synonym_groups(query_tokens)

        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in chunks:
            features = self._get_chunk_features(chunk)
            text = str(features.get("text") or "")
            if not text:
                continue

            score = self._score_chunk(
                query_lower=query_lower,
                query_tokens=query_tokens,
                query_numbers=query_numbers,
                query_groups=query_groups,
                chunk_features=features,
            )
            if score < min_score:
                continue

            payload = {
                "id": str(chunk.get("id") or ""),
                "source": str(chunk.get("source") or "chunk"),
                "text": text,
                "score": round(score, 4),
            }
            scored.append((score, payload))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[: max(1, top_k)]]

    @staticmethod
    def _normalize_space(text: str) -> str:
        return _WS_RE.sub(" ", str(text or "")).strip()

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        raw = _PARA_SPLIT_RE.split(str(text or ""))
        output = [part.strip() for part in raw if part and part.strip()]
        return output if output else [str(text or "").strip()]

    def _segment_text(self, text: str) -> list[str]:
        source = self._normalize_space(text)
        if not source:
            return []

        if len(source) <= self._max_chunk_chars:
            return [source]

        segments: list[str] = []
        cursor = 0
        while cursor < len(source):
            end = min(len(source), cursor + self._max_chunk_chars)
            if end < len(source):
                boundary = source.rfind(" ", cursor + self._max_chunk_chars // 2, end)
                if boundary > cursor:
                    end = boundary

            piece = source[cursor:end].strip()
            if piece:
                segments.append(piece)

            if end >= len(source):
                break

            cursor = max(end - self._overlap_chars, cursor + 1)

        return segments

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        raw = _TOKEN_RE.findall(str(text or "").lower())
        return [token for token in raw if token and token not in _STOPWORDS and len(token) >= 2]

    @staticmethod
    def _extract_numbers(text: str) -> set[str]:
        return set(_NUMBER_RE.findall(str(text or "")))

    @staticmethod
    def _stem(token: str) -> str:
        if token.endswith("ing") and len(token) > 5:
            return token[:-3]
        if token.endswith("ed") and len(token) > 4:
            return token[:-2]
        if token.endswith("es") and len(token) > 4:
            return token[:-2]
        if token.endswith("s") and len(token) > 3:
            return token[:-1]
        return token

    def _expand_tokens(self, tokens: list[str]) -> set[str]:
        token_set = {token for token in tokens if token}
        expanded = {self._stem(token) for token in token_set}

        for idx, group in enumerate(_SYNONYM_GROUPS):
            stemmed_group = self._stemmed_synonym_groups[idx]
            if token_set.intersection(group) or expanded.intersection(stemmed_group):
                expanded.update(stemmed_group)

        return {token for token in expanded if token}

    def _query_synonym_groups(self, query_tokens: set[str]) -> tuple[tuple[str, ...], ...]:
        stemmed_query = {self._stem(token) for token in query_tokens if token}
        groups: list[tuple[str, ...]] = []

        for idx, group in enumerate(_SYNONYM_GROUPS):
            stemmed_group = self._stemmed_synonym_groups[idx]
            if query_tokens.intersection(group) or stemmed_query.intersection(stemmed_group):
                groups.append(tuple(sorted(group)))

        return tuple(groups)

    def _score_chunk(
        self,
        *,
        query_lower: str,
        query_tokens: set[str],
        query_numbers: set[str],
        query_groups: tuple[tuple[str, ...], ...],
        chunk_features: dict[str, Any],
    ) -> float:
        chunk_tokens = chunk_features.get("tokens") if isinstance(chunk_features.get("tokens"), set) else set()
        if not chunk_tokens:
            return 0.0

        overlap = len(query_tokens.intersection(chunk_tokens))
        overlap_score = overlap / max(1, len(query_tokens))

        chunk_lower = str(chunk_features.get("lower") or "")
        phrase_score = 1.0 if query_lower in chunk_lower else 0.0

        chunk_numbers = chunk_features.get("numbers") if isinstance(chunk_features.get("numbers"), set) else set()
        number_score = 1.0 if query_numbers and query_numbers.intersection(chunk_numbers) else 0.0

        semantic_hits = 0
        for group in query_groups:
            if any(item in chunk_lower for item in group):
                semantic_hits += 1
        semantic_score = min(1.0, semantic_hits / 2.0)

        weighted = (
            (overlap_score * 0.62)
            + (phrase_score * 0.18)
            + (number_score * 0.08)
            + (semantic_score * 0.12)
        )
        return min(1.0, max(0.0, weighted))

    def _prime_chunk_cache(self, chunk: dict[str, Any]) -> None:
        _ = self._get_chunk_features(chunk)

    def _get_chunk_features(self, chunk: dict[str, Any]) -> dict[str, Any]:
        text_raw = str(chunk.get("text") or "")
        cache_key = self._chunk_cache_key(chunk)
        cached = self._feature_cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("raw") == text_raw:
            return cached

        normalized = self._normalize_space(text_raw)
        lowered = normalized.lower()
        features = {
            "raw": text_raw,
            "text": normalized,
            "lower": lowered,
            "tokens": self._expand_tokens(self._tokenize(lowered)),
            "numbers": self._extract_numbers(lowered),
        }
        self._feature_cache[cache_key] = features
        if len(self._feature_cache) > 8192:
            self._feature_cache.clear()
        return features

    @staticmethod
    def _chunk_cache_key(chunk: dict[str, Any]) -> str:
        chunk_id = str(chunk.get("id") or "")
        source = str(chunk.get("source") or "")
        text_raw = str(chunk.get("text") or "")
        return f"{source}:{chunk_id}:{hash(text_raw)}"
