from __future__ import annotations

import random
import re
from collections import deque
from typing import Literal


class HumorEngine:
    """Contextual one-liner generator with short-term repetition guards."""

    def __init__(self, *, seed: int | None = None, recent_window: int = 6) -> None:
        self._rng = random.Random(seed)
        self._recent_lines: deque[str] = deque(maxlen=max(2, recent_window))
        self._recent_reply_lines: deque[str] = deque(maxlen=max(4, recent_window * 2))
        self._reply_decks: dict[str, deque[str]] = {}
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
        self._reply_templates: dict[str, list[str]] = {
            "success": [
                "Clean result, tiny victory lap.",
                "Task handled; drama stayed offline.",
                "Another neat win for the mission log.",
                "Smooth run, no cinematic chaos.",
                "Done and tidy, exactly as intended.",
                "That landed cleanly.",
                "Good execution, low noise.",
                "Mission step complete.",
                "Solid output, no friction.",
                "That went exactly on script.",
                "We keep collecting clean wins.",
            ],
            "error": [
                "No panic, we can reroute this.",
                "That one slipped, but control is intact.",
                "Not ideal, still recoverable.",
                "Small bump, steady hands.",
                "We can take another clean shot.",
                "No drama, we adapt and continue.",
                "This is fixable in one more pass.",
                "Temporary miss, permanent progress.",
                "We stay calm and iterate.",
                "No crash, just a course correction.",
            ],
            "question": [
                "Ready for the next round.",
                "Queue the next challenge.",
                "Warm engines for follow-up.",
                "Your move, listening closely.",
                "Round two can start anytime.",
                "Next prompt can drop anytime.",
                "I am prepped for the follow-up.",
                "Send the next objective.",
                "Standing by for your next call.",
                "Happy to keep the momentum going.",
            ],
            "neutral": [
                "Keeping it sharp and light.",
                "Precision first, mischief second.",
                "Calm, clear, and slightly amused.",
                "Professional tone, playful edge.",
                "Steady output with a small grin.",
                "Clear signal, low noise.",
                "Staying practical with a wink.",
                "Measured output, light touch.",
                "Neat, direct, and lightly playful.",
                "Clean words, zero chaos.",
            ],
        }
        self._context_templates: dict[str, list[str]] = {
            "greeting": [
                "Launch tone set.",
                "Shift is live.",
                "Command deck is open.",
                "Systems are awake.",
                "All channels are clear.",
                "Ready for your first objective.",
            ],
            "wellbeing": [
                "Core mood: steady and useful.",
                "Energy is stable and mission-ready.",
                "Running smooth and alert.",
                "All good on this side.",
                "Confidence high, noise low.",
            ],
            "time": [
                "Clockwork confirmed.",
                "Timeline synced.",
                "Chronology check passed.",
                "Timeboard is in order.",
                "Temporal diagnostics look clean.",
            ],
            "ip": [
                "Internet passport located.",
                "Network badge is visible.",
                "Address lock acquired.",
                "External route looks healthy.",
                "IP telemetry looks stable.",
            ],
            "location": [
                "Geo fix is stable.",
                "Location lock confirmed.",
                "Position map looks clean.",
                "Coordinates aligned.",
                "Geo telemetry is consistent.",
            ],
            "connectivity": [
                "Link state looks healthy.",
                "Network pulse is steady.",
                "Connectivity channel is responsive.",
                "Online signal checks out.",
                "Route quality is stable.",
            ],
            "system": [
                "Diagnostics lane is calm.",
                "System telemetry is readable.",
                "Status board is clean.",
                "Machine rhythm looks stable.",
                "Ops panel looks healthy.",
            ],
            "weather": [
                "Sky report delivered.",
                "Forecast channel is active.",
                "Atmosphere update complete.",
                "Weather board refreshed.",
                "Climate snapshot locked.",
            ],
            "speedtest": [
                "Bandwidth lane checked.",
                "Network sprint completed.",
                "Throughput reading is in.",
                "Speed telemetry captured.",
                "Link performance logged.",
            ],
            "help": [
                "Navigation mode enabled.",
                "Guide rails are up.",
                "Command map is ready.",
                "Support panel is open.",
                "You can call any lane now.",
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

    def _pick_non_repeating(self, candidates: list[str], *, recent: deque[str] | None = None) -> str:
        recent_lines = recent if recent is not None else self._recent_lines
        fresh = [line for line in candidates if line not in recent_lines]
        pool = fresh if fresh else candidates
        choice = self._rng.choice(pool)
        recent_lines.append(choice)
        return choice

    def _pick_from_deck(self, key: str, candidates: list[str], *, recent: deque[str]) -> str:
        if not candidates:
            return ""

        deck = self._reply_decks.get(key)
        if not deck:
            shuffled = list(candidates)
            self._rng.shuffle(shuffled)
            deck = deque(shuffled)
            self._reply_decks[key] = deck

        selected = ""
        attempts = len(deck)
        while attempts > 0:
            candidate = deck.popleft()
            if candidate not in recent:
                selected = candidate
                break
            deck.append(candidate)
            attempts -= 1

        if not selected:
            selected = deck.popleft() if deck else candidates[0]

        if not deck:
            reshuffled = list(candidates)
            self._rng.shuffle(reshuffled)
            deck.extend(reshuffled)

        recent.append(selected)
        self._reply_decks[key] = deck
        return selected

    @property
    def reply_line_catalog(self) -> set[str]:
        lines = {line for values in self._reply_templates.values() for line in values}
        lines.update(line for values in self._context_templates.values() for line in values)
        return lines

    def has_known_reply_line_suffix(self, text: str) -> bool:
        stripped = str(text or "").strip()
        if not stripped:
            return False
        for line in self.reply_line_catalog:
            if stripped.endswith(line):
                return True
        return False

    def reply_line(
        self,
        *,
        category: Literal["success", "error", "question", "neutral"] = "neutral",
        context: str = "",
    ) -> str:
        normalized_context = re.sub(r"[^a-z0-9_]+", "", str(context or "").lower())
        candidates: list[str] = []

        if normalized_context and normalized_context in self._context_templates:
            candidates.extend(self._context_templates[normalized_context])

        candidates.extend(self._reply_templates.get(category, self._reply_templates["neutral"]))
        unique_candidates = list(dict.fromkeys(candidates))

        deck_key = f"{category}:{normalized_context or 'generic'}"
        return self._pick_from_deck(deck_key, unique_candidates, recent=self._recent_reply_lines)

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
