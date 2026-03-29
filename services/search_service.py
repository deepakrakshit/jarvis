from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests

from core.settings import AppConfig


@dataclass(frozen=True)
class SearchResult:
    title: str
    snippet: str
    link: str
    trusted: bool = False


class SearchService:
    """Realtime internet search via Serper.dev.

    This service intentionally returns raw search evidence only. Final
    summarization/formatting is delegated to the agent synthesizer layer.
    """

    SEARCH_URL = "https://google.serper.dev/search"
    NEWS_URL = "https://google.serper.dev/news"
    TRUSTED_KEYWORDS = ("gov", "official", "reuters", "bbc", "wikipedia")

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

    def _fetch_payload(self, *, url: str, api_key: str, query: str, max_results: int) -> dict[str, Any] | None:
        try:
            response = requests.post(
                url,
                headers={
                    "X-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "q": query,
                    "num": max(3, min(max_results, 8)),
                },
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return None
        except Exception:
            return None

    def _parse_results(self, payload: dict[str, Any], *, max_results: int) -> list[SearchResult]:
        rows: list[dict[str, Any]] = []
        for key in ("organic", "news"):
            items = payload.get(key)
            if isinstance(items, list):
                rows.extend(item for item in items if isinstance(item, dict))

        parsed: list[SearchResult] = []
        seen: set[tuple[str, str]] = set()
        for entry in rows:
            title = str(entry.get("title") or "").strip()
            link = str(entry.get("link") or "").strip()
            snippet = self._clean_snippet(
                str(entry.get("snippet") or entry.get("description") or entry.get("source") or "")
            )

            if not title:
                continue
            if not snippet:
                snippet = "No summary snippet was provided by the source."

            signature = (title.lower(), link.lower())
            if signature in seen:
                continue
            seen.add(signature)

            parsed.append(
                SearchResult(
                    title=title,
                    snippet=snippet,
                    link=link,
                    trusted=self._is_trusted_source(link=link, title=title, snippet=snippet),
                )
            )
            if len(parsed) >= max_results:
                break

        return parsed

    @staticmethod
    def _clean_snippet(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        return cleaned[:280].rstrip()

    @classmethod
    def _is_trusted_source(cls, *, link: str, title: str, snippet: str) -> bool:
        probe = f"{link} {title} {snippet}".lower()
        return any(keyword in probe for keyword in cls.TRUSTED_KEYWORDS)

    def search_web(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Fetch raw organic search entries from Serper."""
        api_key = (self.config.serper_api_key or "").strip()
        if not api_key or api_key == "your_serper_api_key_here":
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
            payload = self._fetch_payload(
                url=self.SEARCH_URL,
                api_key=api_key,
                query=variant,
                max_results=max_results,
            )
            if payload is None:
                continue
            extend_unique(self._parse_results(payload, max_results=max_results))
            if len(merged) >= max_results:
                return merged[:max_results]

        if merged:
            return merged[:max_results]

        if not self._is_news_query(query_variants[0]):
            return []

        for variant in query_variants:
            payload = self._fetch_payload(
                url=self.NEWS_URL,
                api_key=api_key,
                query=variant,
                max_results=max_results,
            )
            if payload is None:
                continue
            extend_unique(self._parse_results(payload, max_results=max_results))
            if len(merged) >= max_results:
                break

        return merged[:max_results]

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
            "error": "no_results_or_serper_unavailable",
        }
