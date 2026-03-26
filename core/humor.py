from __future__ import annotations

import random
import re
from collections import deque


class HumorEngine:
    """Contextual one-liner generator with short-term repetition guards."""

    def __init__(self, *, seed: int | None = None, recent_window: int = 6) -> None:
        self._rng = random.Random(seed)
        self._recent_lines: deque[str] = deque(maxlen=max(2, recent_window))
        self._templates: dict[str, list[str]] = {
            "storm": [
                "Storm activity is active right now, so outdoor plans need backup options.",
                "Conditions are volatile enough to justify staying indoors for a while.",
                "The sky is in a dramatic mood; caution is the smart play.",
                "This weather has strong plot-twist energy, so keep plans flexible.",
                "A short delay to outdoor plans is probably the efficient decision.",
            ],
            "rain": [
                "Rain conditions are active, so keeping an umbrella nearby is a good call.",
                "It is a wet setup outside, so travel plans should stay flexible.",
                "Expect periodic rain; dry shoes may require defensive planning.",
                "Road conditions may be slower than usual, so timing buffer helps.",
                "Rainfall is steady enough to make covered routes the safer option.",
            ],
            "snow": [
                "Cold conditions are serious enough for proper layers before stepping out.",
                "It is blanket weather, and the blanket has a strong argument.",
                "Outside is running a winter test, so insulation is not optional.",
                "This is weather that rewards gloves and punishes optimism.",
                "Layering strategy matters more than fashion today.",
            ],
            "very_hot": [
                "The temperature is pushing limits, so hydration and shade matter.",
                "Outdoor activity is mildly ambitious in this heat.",
                "Conditions are leaning uncomfortable, especially in direct sun.",
                "Heat stress risk is elevated, so keep exposure brief when possible.",
                "Midday outdoor plans are possible, but comfort will be negotiable.",
            ],
            "hot": [
                "It is warm enough that water breaks should be frequent.",
                "The day is running hot, so pacing outdoor activity makes sense.",
                "Heat is noticeable; comfort improves with lighter plans.",
                "This temperature rewards shaded routes and lighter scheduling.",
                "A slower outdoor pace will feel smarter than usual today.",
            ],
            "cold": [
                "The air is sharp enough that an extra layer is worth it.",
                "Conditions are chilly, so longer outdoor plans need warm gear.",
                "A warmer jacket will pay dividends today.",
                "The temperature is manageable, but layering still saves comfort.",
                "Cold air is noticeable enough to plan for wind exposure.",
            ],
            "mild": [
                "Conditions look manageable with no major weather drama.",
                "The weather is fairly balanced right now.",
                "Overall conditions are steady and workable.",
                "This is a practical weather window for normal plans.",
                "Conditions are cooperative and should not disrupt typical routines.",
            ],
        }

    @staticmethod
    def _is_any(token_set: set[str], *keywords: str) -> bool:
        return any(keyword in token_set for keyword in keywords)

    def _bucket(self, *, temp_c: float, weather_code: int | None, condition: str) -> str:
        normalized = re.sub(r"[^a-z\s]", " ", (condition or "").lower())
        tokens = {token for token in normalized.split() if token}

        if weather_code in {95, 96, 99} or self._is_any(tokens, "thunderstorm", "thunder"):
            return "storm"
        if weather_code in {61, 63, 65, 80, 81, 82} or self._is_any(tokens, "rain", "drizzle", "showers"):
            return "rain"
        if weather_code in {71, 73, 75, 85, 86} or self._is_any(tokens, "snow"):
            return "snow"
        if temp_c >= 37:
            return "very_hot"
        if temp_c >= 31:
            return "hot"
        if temp_c <= 10:
            return "cold"
        return "mild"

    def _pick_non_repeating(self, candidates: list[str]) -> str:
        fresh = [line for line in candidates if line not in self._recent_lines]
        pool = fresh if fresh else candidates
        choice = self._rng.choice(pool)
        self._recent_lines.append(choice)
        return choice

    def weather_line(
        self,
        *,
        temp_c: float,
        condition: str,
        weather_code: int | None,
        context: str = "",
    ) -> str:
        bucket = self._bucket(temp_c=temp_c, weather_code=weather_code, condition=condition)
        templates = self._templates.get(bucket, self._templates["mild"])
        line = self._pick_non_repeating(templates)

        if context and self._rng.random() < 0.15:
            return f"{line} ({context})"
        return line
