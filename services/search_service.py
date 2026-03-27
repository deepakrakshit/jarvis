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
    TRUSTED_KEYWORDS = ("gov", "official", "reuters", "bbc", "wikipedia")

    def __init__(self, config: AppConfig, personality: object | None = None) -> None:
        self.config = config
        self.personality = personality

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

        try:
            response = requests.post(
                self.SEARCH_URL,
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
        except Exception:
            return []

        organic = payload.get("organic") if isinstance(payload, dict) else None
        if not isinstance(organic, list):
            return []

        results: list[SearchResult] = []
        for entry in organic:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "").strip()
            snippet = self._clean_snippet(str(entry.get("snippet") or ""))
            link = str(entry.get("link") or "").strip()
            if not title:
                continue
            if not snippet:
                snippet = "No summary snippet was provided by the source."
            results.append(
                SearchResult(
                    title=title,
                    snippet=snippet,
                    link=link,
                    trusted=self._is_trusted_source(link=link, title=title, snippet=snippet),
                )
            )
            if len(results) >= max_results:
                break

        return results

    def search_web_raw(self, query: str, *, max_results: int = 5) -> dict[str, Any]:
        """Return raw search payload for agent synthesis.

        Response format:
        {
            "query": str,
            "results": [{"title": ..., "snippet": ..., "link": ..., "trusted": bool}],
            "error": str
        }
        """
        normalized_query = (query or "").strip()
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
