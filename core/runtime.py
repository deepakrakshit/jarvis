from __future__ import annotations

import datetime
import json
import re
import threading
import time
from typing import Callable

import requests

from core.humor import HumorEngine
from core.personality import PersonalityEngine
from core.settings import AppConfig, RESET, SYSTEM_PROMPT, WHITE
from memory.store import MemoryStore, extract_user_name
from services.intent_router import IntentRouter
from services.news_service import NewsService
from services.network_service import NetworkService
from services.search_service import SearchService
from services.weather_service import WeatherService
from utils.text_cleaner import TextCleaner
from voice.tts import RealtimePiperTTS


class JarvisRuntime:
    """Primary runtime orchestrator.

    Responsibilities:
    - route local intents to feature services
    - orchestrate Groq streaming for general requests
    - coordinate TTS and UI callbacks
    """

    FIRST_CHUNK_MIN_CHARS = 14
    FIRST_CHUNK_MAX_CHARS = 26
    EARLY_CHUNK_MIN_CHARS = 20
    EARLY_CHUNK_TARGET_CHARS = 34
    EARLY_CHUNK_MAX_CHARS = 36
    EARLY_CHUNK_MAX_WAIT_SECONDS = 0.22

    WEATHER_RE = re.compile(r"\b(weather|temperature|forecast)\b", re.IGNORECASE)
    NEWS_RE = re.compile(r"\b(news|headline|headlines|breaking)\b", re.IGNORECASE)
    GREETING_RE = re.compile(r"^\s*(hello|hi|hey|yo|good morning|good afternoon|good evening|good night)\b", re.IGNORECASE)
    WELLBEING_RE = re.compile(r"\b(how are you|how are you feeling|how's it going|how do you feel)\b", re.IGNORECASE)
    NAME_QUERY_RE = re.compile(r"\b(what(?:'s| is)? my name|do you know my name|who am i)\b", re.IGNORECASE)
    NAME_SET_RE = re.compile(r"\b(my name is|name is|call me)\b", re.IGNORECASE)
    CORRECTION_RE = re.compile(
        r"\b(that'?s wrong|that is wrong|incorrect|not correct|wrong answer|you are wrong|that's completely wrong|hallucinating|hallucination)\b",
        re.IGNORECASE,
    )
    SPEEDTEST_RE = re.compile(r"\b(speed\s*test|speedtest|internet speed|network speed)\b", re.IGNORECASE)
    PUBLIC_IP_RE = re.compile(r"\b(public ip|my ip|ip address|external ip|current ip|current ip address)\b", re.IGNORECASE)
    LOCATION_RE = re.compile(r"\b(where am i|my location|current location|location from ip|network location)\b", re.IGNORECASE)
    STATUS_RE = re.compile(
        r"\b(system status|device status|pc status|computer status|network status|status of (?:my )?(?:system|pc|computer|device)|how is (?:my )?(?:system|pc|computer|device))\b",
        re.IGNORECASE,
    )
    TEMPORAL_RE = re.compile(
        r"\b(current time|time now|what time|local time|current date|date today|today's date|what date|what day is it|current year|what year|current month|what month)\b",
        re.IGNORECASE,
    )
    UPDATE_RE = re.compile(r"\b(system update|software update|update status|version|patch|upgrade)\b", re.IGNORECASE)
    SEARCH_RE = re.compile(r"\b(search|internet|web|google|look up|lookup|find online)\b", re.IGNORECASE)
    SEARCH_POLICY_RE = re.compile(
        r"\b(check|use|verify)\b.*\b(internet|web|online)\b|\bknowledge cutoff\b",
        re.IGNORECASE,
    )
    ABUSE_RE = re.compile(r"\b(trash|useless|stupid|idiot|dumb|worst)\b", re.IGNORECASE)
    FACTUAL_RE = re.compile(
        r"\b(who won|what happened|latest|recent|facts?|history|record|ipl|season|champion|winner|news|current|prime minister|pm|president|chief minister|capital|population|replacement|replace|replaced|confirm|holiday)\b",
        re.IGNORECASE,
    )
    AMBIGUOUS_SEASON_RE = re.compile(r"^\s*(?:the\s+)?(?:\d{4}|20\d{2})\s+season\.?\s*$|^\s*season\s+\d{4}\.?\s*$", re.IGNORECASE)

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.from_env(".env")
        self.personality = PersonalityEngine()
        self.humor = HumorEngine()
        self.memory = MemoryStore(self.config.memory_store_path)
        self.text_cleaner = TextCleaner()

        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._on_mode_change: Callable[[str], None] | None = None
        self._on_text_delta: Callable[[str], None] | None = None
        self._on_api_activity: Callable[[bool], None] | None = None
        self._request_lock = threading.Lock()
        self._last_fact_query = ""
        self._last_fact_source = ""
        self._last_fact_handler: Callable[[str], str] | None = None
        self._last_assistant_reply = ""
        self._last_user_query = ""
        self._last_search_query = str(self.memory.get("last_search_query") or "").strip()
        self._last_speedtest_requested_at = float(self.memory.get("last_speedtest_requested_at") or 0.0)

        self.tts = RealtimePiperTTS(
            self.config,
            on_speaking_start=self._handle_tts_start,
            on_speaking_stop=self._handle_tts_stop,
        )

        self.network_service = NetworkService(self.config, self.personality)
        self.search_service = SearchService(self.config, self.personality)
        self.weather_service = WeatherService(self.config, self.network_service, self.personality, self.humor, self.memory)
        self.news_service = NewsService(self.config, self.personality, self.search_service)
        self._intent_router = self._build_intent_router()

    def _build_intent_router(self) -> IntentRouter:
        router = IntentRouter()
        router.register(
            name="correction",
            matcher=self._is_correction_request,
            handler=self._handle_correction,
            priority=5,
        )
        router.register(
            name="set_user_name",
            matcher=self._is_name_set_request,
            handler=self._handle_user_name_set,
            priority=8,
        )
        router.register(
            name="query_user_name",
            matcher=lambda text: bool(self.NAME_QUERY_RE.search(text)),
            handler=self._handle_user_name_query,
            priority=9,
        )
        router.register(
            name="greeting",
            matcher=self._is_pure_greeting,
            handler=self._handle_greeting,
            priority=10,
        )
        router.register(
            name="wellbeing",
            matcher=lambda text: bool(self.WELLBEING_RE.search(text)),
            handler=self._handle_wellbeing,
            priority=12,
        )
        router.register(
            name="search_policy",
            matcher=self._is_search_policy_feedback,
            handler=self._handle_search_policy_feedback,
            priority=13,
        )
        router.register(
            name="abuse_feedback",
            matcher=self._is_abuse_feedback,
            handler=self._handle_abuse_feedback,
            priority=14,
        )
        router.register(
            name="update_status",
            matcher=lambda text: bool(self.UPDATE_RE.search(text)),
            handler=self._handle_update_status,
            priority=20,
        )
        router.register(
            name="speedtest",
            matcher=lambda text: bool(self.SPEEDTEST_RE.search(text)) or self._is_speedtest_followup_query(text),
            handler=self._handle_speedtest_query,
            priority=30,
        )
        router.register(
            name="public_ip",
            matcher=lambda text: bool(self.PUBLIC_IP_RE.search(text)),
            handler=self._handle_public_ip,
            priority=40,
        )
        router.register(
            name="network_location",
            matcher=lambda text: bool(self.LOCATION_RE.search(text)),
            handler=self._handle_network_location,
            priority=50,
        )
        router.register(
            name="weather",
            matcher=lambda text: bool(self.WEATHER_RE.search(text)),
            handler=self._handle_weather,
            priority=60,
        )
        router.register(
            name="news",
            matcher=lambda text: bool(self.NEWS_RE.search(text)),
            handler=self._handle_news,
            priority=70,
        )
        router.register(
            name="internet_search",
            matcher=self._is_search_request,
            handler=self._handle_search,
            priority=75,
        )
        router.register(
            name="ambiguous_season",
            matcher=self._is_ambiguous_season_query,
            handler=self._handle_ambiguous_season_query,
            priority=76,
        )
        router.register(
            name="system_status",
            matcher=lambda text: "project status" not in text.lower() and bool(self.STATUS_RE.search(text)),
            handler=self._handle_system_status,
            priority=80,
        )
        router.register(
            name="temporal",
            matcher=lambda text: bool(self.TEMPORAL_RE.search(text)),
            handler=self._handle_temporal,
            priority=90,
        )
        return router

    def _is_name_set_request(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        if lowered.endswith("?"):
            return False
        return bool(self.NAME_SET_RE.search(lowered))

    def _is_pure_greeting(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered or not self.GREETING_RE.search(lowered):
            return False

        if self.WELLBEING_RE.search(lowered):
            return False

        if any(
            matcher.search(lowered)
            for matcher in (self.WEATHER_RE, self.NEWS_RE, self.SPEEDTEST_RE, self.PUBLIC_IP_RE, self.STATUS_RE)
        ):
            return False

        words = re.findall(r"\b\w+\b", lowered)
        return len(words) <= 8

    def _is_correction_request(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        if self.CORRECTION_RE.search(lowered):
            return True
        return lowered in {"wrong", "incorrect", "no", "nope"}

    def _is_ambiguous_season_query(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        if "ipl" in lowered or "premier league" in lowered:
            return False
        return bool(self.AMBIGUOUS_SEASON_RE.search(lowered))

    def _is_search_request(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False

        if self.SEARCH_RE.search(lowered):
            return True

        if re.search(r"\b(who won|what happened)\b", lowered) and self.FACTUAL_RE.search(lowered):
            return True

        return "latest news" in lowered

    def _is_abuse_feedback(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered or not self.ABUSE_RE.search(lowered):
            return False

        if any(
            matcher.search(lowered)
            for matcher in (
                self.SPEEDTEST_RE,
                self.PUBLIC_IP_RE,
                self.LOCATION_RE,
                self.WEATHER_RE,
                self.NEWS_RE,
                self.STATUS_RE,
                self.TEMPORAL_RE,
                self.UPDATE_RE,
            )
        ):
            return False

        if self._is_search_request(lowered) or self._is_factual_query(lowered):
            return False

        return True

    def _is_explicit_detail_request(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        return any(
            marker in lowered
            for marker in (
                "in detail",
                "detailed",
                "deep dive",
                "step by step",
                "comprehensive",
                "elaborate",
                "full explanation",
            )
        )

    def _is_conceptual_query(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        return bool(
            re.search(
                r"\b(how does|how do|explain|teach me|what is|define|difference between|semiconductor|physics|bandgap|paradox|immovable|unstoppable|mobile phone)\b",
                lowered,
            )
        )

    @staticmethod
    def _briefen_response(text: str) -> str:
        source = (text or "").strip()
        if not source:
            return ""

        single_line = re.sub(r"\s+", " ", source).strip()
        sentences = re.split(r"(?<=[.!?])\s+", single_line)
        if len([part for part in sentences if part.strip()]) <= 2 and len(single_line) <= 260 and source.count("\n") <= 3:
            return source

        kept = [part.strip() for part in sentences if part.strip()][:2]
        if not kept:
            kept = [single_line[:220].rstrip() + "..."]

        brief = " ".join(kept).strip()
        if not brief.endswith((".", "?", "!")):
            brief += "."

        if "want a deeper" not in brief.lower():
            brief += " Want a deeper breakdown?"
        return brief

    def _is_factual_query(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False

        if self._is_search_request(lowered) and (
            self.FACTUAL_RE.search(lowered)
            or re.search(r"\b(who|what|when|where|is there|can|does|did|will)\b", lowered)
        ):
            return True

        if re.search(r"\bipl\b", lowered) and re.search(r"\b20\d{2}\b", lowered):
            return True

        if re.search(r"\b(current|latest)\b", lowered) and re.search(
            r"\b(prime minister|president|chief minister|capital|population)\b",
            lowered,
        ):
            return True

        if re.search(r"\b(is|are)\b", lowered) and re.search(
            r"\b(current|prime minister|\bpm\b|president|chief minister|captain)\b",
            lowered,
        ):
            return True

        if re.search(r"\b(confirm|replacement|replace|replaced)\b", lowered) and re.search(
            r"\b(ipl|season|campaign|team|squad|player)\b",
            lowered,
        ):
            return True

        if "holiday" in lowered and any(token in lowered for token in ("today", "tomorrow", "date", "day", "is")):
            return True

        if self._last_search_query and re.search(r"\b(that season|that team|that winner|which team|that year)\b", lowered):
            return True

        patterns = [
            r"\bwho\b",
            r"\bwhen\b",
            r"\bwhere\b",
            r"\bwhat\b",
            r"\bwon\b",
            r"\bchampion\b",
            r"\bfacts?\b",
            r"\bhistory\b",
        ]
        return bool(self.FACTUAL_RE.search(lowered)) and any(re.search(pattern, lowered) for pattern in patterns)

    def _is_speedtest_followup_query(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if self._last_fact_source != "speedtest":
            return False

        if re.search(
            r"\b(holiday|prime minister|\bpm\b|president|ipl|season|weather|news|capital|population|who|what|when|where)\b",
            lowered,
        ):
            return False

        followup_markers = (
            "speed result",
            "speedtest result",
            "internet speed",
            "network speed",
            "results out",
            "results out now",
            "results now",
            "are the results",
            "download",
            "upload",
            "ping",
            "average speed",
            "just got",
            "that speed",
            "those speeds",
            "below average",
            "above average",
            "check speed",
            "run again",
        )
        return any(marker in lowered for marker in followup_markers)

    @staticmethod
    def _extract_ipl_year(query: str) -> str | None:
        match = re.search(r"\b(20\d{2})\b", query or "", flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1)

    @staticmethod
    def _normalize_query_typos(text: str) -> str:
        normalized = text or ""
        normalized = re.sub(r"\bibill\b", "IPL", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bipll\b", "IPL", normalized, flags=re.IGNORECASE)
        return normalized

    @staticmethod
    def _is_short_ipl_season_prompt(text: str) -> bool:
        lowered = re.sub(r"\s+", " ", (text or "").strip().lower())
        patterns = (
            r"^(?:the\s+)?ipl\s+20\d{2}\s+season$",
            r"^20\d{2}\s+ipl\s+season$",
            r"^(?:the\s+)?ipl\s+season\s+20\d{2}$",
        )
        return any(re.search(pattern, lowered) for pattern in patterns)

    @staticmethod
    def _is_non_winner_ipl_context(text: str) -> bool:
        return bool(
            re.search(
                r"\b(replacement|replace|replaced|confirm|campaign|squad|auction|captain|coach|retained|released|injury)\b",
                text or "",
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _is_generic_search_command(text: str) -> bool:
        lowered = re.sub(r"\s+", " ", (text or "").strip().lower())
        if not lowered:
            return False

        if re.fullmatch(
            r"(?:then\s+|now\s+|please\s+)*(?:search(?:\s+on\s+(?:the\s+)?)?(?:internet|web|online)|search|use\s+internet|check\s+internet)(?:\s+(?:pro|bro))?",
            lowered,
        ):
            return True

        return lowered in {"search", "search internet", "search on internet", "search on the internet"}

    def _extract_search_topic(self, text: str) -> str:
        cleaned = self.text_cleaner.clean(text).cleaned_text or text
        lowered_cleaned = cleaned.lower()

        if self._is_generic_search_command(cleaned):
            if self._last_fact_query:
                return self._last_fact_query
            if self._last_user_query and self._is_factual_query(self._last_user_query):
                return self._last_user_query
            return cleaned

        clauses = [part.strip(" .?!") for part in re.split(r"[?]", cleaned) if part.strip(" .?!")]
        if len(clauses) >= 2:
            for clause in reversed(clauses):
                lowered_clause = clause.lower()
                if (
                    "holiday" in lowered_clause
                    or bool(self.FACTUAL_RE.search(lowered_clause))
                    or bool(re.search(r"\b(who|what|when|where|is there|can|does|did|will)\b", lowered_clause))
                ):
                    return clause

        if re.match(r"^\s*(then\s+|now\s+|please\s+)*search\b", lowered_cleaned):
            explicit = re.search(
                r"^\s*(?:then\s+|now\s+|please\s+)*search(?:\s+on\s+(?:the\s+)?(?:internet|web|online)|\s+(?:internet|web|online))?\s+(.+)$",
                cleaned,
                flags=re.IGNORECASE,
            )
            if explicit:
                candidate = explicit.group(1).strip(" .?!")
                if candidate and candidate.lower() not in {"internet", "web", "online", "the internet", "pro", "bro"}:
                    return candidate

        prefixed = re.search(
            r"^\s*(?:i\s+said\s+)?check\s+on\s+(?:the\s+)?(?:internet|web|online)\s+(?:that\s+)?(.+)$",
            cleaned,
            flags=re.IGNORECASE,
        )
        if prefixed:
            candidate = prefixed.group(1).strip(" .?!")
            if candidate:
                return candidate

        return cleaned

    def _is_search_policy_feedback(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False

        if not self.SEARCH_POLICY_RE.search(lowered):
            return False

        if self._is_generic_search_command(lowered) or bool(re.match(r"^\s*(then\s+|now\s+|please\s+)*search\b", lowered)):
            return False

        if any(
            matcher.search(lowered)
            for matcher in (
                self.SPEEDTEST_RE,
                self.PUBLIC_IP_RE,
                self.LOCATION_RE,
                self.WEATHER_RE,
                self.NEWS_RE,
                self.STATUS_RE,
                self.TEMPORAL_RE,
                self.UPDATE_RE,
            )
        ):
            return False

        if re.search(r"\b(you should|you must|always|why not)\b", lowered):
            return "?" not in lowered

        if self._is_search_request(lowered) and ("?" in lowered or self.FACTUAL_RE.search(lowered)):
            return False

        return True

    def _build_effective_search_query(self, text: str) -> str:
        normalized_text = self._normalize_query_typos(text)
        cleaned = self.text_cleaner.clean(normalized_text).cleaned_text or normalized_text
        lowered = cleaned.lower()

        if re.search(r"\bipl\b", lowered):
            year = self._extract_ipl_year(lowered)
            winner_intent = bool(re.search(r"\b(who won|winner|champion|which team won|won)\b", lowered))
            short_season_prompt = self._is_short_ipl_season_prompt(lowered)
            if year and (winner_intent or short_season_prompt) and not self._is_non_winner_ipl_context(lowered):
                return f"who won IPL {year} season"

        if self._last_search_query and re.search(r"\b(that season|that team|that winner|that year|which team)\b", lowered):
            if re.search(r"\b(who won|winner|won|which team)\b", lowered):
                return self._last_search_query
            return f"{cleaned} about {self._last_search_query}"

        if re.search(r"\bwon that season\b", lowered) and self._last_search_query:
            return self._last_search_query

        if re.search(r"\bipl\s+20\d{2}\s+season\b", lowered):
            year = self._extract_ipl_year(lowered)
            if year:
                return f"who won IPL {year} season"

        return cleaned

    @staticmethod
    def _speedtest_benchmark(country: str | None) -> tuple[float, float, str]:
        normalized = (country or "").strip().lower()
        if normalized == "india":
            return 40.0, 100.0, "India"
        if normalized in {"united states", "usa", "us"}:
            return 100.0, 200.0, "United States"
        return 50.0, 150.0, (country or "your region")

    def _resolve_user_country(self) -> str | None:
        try:
            location = self.network_service.get_location_from_ip()
        except Exception:
            location = None

        if location and location.country:
            self.memory.set("user_country", location.country)
            return location.country

        remembered = str(self.memory.get("user_country") or "").strip()
        return remembered or None

    def _speed_query_mode(self, text: str) -> str | None:
        lowered = (text or "").lower()

        if any(word in lowered for word in ("run speed", "run speedtest", "start speed", "new speed test", "run internet speed")):
            return None

        if any(word in lowered for word in ("average", "below", "above", "fast", "slow", "good", "better", "improve", "upgrade")):
            return "assessment"
        if any(word in lowered for word in ("result", "results", "status", "report", "latest", "show", "out now", "done")):
            return "result"
        return None

    def _speed_snapshot_is_fresh(self, snapshot: dict[str, float]) -> bool:
        snapshot_ts = float(snapshot.get("timestamp", 0.0))
        if snapshot_ts <= 0:
            return False
        if self._last_speedtest_requested_at <= 0:
            return True
        return snapshot_ts >= self._last_speedtest_requested_at

    def _get_memory_speedtest(self) -> dict[str, float] | None:
        payload = self.memory.get("last_speedtest")
        if not isinstance(payload, dict):
            return None

        required = ("download_mbps", "upload_mbps", "ping_ms")
        if not all(key in payload for key in required):
            return None

        try:
            return {
                "download_mbps": float(payload["download_mbps"]),
                "upload_mbps": float(payload["upload_mbps"]),
                "ping_ms": float(payload["ping_ms"]),
                "timestamp": float(payload.get("timestamp", 0.0)),
            }
        except Exception:
            return None

    def _build_speedtest_result_from_snapshot(self, snapshot: dict[str, float], *, country: str | None) -> str:
        download = float(snapshot.get("download_mbps", 0.0))
        upload = float(snapshot.get("upload_mbps", 0.0))
        ping = float(snapshot.get("ping_ms", 0.0))
        avg_low, avg_high, country_label = self._speedtest_benchmark(country)

        if download < avg_low:
            verdict = f"This is below common {country_label} household ranges ({avg_low:.0f}-{avg_high:.0f} Mbps)."
        elif download <= avg_high:
            verdict = f"This is within common {country_label} household ranges ({avg_low:.0f}-{avg_high:.0f} Mbps)."
        else:
            verdict = f"This is above common {country_label} household ranges ({avg_low:.0f}-{avg_high:.0f} Mbps)."

        return (
            f"Download: {download:.2f} Mbps\n"
            f"Upload: {upload:.2f} Mbps\n"
            f"Ping: {ping:.1f} ms\n\n"
            f"{verdict}"
        )

    def _build_speedtest_assessment_from_snapshot(self, snapshot: dict[str, float], *, country: str | None) -> str:
        download = float(snapshot.get("download_mbps", 0.0))
        avg_low, avg_high, country_label = self._speedtest_benchmark(country)

        if download < avg_low:
            note = "below typical"
            guidance = (
                "You can improve this with Ethernet testing, router placement tuning, "
                "and an ISP plan check."
            )
        elif download <= avg_high:
            note = "within typical"
            guidance = "This should handle regular work and streaming reliably."
        else:
            note = "above typical"
            guidance = "This is strong for most high-bandwidth home workloads."

        return (
            f"Your measured download speed is {download:.1f} Mbps, which is {note} "
            f"for common {country_label} ranges ({avg_low:.0f}-{avg_high:.0f} Mbps). {guidance}"
        )

    def _remember_fact(self, *, source: str, query: str, handler: Callable[[str], str]) -> None:
        self._last_fact_source = source
        self._last_fact_query = query
        self._last_fact_handler = handler

    def _build_profile_context(self) -> str | None:
        user_name = (self.memory.get("user_name") or "").strip()
        if not user_name:
            return None
        return (
            f"Known user profile: user_name={user_name}. "
            "Use this naturally and accurately in relevant replies."
        )

    def _handle_greeting(self, _text: str) -> str:
        user_name = (self.memory.get("user_name") or "").strip() or None
        greeting = self.personality.greeting(name=user_name)
        return f"{greeting} What can I help you with?"

    def _handle_wellbeing(self, _text: str) -> str:
        return "Doing well and fully focused. What should we tackle next?"

    def _handle_search_policy_feedback(self, _text: str) -> str:
        self.memory.set("prefer_web_for_facts", True)
        return "Understood. I will verify factual and time-sensitive questions with live web search first."

    def _handle_abuse_feedback(self, _text: str) -> str:
        return "I hear you. Ask the exact question and I will verify it with live sources."

    def _handle_ambiguous_season_query(self, _text: str) -> str:
        return "Please specify the event for that season, for example IPL 2025 season."

    def _handle_user_name_set(self, text: str) -> str:
        name = extract_user_name(text)
        if not name:
            return "I caught that you wanted to set your name, but I missed the exact wording."

        self.memory.set("user_name", name)
        return f"Noted. I will call you {name}."

    def _handle_user_name_query(self, _text: str) -> str:
        name = (self.memory.get("user_name") or "").strip()
        if not name:
            return "You have not shared your name with me yet."
        return f"Your name is {name}."

    def _handle_correction(self, text: str) -> str:
        if self._last_fact_source == "speedtest":
            country = self._resolve_user_country()
            memory_snapshot = self._get_memory_speedtest()
            if memory_snapshot:
                if self._speed_query_mode(self._last_user_query) == "assessment":
                    corrected = self._build_speedtest_assessment_from_snapshot(memory_snapshot, country=country)
                else:
                    corrected = self._build_speedtest_result_from_snapshot(memory_snapshot, country=country)
                return self.personality.correction(corrected, confidence="high", user_text=text)

            error = self.network_service.get_last_speedtest_error() or str(self.memory.get("last_speedtest_error") or "")
            if error == "missing_speedtest_module" or "No module named 'speedtest'" in error:
                corrected = "Speed test couldn't run because required module is missing."
                return self.personality.correction(corrected, confidence="high", user_text=text)

            corrected = "I couldn't confirm your speed yet. Let's run the test again."
            return self.personality.correction(corrected, confidence="medium", user_text=text)

        if self._last_fact_handler and self._last_fact_query:
            corrected = self._last_fact_handler(self._last_fact_query)
            corrected = re.sub(r"\s*Confidence:\s*(high|medium|low)\.?$", "", corrected, flags=re.IGNORECASE).strip()
            lowered = corrected.lower()
            confidence = "high"
            if "could not" in lowered or "unavailable" in lowered or "failed" in lowered:
                confidence = "medium"
            return self.personality.correction(corrected, confidence=confidence, user_text=text)

        if self._last_user_query and self._is_factual_query(self._last_user_query):
            corrected = self.search_service.summarize_search(
                self._last_user_query,
                max_results=4,
                user_text=text,
            )
            corrected = re.sub(r"\s*Confidence:\s*(high|medium|low)\.?$", "", corrected, flags=re.IGNORECASE).strip()
            confidence = "high"
            if "could not fetch live search results" in corrected.lower():
                confidence = "medium"
            return self.personality.correction(corrected, confidence=confidence, user_text=text)

        fallback = (
            "I rechecked the local sources available in this build, "
            "but I cannot verify a stronger correction for the last answer."
        )
        return self.personality.correction(fallback, confidence="low", user_text=text)

    def _handle_update_status(self, text: str) -> str:
        self._remember_fact(source="update", query=text, handler=lambda _q: self.network_service.get_update_status())
        return self.network_service.get_update_status()

    def _handle_speedtest_query(self, text: str) -> str:
        self._remember_fact(source="speedtest", query=text, handler=self.network_service.handle_speedtest_query)

        country = self._resolve_user_country()
        mode = self._speed_query_mode(text)
        memory_snapshot = self._get_memory_speedtest()

        if mode and memory_snapshot and not self.network_service.is_speedtest_running() and self._speed_snapshot_is_fresh(memory_snapshot):
            if mode == "assessment":
                return self._build_speedtest_assessment_from_snapshot(memory_snapshot, country=country)
            return self._build_speedtest_result_from_snapshot(memory_snapshot, country=country)

        if mode is None:
            self._last_speedtest_requested_at = time.time()
            self.memory.set("last_speedtest_requested_at", self._last_speedtest_requested_at)

        response = self.network_service.handle_speedtest_query(text)

        snapshot = self.network_service.get_last_speedtest_snapshot()
        if snapshot:
            self.memory.set("last_speedtest", snapshot)
            self.memory.set("last_speedtest_error", "")
        else:
            last_error = self.network_service.get_last_speedtest_error()
            if last_error:
                self.memory.set("last_speedtest_error", last_error)

        return response

    def _handle_multi_office_query(self, text: str) -> str | None:
        lowered = (text or "").strip().lower()
        if "president" not in lowered:
            return None

        has_india = "india" in lowered
        has_us = "united states" in lowered or bool(re.search(r"\busa\b|\bus\b", lowered))
        if not (has_india and has_us):
            return None

        india_query = "who is the current President of India"
        us_query = "who is the current President of United States"

        india_results = self.search_service.search_web(india_query, max_results=5)
        us_results = self.search_service.search_web(us_query, max_results=5)

        if not india_results and not us_results:
            return self.personality.finalize(
                "I could not fetch live search results right now. Please verify SERPER_API_KEY in .env or try again shortly.",
                user_text=text,
            )

        india_answer, india_conf = self.search_service.extract_consensus_answer(india_results, india_query)
        us_answer, us_conf = self.search_service.extract_consensus_answer(us_results, us_query)

        confidence_rank = {"low": 1, "medium": 2, "high": 3}
        min_conf = min(confidence_rank.get(india_conf, 2), confidence_rank.get(us_conf, 2))
        combined_conf = {1: "low", 2: "medium", 3: "high"}[min_conf]

        message = f"India: {india_answer} United States: {us_answer} Confidence: {combined_conf}."
        return self.personality.finalize(message, user_text=text)

    def _handle_public_ip(self, text: str) -> str:
        self._remember_fact(source="public_ip", query=text, handler=lambda _q: self.network_service.describe_public_ip())
        return self.network_service.describe_public_ip()

    def _handle_network_location(self, text: str) -> str:
        self._remember_fact(source="network_location", query=text, handler=lambda _q: self.network_service.describe_ip_location())
        return self.network_service.describe_ip_location()

    def _handle_weather(self, text: str) -> str:
        self._remember_fact(source="weather", query=text, handler=self.weather_service.get_weather_brief)
        return self.weather_service.get_weather_brief(text)

    def _handle_news(self, text: str) -> str:
        self._remember_fact(source="news", query=text, handler=self.news_service.get_news_brief)
        return self.news_service.get_news_brief(text)

    def _handle_search(self, text: str) -> str:
        topic = self._extract_search_topic(text)
        effective_query = self._build_effective_search_query(topic)
        self._last_search_query = effective_query
        self.memory.set("last_search_query", effective_query)

        self._remember_fact(
            source="internet_search",
            query=effective_query,
            handler=lambda q: self.search_service.summarize_search(q, max_results=5, user_text=q),
        )
        return self.search_service.summarize_search(effective_query, max_results=5, user_text=text)

    def _handle_system_status(self, text: str) -> str:
        self._remember_fact(source="system_status", query=text, handler=lambda _q: self.network_service.get_system_status_snapshot())
        return self.network_service.get_system_status_snapshot()

    def _handle_temporal(self, text: str) -> str:
        self._remember_fact(source="temporal", query=text, handler=lambda _q: self.network_service.get_temporal_snapshot())
        return self.network_service.get_temporal_snapshot()

    def set_event_callbacks(
        self,
        *,
        on_mode_change: Callable[[str], None] | None = None,
        on_text_delta: Callable[[str], None] | None = None,
        on_api_activity: Callable[[bool], None] | None = None,
    ) -> None:
        self._on_mode_change = on_mode_change
        self._on_text_delta = on_text_delta
        self._on_api_activity = on_api_activity

    def _emit_mode(self, mode: str) -> None:
        if self._on_mode_change:
            try:
                self._on_mode_change(mode)
            except Exception:
                pass

    def _emit_text_delta(self, delta: str) -> None:
        if self._on_text_delta:
            try:
                self._on_text_delta(delta)
            except Exception:
                pass

    def _emit_api_activity(self, active: bool) -> None:
        if self._on_api_activity:
            try:
                self._on_api_activity(active)
            except Exception:
                pass

    def _handle_tts_start(self) -> None:
        self._emit_mode("speaking")

    def _handle_tts_stop(self) -> None:
        self._emit_mode("listening")

    def _trim_history(self) -> None:
        if len(self.messages) > (self.config.max_context_messages + 1):
            self.messages = [self.messages[0]] + self.messages[-self.config.max_context_messages:]

    def _should_flush_speech_buffer(self, buffer: str) -> bool:
        stripped = buffer.strip()
        if not stripped:
            return False

        flush_chars = max(24, min(self.config.tts_chunk_chars, self.EARLY_CHUNK_MAX_CHARS))

        if stripped[-1] in ".?!":
            return True

        if len(stripped) >= flush_chars:
            return True

        return False

    def _next_speech_chunk(self, buffer: str, *, final: bool = False) -> tuple[str, str]:
        if not buffer:
            return "", ""

        if final:
            return buffer.strip(), ""

        if not self._should_flush_speech_buffer(buffer):
            return "", buffer

        boundaries = [". ", "? ", "! ", ", ", "; ", ": ", "\n", " "]
        cutoff = -1
        for marker in boundaries:
            idx = buffer.rfind(marker)
            if idx > cutoff:
                cutoff = idx + len(marker)

        if cutoff <= 0:
            cutoff = min(len(buffer), self.config.tts_chunk_chars)

        chunk = buffer[:cutoff].strip()
        rest = buffer[cutoff:]

        if len(chunk) < 8:
            return "", buffer

        return chunk, rest

    def _early_speech_chunk(self, buffer: str) -> tuple[str, str]:
        stripped = buffer.strip()
        if len(stripped) < self.EARLY_CHUNK_MIN_CHARS:
            return "", buffer

        target = max(self.EARLY_CHUNK_TARGET_CHARS, min(self.config.tts_chunk_chars, self.EARLY_CHUNK_MAX_CHARS))
        target = min(target, len(buffer))
        cutoff = target

        while cutoff > 0 and buffer[cutoff - 1] not in (" ", "\n", ",", ".", "?", "!", ";", ":"):
            cutoff -= 1

        if cutoff <= 0:
            cutoff = target

        chunk = buffer[:cutoff].strip()
        rest = buffer[cutoff:]
        if len(chunk) < self.EARLY_CHUNK_MIN_CHARS:
            return "", buffer

        return chunk, rest

    def _first_speech_chunk(self, buffer: str) -> tuple[str, str]:
        stripped = buffer.strip()
        if len(stripped) < self.FIRST_CHUNK_MIN_CHARS:
            return "", buffer

        target = min(max(self.FIRST_CHUNK_MIN_CHARS, self.FIRST_CHUNK_MAX_CHARS), len(buffer))
        cutoff = target

        while cutoff > 0 and buffer[cutoff - 1] not in (" ", "\n", ",", ".", "?", "!", ";", ":"):
            cutoff -= 1

        if cutoff <= 0:
            return "", buffer

        chunk = buffer[:cutoff].strip()
        rest = buffer[cutoff:]
        if len(chunk) < self.FIRST_CHUNK_MIN_CHARS:
            return "", buffer

        return chunk, rest

    def _respond_local(
        self,
        user_text: str,
        response_text: str,
        *,
        persist_user: bool,
        stream_to_stdout: bool,
    ) -> str:
        finalized = self.personality.finalize(response_text, user_text=user_text)

        if persist_user:
            self.messages.append({"role": "user", "content": user_text})
            self._trim_history()

        turn_id = self.tts.interrupt()
        self._emit_mode("processing")
        self._emit_api_activity(False)
        self._emit_text_delta(finalized)
        self.tts.enqueue_text(finalized, turn_id)
        self.tts.wait_for_turn_completion(
            turn_id,
            timeout_s=self.config.tts_turn_completion_timeout_seconds,
        )

        if stream_to_stdout:
            print(f"{WHITE}JARVIS:{RESET} {finalized}")

        if persist_user:
            self.messages.append({"role": "assistant", "content": finalized})
            self._trim_history()

        self._last_assistant_reply = finalized
        return finalized

    def ask_groq(
        self,
        text: str,
        *,
        persist_user: bool = True,
        stream_to_stdout: bool = True,
    ) -> str:
        with self._request_lock:
            return self._ask_groq_locked(
                text,
                persist_user=persist_user,
                stream_to_stdout=stream_to_stdout,
            )

    def _ask_groq_locked(
        self,
        text: str,
        *,
        persist_user: bool = True,
        stream_to_stdout: bool = True,
    ) -> str:
        cleaned = self.text_cleaner.clean(text)
        normalized_text = cleaned.cleaned_text or text

        # Support "weather again" style turns by reusing remembered city context.
        if cleaned.had_again and self.WEATHER_RE.search(normalized_text):
            has_city = bool(re.search(r"\b(?:in|at|for)\s+[a-zA-Z]", normalized_text, flags=re.IGNORECASE))
            if not has_city:
                last_city = str(self.memory.get("last_city") or "").strip()
                if last_city:
                    normalized_text = f"weather in {last_city}"

        if not self._is_correction_request(normalized_text):
            self._last_user_query = normalized_text

        local_result = self._intent_router.dispatch_result(normalized_text)
        if local_result:
            return self._respond_local(
                text,
                local_result.response,
                persist_user=persist_user,
                stream_to_stdout=stream_to_stdout,
            )

        multi_office_response = self._handle_multi_office_query(normalized_text)
        if multi_office_response:
            self._remember_fact(
                source="factual_search_fallback",
                query=normalized_text,
                handler=lambda q: self.search_service.summarize_search(q, max_results=5, user_text=q),
            )
            return self._respond_local(
                text,
                multi_office_response,
                persist_user=persist_user,
                stream_to_stdout=stream_to_stdout,
            )

        if re.search(r"\bipl\b", normalized_text, flags=re.IGNORECASE) and re.search(r"\b20\d{2}\b", normalized_text):
            search_query = self._build_effective_search_query(normalized_text)
            search_response = self.search_service.summarize_search(
                search_query,
                max_results=5,
                user_text=text,
            )
            self._last_search_query = search_query
            self.memory.set("last_search_query", search_query)
            self._remember_fact(
                source="internet_search",
                query=search_query,
                handler=lambda q: self.search_service.summarize_search(q, max_results=5, user_text=q),
            )
            return self._respond_local(
                text,
                search_response,
                persist_user=persist_user,
                stream_to_stdout=stream_to_stdout,
            )

        if self._is_factual_query(normalized_text):
            effective_query = self._build_effective_search_query(normalized_text)
            search_response = self.search_service.summarize_search(
                effective_query,
                max_results=5,
                user_text=text,
            )
            self._last_search_query = effective_query
            self.memory.set("last_search_query", effective_query)
            self._remember_fact(
                source="factual_search_fallback",
                query=effective_query,
                handler=lambda q: self.search_service.summarize_search(q, max_results=5, user_text=q),
            )
            return self._respond_local(
                text,
                search_response,
                persist_user=persist_user,
                stream_to_stdout=stream_to_stdout,
            )

        if persist_user:
            self.messages.append({"role": "user", "content": normalized_text})
            self._trim_history()
            outbound_messages = list(self.messages)
        else:
            outbound_messages = self.messages + [{"role": "user", "content": normalized_text}]

        profile_context = self._build_profile_context()
        if profile_context and outbound_messages and outbound_messages[-1].get("role") == "user":
            outbound_messages = outbound_messages[:-1] + [{"role": "system", "content": profile_context}] + [outbound_messages[-1]]

        turn_id = self.tts.interrupt()
        self._emit_mode("processing")
        self._emit_api_activity(True)

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.groq_model,
                "messages": outbound_messages,
                "temperature": 0.3,
                "stream": True,
            },
            stream=True,
            timeout=60,
        )
        response.raise_for_status()

        full_text = ""
        speak_buffer = ""
        first_voice_chunk = True
        queued_any_speech = False
        last_chunk_queued_at = time.perf_counter()

        if stream_to_stdout:
            print(f"{WHITE}JARVIS:{RESET} ", end="", flush=True)

        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                if not line.startswith("data: "):
                    continue

                chunk = line[6:]
                if chunk == "[DONE]":
                    break

                try:
                    data = json.loads(chunk)
                    delta = data["choices"][0].get("delta", {}).get("content")
                except Exception:
                    continue

                if not delta:
                    continue

                if stream_to_stdout:
                    print(delta, end="", flush=True)

                self._emit_text_delta(delta)
                full_text += delta
                speak_buffer += delta

                if first_voice_chunk:
                    first_chunk, speak_buffer = self._first_speech_chunk(speak_buffer)
                    if first_chunk:
                        if self.config.tts_first_chunk_delay > 0:
                            time.sleep(self.config.tts_first_chunk_delay)
                        first_voice_chunk = False
                        queued_any_speech = True
                        self.tts.enqueue_text(first_chunk, turn_id)
                        last_chunk_queued_at = time.perf_counter()

                while True:
                    chunk_to_speak, speak_buffer = self._next_speech_chunk(speak_buffer, final=False)
                    if not chunk_to_speak:
                        break

                    if first_voice_chunk and self.config.tts_first_chunk_delay > 0:
                        time.sleep(self.config.tts_first_chunk_delay)
                    first_voice_chunk = False
                    queued_any_speech = True
                    self.tts.enqueue_text(chunk_to_speak, turn_id)
                    last_chunk_queued_at = time.perf_counter()

                if speak_buffer.strip() and (time.perf_counter() - last_chunk_queued_at) >= self.EARLY_CHUNK_MAX_WAIT_SECONDS:
                    early_chunk, speak_buffer = self._early_speech_chunk(speak_buffer)
                    if early_chunk:
                        if first_voice_chunk and self.config.tts_first_chunk_delay > 0:
                            time.sleep(self.config.tts_first_chunk_delay)
                        first_voice_chunk = False
                        queued_any_speech = True
                        self.tts.enqueue_text(early_chunk, turn_id)
                        last_chunk_queued_at = time.perf_counter()
        finally:
            self._emit_api_activity(False)

        if speak_buffer.strip():
            if first_voice_chunk and self.config.tts_first_chunk_delay > 0:
                time.sleep(self.config.tts_first_chunk_delay)
            tail_chunk, _ = self._next_speech_chunk(speak_buffer, final=True)
            if tail_chunk:
                queued_any_speech = True
                self.tts.enqueue_text(tail_chunk, turn_id)

        raw_text = full_text.strip().strip('"')
        if not full_text.strip():
            raw_text = "I did not receive a valid response. Please try again."
            full_text = raw_text
            if stream_to_stdout:
                print(raw_text, end="", flush=True)
            self.tts.enqueue_text(raw_text, turn_id)
            queued_any_speech = True

        if stream_to_stdout:
            print()

        if self._is_conceptual_query(normalized_text) and not self._is_explicit_detail_request(normalized_text):
            raw_text = self._briefen_response(raw_text)

        finalized = self.personality.finalize(raw_text, user_text=text)

        if persist_user:
            self.messages.append({"role": "assistant", "content": finalized})
            self._trim_history()

        if queued_any_speech:
            self.tts.wait_for_turn_completion(
                turn_id,
                timeout_s=self.config.tts_turn_completion_timeout_seconds,
            )
        else:
            self._emit_mode("listening")

        self._last_assistant_reply = finalized
        return finalized

    def greet(self, *, stream_to_stdout: bool = True) -> str:
        user_name = (self.memory.get("user_name") or "").strip() or None
        greeting = self.personality.greeting(name=user_name, now=datetime.datetime.now())
        greeting = f"{greeting} Ready when you are."
        return self._respond_local(
            user_text="",
            response_text=greeting,
            persist_user=False,
            stream_to_stdout=stream_to_stdout,
        )

    def close(self) -> None:
        self.network_service.close()
        self.tts.close()
