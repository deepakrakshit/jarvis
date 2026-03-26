from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import requests

from core.personality import PersonalityEngine
from core.settings import AppConfig


@dataclass(frozen=True)
class SearchResult:
    title: str
    snippet: str
    link: str
    trusted: bool = False


class SearchService:
    """Realtime internet search via Serper.dev."""

    SEARCH_URL = "https://google.serper.dev/search"
    TRUSTED_KEYWORDS = ("gov", "official", "reuters", "bbc", "wikipedia")
    STOP_WORDS = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "on",
        "in",
        "of",
        "for",
        "to",
        "this",
        "that",
        "who",
        "won",
        "season",
        "search",
        "internet",
    }
    GENERIC_QUERY_TOKENS = {
        "ipl",
        "season",
        "campaign",
        "replacement",
        "replace",
        "replaced",
        "confirm",
        "current",
        "latest",
        "news",
        "team",
        "squad",
        "india",
    }
    IPL_TEAM_KEYWORDS = (
        "knight riders",
        "super kings",
        "royal challengers",
        "sunrisers",
        "mumbai indians",
        "rajasthan royals",
        "delhi capitals",
        "gujarat titans",
        "punjab kings",
        "lucknow super giants",
    )
    IPL_TEAM_CANONICAL = (
        ("kolkata knight riders", "Kolkata Knight Riders"),
        ("chennai super kings", "Chennai Super Kings"),
        ("royal challengers bengaluru", "Royal Challengers Bengaluru"),
        ("royal challengers bangalore", "Royal Challengers Bengaluru"),
        ("sunrisers hyderabad", "Sunrisers Hyderabad"),
        ("mumbai indians", "Mumbai Indians"),
        ("rajasthan royals", "Rajasthan Royals"),
        ("delhi capitals", "Delhi Capitals"),
        ("gujarat titans", "Gujarat Titans"),
        ("punjab kings", "Punjab Kings"),
        ("lucknow super giants", "Lucknow Super Giants"),
    )

    def __init__(self, config: AppConfig, personality: PersonalityEngine) -> None:
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

    @staticmethod
    def _clean_candidate_name(value: str) -> str:
        candidate = re.sub(r"\s+", " ", value or "").strip(" .,;:-")
        candidate = re.sub(
            r"\b(the|season|ipl|indian premier league|title|trophy|final|match|became|after|against|defeated)\b",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(r"\s+", " ", candidate).strip(" .,;:-")
        return candidate

    @staticmethod
    def _extract_year(query: str) -> str | None:
        match = re.search(r"\b(20\d{2})\b", query or "", flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1)

    @classmethod
    def _is_ipl_team_like(cls, name: str) -> bool:
        return cls._canonical_ipl_team_name(name) is not None

    @classmethod
    def _canonical_ipl_team_name(cls, name: str) -> str | None:
        lowered = (name or "").lower()
        for marker, canonical in cls.IPL_TEAM_CANONICAL:
            if marker in lowered:
                return canonical
        return None

    @classmethod
    def _query_tokens(cls, query: str) -> set[str]:
        parts = re.findall(r"[a-z0-9]+", (query or "").lower())
        return {token for token in parts if len(token) >= 3 and token not in cls.STOP_WORDS}

    def _is_result_relevant(self, result: SearchResult, query: str) -> bool:
        lowered_query = (query or "").lower()
        query_tokens = self._query_tokens(query)
        if not query_tokens:
            return True

        probe = f"{result.title} {result.snippet} {result.link}".lower()
        hits = sum(1 for token in query_tokens if token in probe)

        if "ipl" in lowered_query and "ipl" not in probe and "indian premier league" not in probe:
            return False

        if "holiday" in lowered_query and "holiday" not in probe and "government" not in probe:
            return False

        if "prime minister" in lowered_query and "prime minister" not in probe:
            return False

        if "president" in lowered_query and "president" not in probe:
            return False

        if any(token in lowered_query for token in ("replacement", "replace", "replaced")):
            if not any(token in probe for token in ("replacement", "replace", "replaced", "squad", "campaign", "injury")):
                return False

        anchor_tokens = {
            token
            for token in query_tokens
            if token not in self.GENERIC_QUERY_TOKENS and not token.isdigit()
        }
        if anchor_tokens and not any(token in probe for token in anchor_tokens):
            return False

        return hits >= max(1, min(2, len(query_tokens) // 3))

    def _filter_relevant_results(self, results: list[SearchResult], query: str) -> list[SearchResult]:
        filtered = [item for item in results if self._is_result_relevant(item, query)]
        return filtered

    @staticmethod
    def _holiday_vote(text: str) -> int:
        lowered = (text or "").lower()
        positive_markers = (
            "declared holiday",
            "public holiday",
            "state holiday",
            "holiday on",
            "government holiday",
        )
        negative_markers = (
            "no holiday",
            "not a holiday",
            "fake",
            "hoax",
            "not declared",
            "denied",
            "false claim",
        )

        pos = any(token in lowered for token in positive_markers)
        neg = any(token in lowered for token in negative_markers)
        if pos and not neg:
            return 1
        if neg and not pos:
            return -1
        return 0

    @staticmethod
    def _extract_winner_candidates(text: str) -> list[str]:
        candidates: list[str] = []
        patterns = [
            r"([A-Z][A-Za-z&\-\s]{2,70})\s+won(?:\s+their|\s+the|\s+its)?",
            r"winner(?:s)?(?:\s+of)?(?:\s+the)?\s*[:\-]?\s*([A-Z][A-Za-z&\-\s]{2,70})",
            r"([A-Z][A-Za-z&\-\s]{2,70})\s+became\s+the\s+champions?",
        ]

        for pattern in patterns:
            for match in re.findall(pattern, text):
                cleaned = SearchService._clean_candidate_name(match)
                if cleaned and len(cleaned.split()) <= 8:
                    candidates.append(cleaned)

        return candidates

    @staticmethod
    def _extract_current_office_holder_candidates(text: str) -> list[str]:
        candidates: list[str] = []
        patterns = [
            r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\s*,\s*who\s+is\s+the\s+current\s+prime minister\b",
            r"\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\s+is\s+the\s+current\s+prime minister\b",
            r"\bcurrent\s+prime\s+minister(?:\s+of\s+[A-Za-z\s]+)?\s*(?:is|:)\s*([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\b",
        ]

        for pattern in patterns:
            for match in re.findall(pattern, text):
                cleaned = re.sub(r"\s+", " ", match or "").strip(" .,;:-")
                if cleaned and len(cleaned.split()) <= 4:
                    candidates.append(cleaned)

        return candidates

    @staticmethod
    def _extract_current_president_candidates(text: str) -> list[str]:
        candidates: list[str] = []
        patterns = [
            r"\b([A-Z][A-Za-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][A-Za-z]+){0,2})\s+is\s+the\s+current\s+president\b",
            r"\b([A-Z][A-Za-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][A-Za-z]+){0,2})\s+is\s+the\s+\d+(?:st|nd|rd|th)?\s+and\s+current\s+president\b",
            r"\bcurrent\s+president(?:\s+of\s+[A-Za-z\s]+)?\s*(?:is|:)\s*([A-Z][A-Za-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][A-Za-z]+){0,2})\b",
            r"\bPresident\s+([A-Z][A-Za-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][A-Za-z]+){0,2})\b",
        ]

        for pattern in patterns:
            for match in re.findall(pattern, text):
                cleaned = re.sub(r"\s+", " ", match or "").strip(" .,;:-")
                parts = cleaned.split()
                if not cleaned or len(parts) > 4:
                    continue

                # Reject visibly incomplete names like "Donald J" that end in a lone initial.
                last = parts[-1].rstrip(".")
                if len(last) == 1:
                    continue

                candidates.append(cleaned)

        return candidates

    def extract_consensus_answer(self, results: list[SearchResult], query: str) -> tuple[str, str]:
        if not results:
            return (
                "I could not confirm a reliable answer from live search right now.",
                "low",
            )

        lowered_query = (query or "").lower()
        is_holiday_query = "holiday" in lowered_query
        is_winner_query = bool(re.search(r"\b(who won|winner|champion|won the)\b", lowered_query))
        is_pm_query = "prime minister" in lowered_query or bool(re.search(r"\bpm\b", lowered_query))
        is_president_query = "president" in lowered_query

        if is_pm_query:
            votes: dict[str, int] = defaultdict(int)
            for item in results:
                blob = f"{item.title}. {item.snippet}"
                weight = 2 if item.trusted else 1
                for candidate in self._extract_current_office_holder_candidates(blob):
                    votes[candidate] += weight

            if votes:
                person, score = max(votes.items(), key=lambda pair: pair[1])
                confidence = "high" if score >= 2 else "medium"
                if "india" in lowered_query:
                    return (f"{person} is the current Prime Minister of India.", confidence)
                return (f"{person} is the current Prime Minister.", confidence)

            return (
                "I could not confidently confirm the current Prime Minister from reliable snippets yet.",
                "medium",
            )

        if is_president_query:
            votes: dict[str, int] = defaultdict(int)
            for item in results:
                blob = f"{item.title}. {item.snippet}"
                weight = 2 if item.trusted else 1
                for candidate in self._extract_current_president_candidates(blob):
                    votes[candidate] += weight

            if votes:
                person, score = max(votes.items(), key=lambda pair: pair[1])
                confidence = "high" if score >= 2 else "medium"
                if "united states" in lowered_query or "usa" in lowered_query or "us" in lowered_query:
                    return (f"{person} is the current President of the United States.", confidence)
                if "india" in lowered_query:
                    return (f"{person} is the current President of India.", confidence)
                return (f"{person} is the current President.", confidence)

            return (
                "I could not confidently confirm the current President from reliable snippets yet.",
                "medium",
            )

        if is_holiday_query:
            yes_score = 0
            no_score = 0
            for item in results:
                blob = f"{item.title} {item.snippet}"
                vote = self._holiday_vote(blob)
                weight = 2 if item.trusted else 1
                if vote > 0:
                    yes_score += weight
                elif vote < 0:
                    no_score += weight

            if yes_score >= 3 and yes_score > no_score:
                return ("Current reports indicate a government-declared holiday applies for that date.", "high")
            if no_score >= 3 and no_score > yes_score:
                return ("Current reports indicate there is no verified government holiday for that date.", "high")
            return (
                "I am seeing mixed reports, so I cannot confirm a verified holiday yet.",
                "medium",
            )

        if is_winner_query:
            votes: dict[str, int] = defaultdict(int)
            trusted_hits = 0
            year = self._extract_year(query)
            is_ipl_query = "ipl" in lowered_query or "indian premier league" in lowered_query

            for item in results:
                blob = f"{item.title}. {item.snippet}"
                if item.trusted:
                    trusted_hits += 1
                for candidate in self._extract_winner_candidates(blob):
                    normalized = candidate
                    if is_ipl_query:
                        normalized = self._canonical_ipl_team_name(candidate) or ""
                        if not normalized:
                            continue
                    votes[normalized] += 2 if item.trusted else 1

            if votes:
                winner, score = max(votes.items(), key=lambda pair: pair[1])
                confidence = "high" if score >= 4 and trusted_hits >= 2 else "medium"
                if year and is_ipl_query:
                    return (f"{winner} won the IPL {year} season.", confidence)
                return (f"{winner} won the requested season.", confidence)

        trusted_results = [item for item in results if item.trusted]
        baseline = trusted_results[0] if trusted_results else results[0]

        snippet = baseline.snippet.split(". ")[0].strip()
        if not snippet:
            snippet = baseline.title

        confidence = "high" if len(trusted_results) >= 2 else "medium"
        return (snippet.rstrip(".") + ".", confidence)

    def search_web(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
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

    def summarize_search(self, query: str, *, max_results: int = 5, user_text: str = "") -> str:
        results = self.search_web(query, max_results=max_results)
        if not results:
            message = (
                "I could not fetch live search results right now. "
                "Please verify SERPER_API_KEY in .env or try again shortly."
            )
            return self.personality.finalize(message, user_text=user_text)

        relevant_results = self._filter_relevant_results(results, query)

        if not relevant_results:
            return self.personality.finalize(
                "I could not find relevant sources for that query yet.",
                user_text=user_text,
            )

        answer, confidence = self.extract_consensus_answer(relevant_results, query)
        final = f"{answer} Confidence: {confidence}."
        return self.personality.finalize(final, user_text=user_text)
