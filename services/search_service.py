# ==============================================================================
# File: services/search_service.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Real-Time Internet Search — Gemini Grounding API
#
#    - Gemini Grounding API powered web search with Google Search integration.
#    - Multi-variant query generation: original, no-possessive, stripped-prefix.
#    - Grounding chunk extraction with snippet-to-source index mapping.
#    - Domain-diversified result ranking to prevent single-source dominance.
#    - Trust scoring: gov/official/reuters/bbc/wikipedia sources marked trusted.
#    - LLM-powered query reformulation for zero-result recovery scenarios.
#    - News-aware prompting: recent reporting focus for news-related queries.
#    - Dual interface: search_web() for direct results, search_web_raw() for agents.
#    - Retryable HTTP status handling (408, 429, 500, 502, 503, 504).
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from core.settings import AppConfig
from core.llm_api import chat_complete

import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    title: str
    snippet: str
    link: str
    trusted: bool = False


class SearchService:
    """Realtime internet search powered by Gemini Grounding."""

    GEMINI_SEARCH_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    TRUSTED_KEYWORDS = ("gov", "official", "reuters", "bbc", "wikipedia")
    RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}

    def __init__(self, config: AppConfig, personality: object | None = None) -> None:
        self.config = config
        self.personality = personality

    @staticmethod
    def _normalize_query(query: str) -> str:
        cleaned = (query or "").replace("_", " ").replace("\u2019", "'").strip()
        cleaned = re.sub(r"[\s\-_,.;:!?]+$", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    @classmethod
    def _query_variants(cls, query: str) -> list[str]:
        base = cls._normalize_query(query)
        if not base:
            return []

        variants: list[str] = [base]

        no_possessive = re.sub(r"\b([a-z0-9]+)'s\b", r"\1", base, flags=re.IGNORECASE)
        no_possessive = cls._normalize_query(no_possessive)
        if no_possessive and no_possessive not in variants:
            variants.append(no_possessive)

        stripped_prefix = re.sub(
            r"^\s*(?:check|search|lookup|find)\b(?:\s+(?:the\s+)?)?(?:latest\s+|recent\s+|current\s+)?(?:news\s+)?(?:about\s+|on\s+|for\s+)?",
            "",
            base,
            flags=re.IGNORECASE,
        )
        stripped_prefix = cls._normalize_query(stripped_prefix)
        if stripped_prefix and stripped_prefix not in variants:
            variants.append(stripped_prefix)

        return variants[:3]

    @staticmethod
    def _is_news_query(query: str) -> bool:
        lowered = (query or "").lower()
        return bool(re.search(r"\b(news|headline|headlines|latest|recent|war|conflict|statement|statements)\b", lowered))

    @staticmethod
    def _extract_answer_text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(candidates, list) or not candidates:
            return ""

        first = candidates[0] if isinstance(candidates[0], dict) else {}
        content = first.get("content") if isinstance(first, dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            return ""

        chunks: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = str(part.get("text") or "").strip()
            if text:
                chunks.append(text)

        return "\n".join(chunks).strip()

    @staticmethod
    def _collect_grounding_snippets(candidate: dict[str, Any]) -> dict[int, list[str]]:
        metadata = candidate.get("groundingMetadata") if isinstance(candidate, dict) else None
        if not isinstance(metadata, dict):
            return {}

        snippet_map: dict[int, list[str]] = {}
        supports = metadata.get("groundingSupports")
        if not isinstance(supports, list):
            return snippet_map

        for support in supports:
            if not isinstance(support, dict):
                continue
            segment = support.get("segment") if isinstance(support.get("segment"), dict) else {}
            snippet_text = str(segment.get("text") or "").strip()
            if not snippet_text:
                continue

            indices = support.get("groundingChunkIndices")
            if not isinstance(indices, list):
                continue

            for index in indices:
                if not isinstance(index, int):
                    continue
                values = snippet_map.setdefault(index, [])
                if snippet_text not in values:
                    values.append(snippet_text)

        return snippet_map

    def _fetch_payload(self, *, query: str, max_results: int) -> dict[str, Any] | None:
        api_key = str(self.config.gemini_api_key or "").strip()
        if not api_key:
            return None

        model = str(self.config.gemini_search_model or "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        is_news = self._is_news_query(query)
        prompt = (
            "Use live Google Search grounding to find accurate, current information. "
            f"Query: {query}. "
            + (
                "Focus on the most recent reporting within the last 24-48 hours. "
                "Include dates and timeline context. "
                if is_news
                else "Provide specific, factual evidence with details (names, dates, numbers). "
            )
            + "Be thorough and source-backed. Include multiple relevant sources."
        )

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.15,
                "maxOutputTokens": max(320, min(1200, max_results * 200)),
            },
        }

        candidate_model = model
        for attempt in range(2):
            try:
                response = requests.post(
                    self.GEMINI_SEARCH_URL.format(model=candidate_model),
                    params={"key": api_key},
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=16,
                )
                response.raise_for_status()
                body = response.json()
                if isinstance(body, dict):
                    return body
                return None
            except requests.exceptions.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (400, 404):
                    break
                if status in self.RETRYABLE_HTTP_STATUS_CODES and attempt == 0:
                    time.sleep(0.4)
                    continue
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt == 0:
                    time.sleep(0.4)
                    continue
                break
            except Exception:
                break

        return None

    def _parse_results(self, payload: dict[str, Any], *, query: str, max_results: int) -> list[SearchResult]:
        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(candidates, list) or not candidates:
            return []

        first = candidates[0] if isinstance(candidates[0], dict) else {}
        answer_text = self._extract_answer_text(payload)
        snippet_map = self._collect_grounding_snippets(first)

        metadata = first.get("groundingMetadata") if isinstance(first, dict) else None
        chunks = metadata.get("groundingChunks") if isinstance(metadata, dict) else None
        if not isinstance(chunks, list):
            chunks = []

        parsed: list[SearchResult] = []
        seen: set[tuple[str, str]] = set()

        for index, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                continue

            web = chunk.get("web") if isinstance(chunk.get("web"), dict) else {}
            title = str(web.get("title") or "").strip()
            link = str(web.get("uri") or web.get("url") or "").strip()

            if not title and not link:
                continue

            snippet = ""
            snippet_candidates = snippet_map.get(index) or []
            if snippet_candidates:
                snippet = snippet_candidates[0]
            elif answer_text:
                snippet = answer_text
            if not snippet:
                snippet = "Referenced by Gemini grounded search."

            cleaned_snippet = self._clean_snippet(snippet)
            signature = ((title or "untitled").lower(), link.lower())
            if signature in seen:
                continue
            seen.add(signature)

            parsed.append(
                SearchResult(
                    title=title or "Web result",
                    snippet=cleaned_snippet,
                    link=link,
                    trusted=self._is_trusted_source(link=link, title=title, snippet=cleaned_snippet),
                )
            )
            if len(parsed) >= max_results:
                return parsed

        if parsed:
            return parsed[:max_results]

        fallback = self._clean_snippet(answer_text)
        if fallback:
            return [
                SearchResult(
                    title=f"Gemini grounded summary for: {query}",
                    snippet=fallback,
                    link="",
                    trusted=False,
                )
            ]

        return []

    @staticmethod
    def _clean_snippet(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        return cleaned[:280].rstrip()

    @classmethod
    def _is_trusted_source(cls, *, link: str, title: str, snippet: str) -> bool:
        probe = f"{link} {title} {snippet}".lower()
        return any(keyword in probe for keyword in cls.TRUSTED_KEYWORDS)

    @staticmethod
    def _query_tokens(text: str) -> set[str]:
        stop = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "to",
            "of",
            "in",
            "on",
            "for",
            "latest",
            "current",
            "news",
            "about",
        }
        return {token for token in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(token) >= 2 and token not in stop}

    @staticmethod
    def _result_domain(link: str) -> str:
        try:
            parsed = urlparse(str(link or "").strip())
            host = str(parsed.netloc or "").lower()
            if host.startswith("www."):
                host = host[4:]
            return host
        except Exception:
            return ""

    @classmethod
    def _result_score(cls, item: SearchResult, query_tokens: set[str]) -> int:
        probe = f"{item.title} {item.snippet}".lower()
        overlap = sum(1 for token in query_tokens if token in probe)
        score = overlap * 3
        if item.trusted:
            score += 4
        if item.link:
            score += 1
        if len(item.snippet) >= 80:
            score += 1
        return score

    @classmethod
    def _rank_and_diversify_results(cls, *, query: str, results: list[SearchResult], max_results: int) -> list[SearchResult]:
        if not results:
            return []

        query_tokens = cls._query_tokens(query)
        ranked = sorted(results, key=lambda item: cls._result_score(item, query_tokens), reverse=True)

        selected: list[SearchResult] = []
        used_domains: set[str] = set()
        leftovers: list[SearchResult] = []

        for item in ranked:
            domain = cls._result_domain(item.link)
            if domain and domain in used_domains:
                leftovers.append(item)
                continue
            selected.append(item)
            if domain:
                used_domains.add(domain)
            if len(selected) >= max_results:
                return selected

        for item in leftovers:
            selected.append(item)
            if len(selected) >= max_results:
                break

        return selected[:max_results]

    def search_web(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Fetch grounded web evidence via Gemini."""
        if not str(self.config.gemini_api_key or "").strip():
            return []

        query_variants = self._query_variants(query)
        if not query_variants:
            return []

        merged: list[SearchResult] = []
        merged_seen: set[tuple[str, str]] = set()

        def extend_unique(items: list[SearchResult]) -> None:
            for item in items:
                signature = (item.title.lower(), item.link.lower())
                if signature in merged_seen:
                    continue
                merged_seen.add(signature)
                merged.append(item)
                if len(merged) >= max_results:
                    break

        for variant in query_variants:
            payload = self._fetch_payload(query=variant, max_results=max_results)
            if payload is None:
                continue
            extend_unique(self._parse_results(payload, query=variant, max_results=max_results))
            if len(merged) >= max_results:
                break

        return self._rank_and_diversify_results(query=query, results=merged, max_results=max_results)

    def _reformulate_query_with_llm(self, original_query: str) -> str | None:
        """Use Gemini to reformulate a failed search query into a better one.

        Returns None if reformulation fails or produces the same query.
        """
        try:
            result = chat_complete(
                self.config,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a search query optimizer. Given a user's original search query "
                            "that returned no results, reformulate it into a cleaner, more effective "
                            "search query. Return ONLY the reformulated query, nothing else.\n"
                            "Rules:\n"
                            "- Remove filler words and conversational phrasing\n"
                            "- Keep the core intent and key entities\n"
                            "- Use standard search-friendly phrasing\n"
                            "- If the query mentions a year or specific event, keep those details"
                        ),
                    },
                    {"role": "user", "content": f"Original query: {original_query}"},
                ],
                temperature=0.1,
                max_tokens=60,
                timeout=8,
            ).strip().strip('"\'')

            if result and result.lower() != original_query.lower():
                return result
        except Exception as exc:
            logger.debug("Search query reformulation failed: %s", exc)

        return None

    def search_web_raw(self, query: str, *, max_results: int = 5) -> dict[str, Any]:
        """Return raw search payload for agent synthesis.

        Response format:
        {
            "query": str,
            "results": [{"title": ..., "snippet": ..., "link": ..., "trusted": bool}],
            "error": str
        }
        """
        normalized_query = self._normalize_query(query)
        if not normalized_query:
            return {"query": "", "results": [], "error": "missing query"}

        results = self.search_web(normalized_query, max_results=max_results)

        # If no results, try LLM-powered query reformulation.
        if not results:
            reformulated = self._reformulate_query_with_llm(normalized_query)
            if reformulated:
                logger.info("Reformulated search query: '%s' → '%s'", normalized_query, reformulated)
                results = self.search_web(reformulated, max_results=max_results)
                if results:
                    normalized_query = reformulated

        payload_results = [
            {
                "title": item.title,
                "snippet": item.snippet,
                "link": item.link,
                "trusted": item.trusted,
            }
            for item in results
        ]

        if payload_results:
            return {"query": normalized_query, "results": payload_results, "error": ""}

        return {
            "query": normalized_query,
            "results": [],
            "error": "no_results_or_gemini_search_unavailable",
        }
