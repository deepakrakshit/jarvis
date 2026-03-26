from __future__ import annotations

from core.personality import PersonalityEngine
from core.settings import AppConfig
from services.search_service import SearchService


class NewsService:
    """News wrapper that delegates to realtime web search."""

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

    def get_news_brief(self, user_text: str) -> str:
        query = self._news_query(user_text)
        return self.search_service.summarize_search(query, max_results=5, user_text=user_text)
