from __future__ import annotations

from typing import Any

from core.personality import PersonalityEngine
from core.settings import AppConfig
from services.search_service import SearchService


class NewsService:
    """News wrapper built on raw realtime web search."""

    def __init__(self, config: AppConfig, personality: PersonalityEngine, search_service: SearchService) -> None:
        self.config = config
        self.personality = personality
        self.search_service = search_service

    def _news_query(self, user_text: str) -> str:
        lowered = (user_text or "").lower()
        if "global" in lowered or "world" in lowered or "international" in lowered:
            return "latest world news today"

        if "india" in lowered or "indian" in lowered:
            return "latest news in India today"

        return "latest news in India today"

    def get_news_items(self, user_text: str, *, max_results: int = 5) -> dict[str, Any]:
        """Return raw news evidence using search results."""
        query = self._news_query(user_text)
        return self.search_service.search_web_raw(query, max_results=max_results)

    def get_news_brief(self, user_text: str) -> str:
        """Compatibility method for legacy callers.

        The new agent flow should consume raw payloads via `get_news_items` and
        synthesize final responses through the LLM synthesizer.
        """
        payload = self.get_news_items(user_text, max_results=5)
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or not results:
            return self.personality.finalize(
                "I could not fetch live news results right now.",
                user_text=user_text,
            )

        headlines = [str(item.get("title") or "").strip() for item in results[:3] if isinstance(item, dict)]
        headlines = [line for line in headlines if line]
        if not headlines:
            return self.personality.finalize(
                "I could not find usable headlines right now.",
                user_text=user_text,
            )

        composed = "Top headlines: " + " | ".join(headlines)
        return self.personality.finalize(composed, user_text=user_text)
