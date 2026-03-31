from __future__ import annotations

import datetime
import json
import logging
import re
import threading
import time
from typing import Callable

import requests

from agent.agent_loop import AgentLoop
from agent.tool_registry import build_default_tool_registry
from core.humor import HumorEngine
from core.personality import PersonalityEngine
from core.settings import AppConfig, RESET, SYSTEM_PROMPT, WHITE
from memory.store import MemoryStore, extract_user_name
from services.intent_router import IntentRouter
from services.network_service import NetworkService
from services.search_service import SearchService
from services.weather_service import WeatherService
from utils.text_cleaner import TextCleaner
from voice.tts import RealtimePiperTTS


logger = logging.getLogger(__name__)


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
    WELLBEING_RE = re.compile(r"\b(how are you|how are you feeling|how's it going|how do you feel|how r u|hru|how ru)\b", re.IGNORECASE)
    IDENTITY_QUERY_RE = re.compile(
        r"\b(who are you|what are you|what(?:'s| is) your name|are you human)\b",
        re.IGNORECASE,
    )
    NAME_QUERY_RE = re.compile(r"\b(what(?:'s| is)? my name|do you know my name|who am i)\b", re.IGNORECASE)
    NAME_SET_RE = re.compile(r"\b(my name is|name is|call me)\b", re.IGNORECASE)
    CORRECTION_RE = re.compile(
        r"\b(that'?s wrong|that is wrong|incorrect|not correct|wrong answer|you are wrong|that's completely wrong|hallucinating|hallucination)\b",
        re.IGNORECASE,
    )
    SPEEDTEST_RE = re.compile(r"\b(speed\s*test|speedtest|internet speed|network speed)\b", re.IGNORECASE)
    CONNECTIVITY_RE = re.compile(
        r"\b(internet connectivity|network connectivity|connectivity status|am i online|online status|check connectivity|check internet connectivity|check network connectivity)\b",
        re.IGNORECASE,
    )
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
    HELP_RE = re.compile(
        r"^\s*(help|help me|commands|list commands|list available commands|available commands|show commands)\s*$",
        re.IGNORECASE,
    )
    CAPABILITIES_RE = re.compile(
        r"\b(what can you do|your capabilities|capabilities|what do you do|how can you help)\b",
        re.IGNORECASE,
    )
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
    LOCATION_DECLARE_RE = re.compile(
        r"\b(?:i am|i'm|im|my location is|currently in|i live in)\s+([a-zA-Z][a-zA-Z\s\-]{1,80})",
        re.IGNORECASE,
    )
    DOCUMENT_RE = re.compile(
        r"\b(analyze|summarize|read|extract|parse|process|review|upload|select|compare)\b.*\b(document|documents|doc|docs|pdf|pdfs|docx|file|files|image|images|scan)\b"
        r"|\b(open|load)\b.*\b(document|documents|doc|docs|pdf|pdfs|docx|image|images|scan)\b"
        r"|\b(document|pdf|docx)\b",
        re.IGNORECASE,
    )
    DOCUMENT_PICKER_RE = re.compile(
        r"\b(open|show|launch|start)\b.*\b(file\s*picker|document\s*selector|document\s*picker)\b"
        r"|\b(select|choose|pick|upload)\b.*\b(document|pdf|docx|doc|image|scan|file)\b",
        re.IGNORECASE,
    )
    FILE_MANAGER_RE = re.compile(
        r"\b(file\s*explorer|file\s*manager|windows\s*explorer|explorer)\b",
        re.IGNORECASE,
    )
    DOCUMENT_COMPARE_RE = re.compile(
        r"\b(compare|comparison|versus|\bvs\b|difference|differences)\b.*\b(document|documents|doc|docs|pdf|pdfs|docx|file|files)\b"
        r"|\bcompare\s+(?:the\s+)?(?:\d+|two|three|four|five)\s+(?:documents?|files?|docs?|pdfs?)\b"
        r"|\bcompare\s+these\b",
        re.IGNORECASE,
    )
    DOCUMENT_QA_HINT_RE = re.compile(
        r"\b(pricing|price|cost|risk|risks|plan|plans|feature|features|entity|entities|key point|key points|find all|what does this|in this document|from this file)\b",
        re.IGNORECASE,
    )

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
        self._session_location = ""
        self._api_active = False
        self._cancel_event = threading.Event()
        self._stream_response_lock = threading.Lock()
        self._active_stream_response: requests.Response | None = None

        self.tts = RealtimePiperTTS(
            self.config,
            on_speaking_start=self._handle_tts_start,
            on_speaking_stop=self._handle_tts_stop,
        )

        self.network_service = NetworkService(self.config, self.personality)
        self.search_service = SearchService(self.config, self.personality)
        self.weather_service = WeatherService(self.config, self.network_service, self.personality, self.humor, self.memory)

        # Document Intelligence Service (optional — graceful fallback if deps not installed)
        self.document_service = self._init_document_service()

        self.tool_registry = build_default_tool_registry(
            network_service=self.network_service,
            weather_service=self.weather_service,
            search_service=self.search_service,
            document_service=self.document_service,
            memory_store=self.memory,
            get_session_location=self._get_session_location,
            set_session_location=self._set_session_location,
        )
        self.agent_loop = AgentLoop.from_registry(
            config=self.config,
            tool_registry=self.tool_registry,
            get_session_location=self._get_session_location,
        )
        self._intent_router = self._build_intent_router()

    def _get_session_location(self) -> str | None:
        value = " ".join((self._session_location or "").strip().split())
        return value or None

    def _set_session_location(self, location: str) -> None:
        cleaned = re.sub(r"\s+", " ", (location or "").strip())
        cleaned = cleaned.strip(" .,!?;:")
        if not cleaned:
            return
        self._session_location = cleaned
        self.memory.set("last_city", cleaned)

    def _extract_declared_location(self, text: str) -> str:
        match = self.LOCATION_DECLARE_RE.search(text or "")
        if not match:
            return ""
        candidate = re.split(
            r"\b(?:and|but|so|please|weather|forecast|temperature|check)\b",
            match.group(1),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        candidate = re.sub(r"\s+", " ", candidate).strip(" .,!?;:")
        if candidate.lower().startswith("in "):
            candidate = candidate[3:].strip(" .,!?;:")
        return candidate

    def _capture_session_location(self, user_text: str) -> None:
        declared = self._extract_declared_location(user_text)
        if declared:
            self._set_session_location(declared)

    def _init_document_service(self) -> object | None:
        """Lazily initialize DocumentService with graceful fallback."""
        try:
            from services.document.document_service import DocumentService
            return DocumentService(self.config)
        except ImportError as exc:
            logger.info("Document service unavailable due to missing dependency: %s", exc)
            return None
        except Exception as exc:
            logger.exception("Document service initialization failed: %s", exc)
            return None

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
            name="set_session_location",
            matcher=self._is_location_declaration_only,
            handler=self._handle_location_declaration,
            priority=11,
        )
        router.register(
            name="wellbeing",
            matcher=self._is_wellbeing_request,
            handler=self._handle_wellbeing,
            priority=12,
        )
        router.register(
            name="capabilities",
            matcher=lambda text: bool(self.CAPABILITIES_RE.search(text or "")),
            handler=self._handle_capabilities,
            priority=13,
        )
        router.register(
            name="help",
            matcher=lambda text: bool(self.HELP_RE.search(text or "")),
            handler=self._handle_help,
            priority=14,
        )
        router.register(
            name="search_policy",
            matcher=self._is_search_policy_feedback,
            handler=self._handle_search_policy_feedback,
            priority=15,
        )
        router.register(
            name="abuse_feedback",
            matcher=self._is_abuse_feedback,
            handler=self._handle_abuse_feedback,
            priority=16,
        )
        router.register(
            name="ambiguous_season",
            matcher=self._is_ambiguous_season_query,
            handler=self._handle_ambiguous_season_query,
            priority=17,
        )
        router.register(
            name="speedtest",
            matcher=self._is_speedtest_request,
            handler=self._handle_speedtest_query,
            priority=18,
        )
        router.register(
            name="connectivity",
            matcher=lambda text: bool(self.CONNECTIVITY_RE.search(text or "")),
            handler=self._handle_connectivity,
            priority=19,
        )
        router.register(
            name="public_ip",
            matcher=lambda text: bool(self.PUBLIC_IP_RE.search(text or "")),
            handler=self._handle_public_ip,
            priority=20,
        )
        router.register(
            name="network_location",
            matcher=lambda text: bool(self.LOCATION_RE.search(text or "")) and not bool(self.PUBLIC_IP_RE.search(text or "")),
            handler=self._handle_network_location,
            priority=21,
        )
        router.register(
            name="weather",
            matcher=lambda text: bool(self.WEATHER_RE.search(text or "")),
            handler=self._handle_weather,
            priority=22,
        )
        router.register(
            name="system_status",
            matcher=lambda text: bool(self.STATUS_RE.search(text or "")),
            handler=self._handle_system_status,
            priority=23,
        )
        router.register(
            name="temporal",
            matcher=lambda text: bool(self.TEMPORAL_RE.search(text or "")),
            handler=self._handle_temporal,
            priority=24,
        )
        router.register(
            name="update_status",
            matcher=lambda text: bool(self.UPDATE_RE.search(text or "")),
            handler=self._handle_update_status,
            priority=25,
        )
        if self.document_service is not None:
            router.register(
                name="document_qa",
                matcher=self._is_document_question_request,
                handler=self._handle_document_question,
                priority=26,
            )
            router.register(
                name="document",
                matcher=self._is_document_request,
                handler=self._handle_document,
                priority=27,
            )
        router.register(
            name="search_factual",
            matcher=self._is_search_or_factual_request,
            handler=self._handle_search,
            priority=30,
        )
        return router

    def _is_name_set_request(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        if lowered.endswith("?"):
            return False
        return bool(self.NAME_SET_RE.search(lowered))

    def _is_wellbeing_request(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False

        normalized = re.sub(r"[^a-z0-9\s']", " ", lowered)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if self.WELLBEING_RE.search(normalized):
            return True

        compact = normalized.replace(" ", "")
        if any(token in compact for token in ("hru", "howru", "howareyou")):
            return True

        # Handles noisy STT prefixes like "vhow r u".
        if re.search(r"\b[a-z]how\s*(?:are|r)\s*(?:you|u)\b", normalized):
            return True

        return False

    def _is_location_declaration_only(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False

        declared = self._extract_declared_location(lowered)
        if not declared:
            return False

        if any(
            matcher.search(lowered)
            for matcher in (
                self.WEATHER_RE,
                self.NEWS_RE,
                self.SPEEDTEST_RE,
                self.PUBLIC_IP_RE,
                self.LOCATION_RE,
                self.SEARCH_RE,
                self.CONNECTIVITY_RE,
                self.STATUS_RE,
                self.TEMPORAL_RE,
                self.UPDATE_RE,
            )
        ):
            return False

        return "?" not in lowered

    def _is_search_or_factual_request(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False

        if any(
            matcher.search(lowered)
            for matcher in (
                self.WEATHER_RE,
                self.PUBLIC_IP_RE,
                self.LOCATION_RE,
                self.SPEEDTEST_RE,
                self.CONNECTIVITY_RE,
                self.STATUS_RE,
                self.TEMPORAL_RE,
                self.UPDATE_RE,
            )
        ):
            return False

        if self.document_service is not None and (
            self._is_document_request(lowered) or self._is_document_question_request(lowered)
        ):
            return False

        return bool(
            self._is_search_request(lowered)
            or self._is_factual_query(lowered)
            or self._is_short_ipl_season_prompt(lowered)
        )

    @staticmethod
    def _assistant_identity_fallback() -> str:
        return "I am JARVIS, your assistant, Sir. I am doing well and ready to help."

    @staticmethod
    def _strip_role_labels(text: str) -> str:
        cleaned = re.sub(r"(?im)^\s*assistant\s*:?\s*", "", str(text or ""))
        cleaned = re.sub(r"(?im)^\s*jarvis\s*:?\s*", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _looks_like_identity_hallucination(text: str) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False

        hard_triggers = (
            "i am tony stark",
            "i'm tony stark",
            "my name is tony stark",
            "i am john smith",
            "i'm john smith",
            "my name is john smith",
            "ceo of stark industries",
            "billionaire inventor",
        )
        if any(trigger in lowered for trigger in hard_triggers):
            return True

        if re.search(r"\b(?:i am|i'm|my name is)\s+(?:a\s+)?\d{1,3}-year-old\b", lowered):
            return True

        if re.search(
            r"\b(?:i am|i'm|my name is)\s+(?:a\s+)?(software engineer|developer|doctor|teacher|student)\b",
            lowered,
        ):
            return True

        return False

    def _enforce_assistant_identity(self, text: str, *, user_text: str = "") -> str:
        cleaned = self._strip_role_labels(text)
        if self._looks_like_identity_hallucination(cleaned):
            return self._assistant_identity_fallback()

        if self.IDENTITY_QUERY_RE.search(user_text or "") and "jarvis" not in cleaned.lower():
            return self._assistant_identity_fallback()

        return cleaned

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
                self.CONNECTIVITY_RE,
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

    def _is_speedtest_request(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        if self.SPEEDTEST_RE.search(lowered):
            return True
        return self._is_speedtest_followup_query(lowered)

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
                self.CONNECTIVITY_RE,
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

    def _speed_snapshot_is_fresh(self, snapshot: dict[str, object]) -> bool:
        snapshot_ts = float(snapshot.get("timestamp", 0.0))
        if snapshot_ts <= 0:
            return False
        # Avoid serving stale remembered numbers as if they were newly measured.
        if (time.time() - snapshot_ts) > 900:
            return False
        if self._last_speedtest_requested_at <= 0:
            return True
        return snapshot_ts >= self._last_speedtest_requested_at

    def _get_memory_speedtest(self) -> dict[str, object] | None:
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
                "server_name": str(payload.get("server_name") or "").strip(),
                "server_host": str(payload.get("server_host") or "").strip(),
                "server_country": str(payload.get("server_country") or "").strip(),
                "server_sponsor": str(payload.get("server_sponsor") or "").strip(),
            }
        except Exception:
            return None

    def _build_speedtest_result_from_snapshot(self, snapshot: dict[str, object], *, country: str | None) -> str:
        download = float(snapshot.get("download_mbps", 0.0))
        upload = float(snapshot.get("upload_mbps", 0.0))
        if download >= 100 and upload >= 20:
            quality = "Your connection looks excellent for streaming, calls, and large file transfers."
        elif download >= 50 and upload >= 10:
            quality = "Your connection looks good for everyday use, meetings, and HD streaming."
        elif download >= 25 and upload >= 5:
            quality = "Your connection is usable, but heavier workloads may feel slower at times."
        else:
            quality = "Your connection is currently on the slower side; uploads and high-quality streaming may lag."

        return (
            "Internet speed test results:\n"
            f"Download Speed: {download:.2f} Mbps\n"
            f"Upload Speed: {upload:.2f} Mbps\n\n"
            f"{quality}"
        )

    def _build_speedtest_assessment_from_snapshot(self, snapshot: dict[str, object], *, country: str | None) -> str:
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
            "Use this naturally and accurately in relevant replies. "
            "When addressing the user directly, prefer 'Sir' and avoid first-name address unless explicitly requested."
        )

    @staticmethod
    def _preferred_address() -> str:
        return "Sir"

    def _groq_quick_reply(
        self,
        *,
        user_text: str,
        reply_goal: str,
        fallback: str,
        max_tokens: int = 120,
        temperature: float = 0.75,
    ) -> str:
        api_key = (self.config.groq_api_key or "").strip()
        if not api_key:
            return fallback

        preferred_address = self._preferred_address()
        stored_name = (self.memory.get("user_name") or "").strip()
        memory_line = f"Stored user name for memory only: {stored_name}." if stored_name else ""

        system_prompt = (
            "You are JARVIS. Write a short, natural, warm, confident reply. "
            "Sound attractive and human, not robotic. "
            "Keep it 1-2 lines, no bullet points, no emojis. "
            f"Address the user as {preferred_address}. Never address by first name."
        )
        user_prompt = (
            f"User said: {user_text}\n"
            f"Goal: {reply_goal}\n"
            f"Preferred address: {preferred_address}.\n"
            f"{memory_line}\n"
            "Return only the final reply text."
        )

        try:
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.groq_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "stream": False,
                    "max_tokens": max_tokens,
                },
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            choices = payload.get("choices") if isinstance(payload, dict) else None
            if isinstance(choices, list) and choices:
                message = choices[0].get("message") if isinstance(choices[0], dict) else None
                content = str((message or {}).get("content") or "").strip()
                if content:
                    return self._enforce_assistant_identity(content, user_text=user_text)
        except Exception as exc:
            logger.warning("Quick-reply LLM call failed; using fallback response: %s", exc)
            return fallback

        return fallback

    def _handle_greeting(self, text: str) -> str:
        lowered = (text or "").strip().lower()
        if "good afternoon" in lowered:
            period = "afternoon"
        elif "good evening" in lowered:
            period = "evening"
        elif "good night" in lowered:
            period = "night"
        elif "good morning" in lowered:
            period = "morning"
        else:
            period = self._day_period_label()
        return f"Good {period}, Sir. What should we tackle first?"

    def _handle_wellbeing(self, _text: str) -> str:
        period = self._day_period_label()
        if period == "night":
            return "Doing great tonight, Sir. What should we handle next?"
        return f"Doing great this {period}, Sir. What should we handle next?"

    def _handle_capabilities(self, _text: str) -> str:
        return (
            "I can help with weather and forecast checks, internet search and news, public IP and location diagnostics, "
            "connectivity and speed tests, system and app control, and document analysis with follow-up Q&A. "
            "Tell me the task directly and I will route it to the right tool."
        )

    def _handle_help(self, _text: str) -> str:
        return (
            "Try commands like: weather in delhi, forecast for tomorrow, check internet connectivity, what is my IP, "
            "where am I, run speed test, system status, what time is it, open chrome, close it, max volume, "
            "analyze document, and compare these documents."
        )

    @staticmethod
    def _day_period_label() -> str:
        current_hour = datetime.datetime.now().hour
        if 5 <= current_hour < 12:
            return "morning"
        if 12 <= current_hour < 17:
            return "afternoon"
        if 17 <= current_hour < 22:
            return "evening"
        return "night"

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
        return "Noted. I will keep that on file and address you as Sir."

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

        if self._last_user_query:
            retry = self.agent_loop.run(self._last_user_query)
            if retry.handled and retry.response:
                corrected = re.sub(
                    r"\s*Confidence:\s*(high|medium|low)\.?$",
                    "",
                    retry.response,
                    flags=re.IGNORECASE,
                ).strip()
                confidence = "high" if not retry.error else "medium"
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
        result = self.agent_loop.run(text)
        if result.handled:
            return result.response
        return None

    def _handle_connectivity(self, text: str) -> str:
        self._remember_fact(source="connectivity", query=text, handler=lambda _q: self.network_service.describe_connectivity())
        return self.network_service.describe_connectivity()

    def _handle_public_ip(self, text: str) -> str:
        self._remember_fact(source="public_ip", query=text, handler=lambda _q: self.network_service.describe_public_ip())
        return self.network_service.describe_public_ip()

    def _handle_network_location(self, text: str) -> str:
        self._remember_fact(source="network_location", query=text, handler=lambda _q: self.network_service.describe_ip_location())
        return self.network_service.describe_ip_location()

    def _handle_weather(self, text: str) -> str:
        self._remember_fact(source="weather", query=text, handler=self.weather_service.get_weather_brief)
        return self.weather_service.get_weather_brief(text)

    def _handle_search(self, text: str) -> str:
        effective_query = self._build_effective_search_query(self._extract_search_topic(text))

        result = self.agent_loop.run(effective_query)
        if result.handled and result.response:
            self._last_search_query = effective_query
            self.memory.set("last_search_query", effective_query)
            self._remember_fact(source="search", query=effective_query, handler=lambda q: self._deterministic_search_response(q))
            return result.response

        return self._deterministic_search_response(effective_query, user_text=text)

    def _deterministic_search_response(self, query: str, *, user_text: str | None = None) -> str:
        payload = self.search_service.search_web_raw(query, max_results=5)
        results = payload.get("results") if isinstance(payload, dict) else []
        if not isinstance(results, list) or not results:
            return self.personality.finalize(
                "I could not complete that web search request right now.",
                user_text=user_text or query,
            )

        self._last_search_query = query
        self.memory.set("last_search_query", query)

        answer = self._extract_ipl_winner_answer(query, results)
        if not answer:
            year = self._extract_ipl_year(query)
            lowered_query = (query or "").lower()
            if year and "ipl" in lowered_query and re.search(r"\b(who won|winner|champion|won)\b", lowered_query):
                focused_query = f"IPL {year} winner"
                focused_payload = self.search_service.search_web_raw(focused_query, max_results=5)
                focused_results = focused_payload.get("results") if isinstance(focused_payload, dict) else []
                if isinstance(focused_results, list) and focused_results:
                    answer = self._extract_ipl_winner_answer(focused_query, focused_results)
                    if answer:
                        self._last_search_query = focused_query
                        self.memory.set("last_search_query", focused_query)

        if answer:
            return self.personality.finalize(answer, user_text=user_text or query)

        lines = [f"Top web results for '{query}':"]
        for index, item in enumerate(results[:3], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            link = str(item.get("link") or "").strip()
            if title and link:
                lines.append(f"{index}. {title} — {link}")
            elif title:
                lines.append(f"{index}. {title}")

        return self.personality.finalize("\n".join(lines), user_text=user_text or query)

    def _extract_ipl_winner_answer(self, query: str, results: list[dict[str, object]]) -> str:
        lowered_query = (query or "").lower()
        if "ipl" not in lowered_query or not re.search(r"\b(who won|winner|champion|won)\b", lowered_query):
            return ""

        year = self._extract_ipl_year(lowered_query)
        if not year:
            return ""

        winner_patterns = (
            rf"\b([A-Z][A-Za-z0-9& .'-]{{2,60}}?)\s+(?:won|wins|clinched|lifted|secured)\s+(?:the\s+)?(?:IPL|Indian Premier League)\s*{year}\b",
            rf"\b(?:IPL|Indian Premier League)\s*{year}\s*(?:winner|champion)\s*[:\-]?\s*([A-Z][A-Za-z0-9& .'-]{{2,60}})\b",
        )
        team_aliases: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("Royal Challengers Bengaluru", ("royal challengers bengaluru", "royal challengers bangalore", "rcb")),
            ("Chennai Super Kings", ("chennai super kings", "csk")),
            ("Mumbai Indians", ("mumbai indians", "mi")),
            ("Kolkata Knight Riders", ("kolkata knight riders", "kkr")),
            ("Sunrisers Hyderabad", ("sunrisers hyderabad", "srh")),
            ("Rajasthan Royals", ("rajasthan royals", "rr")),
            ("Delhi Capitals", ("delhi capitals", "dc")),
            ("Punjab Kings", ("punjab kings", "pbks", "kings xi punjab")),
            ("Lucknow Super Giants", ("lucknow super giants", "lsg")),
            ("Gujarat Titans", ("gujarat titans", "gt")),
        )

        for item in results:
            if not isinstance(item, dict):
                continue
            probe = f"{item.get('title') or ''}. {item.get('snippet') or ''}".strip()
            probe_lower = probe.lower()

            if year in probe_lower and re.search(r"\b(won|wins|winner|champion|title|trophy|defeated|beat|clinched|lifted|secured)\b", probe_lower):
                for team_name, aliases in team_aliases:
                    for alias in aliases:
                        alias_pattern = re.escape(alias)
                        if re.search(
                            rf"\b{alias_pattern}\b[^.\n]{{0,40}}\b(won|wins|winner|champion|title|trophy|defeated|beat|clinched|lifted|secured)\b",
                            probe_lower,
                        ):
                            return f"Based on current web results, {team_name} won IPL {year} season."

            for pattern in winner_patterns:
                match = re.search(pattern, probe, flags=re.IGNORECASE)
                if not match:
                    continue
                winner = re.sub(r"\s+", " ", str(match.group(1) or "")).strip(" .,-")
                if winner:
                    return f"Based on current web results, {winner} won IPL {year} season."

        return ""

    def _handle_location_declaration(self, text: str) -> str:
        declared = self._extract_declared_location(text)
        if not declared:
            return "I caught your location update, but missed the exact place."

        self._set_session_location(declared)
        return f"Got it, Sir. I will use {declared} for local context."

    def _handle_system_status(self, text: str) -> str:
        self._remember_fact(source="system_status", query=text, handler=lambda _q: self.network_service.get_system_status_snapshot())
        return self.network_service.get_system_status_snapshot()

    def _handle_temporal(self, text: str) -> str:
        self._remember_fact(source="temporal", query=text, handler=lambda q: self.network_service.get_temporal_snapshot(q))
        return self.network_service.get_temporal_snapshot(text)

    def _is_document_request(self, text: str) -> bool:
        """Detect user requests to analyze a document file."""
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        # Don't intercept if document service is not available
        if self.document_service is None:
            return False

        if self._is_document_picker_request(lowered):
            return True

        # Let normal explorer/file-manager requests route through app_control.
        if self.FILE_MANAGER_RE.search(lowered):
            return False

        return bool(self.DOCUMENT_RE.search(lowered))

    def _is_document_picker_request(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        return bool(self.DOCUMENT_PICKER_RE.search(lowered))

    @staticmethod
    def _is_explicit_multi_file_compare_request(text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False

        if not re.search(r"\b(compare|comparison|versus|\bvs\b|difference|differences)\b", lowered):
            return False

        return bool(
            re.search(
                r"\b(?:the|these)?\s*(?:\d+|one|two|three|four|five|both|pair)\s*(?:documents?|files?|docs?|pdfs?)\b",
                lowered,
            )
        )

    def _is_document_question_request(self, text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered or self.document_service is None:
            return False

        has_active_docs = bool(getattr(self.document_service, "has_active_documents", lambda: False)())
        if not has_active_docs:
            return False

        if self.DOCUMENT_COMPARE_RE.search(lowered):
            if self._is_explicit_multi_file_compare_request(lowered):
                # Explicit compare of numbered files should open file picker again.
                return False

            explicit_file_selection = re.search(
                r"\b(upload|select|choose|open|load|pick|analyze|process)\b",
                lowered,
            )
            if explicit_file_selection:
                return False

            active_names = getattr(self.document_service, "active_document_names", lambda: [])()
            active_doc_count = len(active_names) if isinstance(active_names, list) else 0
            return active_doc_count >= 2

        if self.DOCUMENT_RE.search(lowered):
            # Explicit analyze/read/upload commands should use file selection flow.
            if re.search(r"\b(analyze|summarize|read|open|load|upload|select|process|compare)\b", lowered):
                return False

        if any(
            matcher.search(lowered)
            for matcher in (
                self.WEATHER_RE,
                self.PUBLIC_IP_RE,
                self.LOCATION_RE,
                self.SPEEDTEST_RE,
                self.STATUS_RE,
                self.TEMPORAL_RE,
                self.UPDATE_RE,
            )
        ):
            return False

        if self.DOCUMENT_QA_HINT_RE.search(lowered):
            return True

        if self._last_fact_source in {"document", "document_qa", "document_compare"} and re.search(
            r"^(what|which|how|where|when|why|list|find|show|compare)\b",
            lowered,
        ):
            return True

        if self._is_factual_query(lowered):
            return False

        return False

    def _handle_document_question(self, text: str) -> str:
        if self.document_service is None:
            return "Document analysis is not available. Install the required dependencies first."

        try:
            response = self.document_service.answer_question_for_display(text)
        except Exception as exc:
            return f"Document question answering encountered an error: {exc}"

        self._remember_fact(
            source="document_qa",
            query=text,
            handler=lambda _q: self.document_service.answer_question_for_display(_q),
        )
        return response

    def _handle_document(self, text: str) -> str:
        """Handle document analysis requests.

        IMPORTANT: The file picker is opened here by the SYSTEM, not the LLM.
        The LLM only decides this intent needs handling; it never triggers UI directly.
        """
        if self.document_service is None:
            return "Document analysis is not available. Install the required dependencies first."

        # System opens the file picker — LLM has no involvement in this step
        from services.document.file_selector import select_files, validate_file_path

        compare_mode = bool(self.DOCUMENT_COMPARE_RE.search(text or ""))

        self._emit_mode("processing")
        self._emit_text_delta("Opening file selector...")

        # In desktop/voice mode, never block on terminal input fallback.
        allow_cli_fallback = not any(
            callback is not None
            for callback in (self._on_mode_change, self._on_text_delta, self._on_api_activity)
        )

        # Try GUI picker first; fall back to CLI.
        selected_paths = select_files(
            prefer_gui=True,
            allow_multiple=compare_mode,
            allow_cli_fallback=allow_cli_fallback,
        )

        if not selected_paths:
            return "No document was selected. Please say 'analyze document' again and choose a file."

        if compare_mode and len(selected_paths) < 2:
            return "Please select at least two documents to compare."

        validated_paths: list[str] = []
        for file_path in selected_paths:
            validated_path, error = validate_file_path(file_path)
            if error:
                return f"I cannot process that file: {error}"
            validated_paths.append(validated_path)

        if not validated_paths:
            return "No valid document was selected."

        # Emit processing status
        from pathlib import Path
        if compare_mode:
            short_names = ", ".join(Path(path).name for path in validated_paths[:3])
            self._emit_text_delta(f"Comparing {len(validated_paths)} documents: {short_names}...")
        else:
            file_name = Path(validated_paths[0]).name
            self._emit_text_delta(f" Analyzing {file_name}...")
        self._emit_text_delta(" This may take few moments, stay put.")

        try:
            if compare_mode:
                result = self.document_service.compare_documents_for_display(
                    validated_paths,
                    user_query=text,
                )
            else:
                result = self.document_service.analyze_for_display(
                    validated_paths[0],
                    user_query=text,
                )
        except Exception as exc:
            return f"Document analysis encountered an error: {exc}"

        if compare_mode:
            self._remember_fact(
                source="document_compare",
                query=text,
                handler=lambda _q: self.document_service.compare_documents_for_display(validated_paths, user_query=_q),
            )
        else:
            selected_path = validated_paths[0]
            self._remember_fact(
                source="document",
                query=text,
                handler=lambda _q: self.document_service.analyze_for_display(selected_path, user_query=_q),
            )
        return result

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
        self._api_active = bool(active)
        if self._on_api_activity:
            try:
                self._on_api_activity(active)
            except Exception:
                pass

    def _clear_turn_cancellation(self) -> None:
        self._cancel_event.clear()

    def _is_turn_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _cancel_current_turn(self) -> None:
        self._cancel_event.set()

        response_to_close: requests.Response | None = None
        with self._stream_response_lock:
            if self._active_stream_response is not None:
                response_to_close = self._active_stream_response
                self._active_stream_response = None

        if response_to_close is not None:
            try:
                response_to_close.close()
            except Exception:
                pass

    def _handle_tts_start(self) -> None:
        self._emit_mode("speaking")

    def _handle_tts_stop(self) -> None:
        if self._api_active:
            self._emit_mode("processing")
            return
        self._emit_mode("listening")

    def skip_current_reply(self) -> dict[str, object]:
        self._cancel_current_turn()
        turn_id = self.tts.interrupt()
        self._emit_api_activity(False)
        self._emit_mode("listening")
        return {
            "skipped": True,
            "turn_id": turn_id,
            "api_active": self._api_active,
            "cancel_requested": True,
        }

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
        if self._is_turn_cancelled():
            self._emit_api_activity(False)
            self._emit_mode("listening")
            return "Request skipped."

        normalized_response = self._enforce_assistant_identity(response_text, user_text=user_text)
        finalized = self.personality.finalize(normalized_response, user_text=user_text)

        if persist_user:
            self.messages.append({"role": "user", "content": user_text})
            self._trim_history()

        turn_id = self.tts.interrupt()
        self._emit_mode("processing")
        self._emit_api_activity(False)
        self._emit_text_delta(finalized)
        queued_any_speech = self.tts.enqueue_text(finalized, turn_id)
        if queued_any_speech:
            self.tts.wait_for_turn_completion(
                turn_id,
                timeout_s=self.config.tts_turn_completion_timeout_seconds,
            )
        else:
            self._emit_mode("listening")

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
        self._clear_turn_cancellation()
        cleaned = self.text_cleaner.clean(text)
        normalized_text = cleaned.cleaned_text or text
        self._capture_session_location(normalized_text)

        # Support "weather again" style turns by reusing remembered city context.
        if cleaned.had_again and self.WEATHER_RE.search(normalized_text):
            has_city = bool(re.search(r"\b(?:in|at|for)\s+[a-zA-Z]", normalized_text, flags=re.IGNORECASE))
            if not has_city:
                last_city = self._get_session_location() or str(self.memory.get("last_city") or "").strip()
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

        agent_result = self.agent_loop.run(normalized_text)
        if agent_result.handled and agent_result.response:
            self._remember_fact(
                source="agent_loop",
                query=normalized_text,
                handler=lambda q: self.agent_loop.run(q).response,
            )
            return self._respond_local(
                text,
                agent_result.response,
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

        response: requests.Response | None = None
        try:
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
            with self._stream_response_lock:
                self._active_stream_response = response
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
                    if self._is_turn_cancelled():
                        break

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

                    if self._is_turn_cancelled():
                        break

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
                            if self.tts.enqueue_text(first_chunk, turn_id):
                                queued_any_speech = True
                                last_chunk_queued_at = time.perf_counter()

                    while True:
                        if self._is_turn_cancelled():
                            break
                        chunk_to_speak, speak_buffer = self._next_speech_chunk(speak_buffer, final=False)
                        if not chunk_to_speak:
                            break

                        if first_voice_chunk and self.config.tts_first_chunk_delay > 0:
                            time.sleep(self.config.tts_first_chunk_delay)
                        first_voice_chunk = False
                        if self.tts.enqueue_text(chunk_to_speak, turn_id):
                            queued_any_speech = True
                            last_chunk_queued_at = time.perf_counter()

                    if self._is_turn_cancelled():
                        break

                    if speak_buffer.strip() and (time.perf_counter() - last_chunk_queued_at) >= self.EARLY_CHUNK_MAX_WAIT_SECONDS:
                        early_chunk, speak_buffer = self._early_speech_chunk(speak_buffer)
                        if early_chunk:
                            if first_voice_chunk and self.config.tts_first_chunk_delay > 0:
                                time.sleep(self.config.tts_first_chunk_delay)
                            first_voice_chunk = False
                            if self.tts.enqueue_text(early_chunk, turn_id):
                                queued_any_speech = True
                                last_chunk_queued_at = time.perf_counter()
            finally:
                self._emit_api_activity(False)

            if self._is_turn_cancelled():
                if stream_to_stdout:
                    print()
                self._emit_mode("listening")
                return "Request skipped."

            if speak_buffer.strip():
                if first_voice_chunk and self.config.tts_first_chunk_delay > 0:
                    time.sleep(self.config.tts_first_chunk_delay)
                tail_chunk, _ = self._next_speech_chunk(speak_buffer, final=True)
                if tail_chunk:
                    if self.tts.enqueue_text(tail_chunk, turn_id):
                        queued_any_speech = True

            raw_text = full_text.strip().strip('"')
            if not full_text.strip():
                raw_text = "I did not receive a valid response. Please try again."
                full_text = raw_text
                if stream_to_stdout:
                    print(raw_text, end="", flush=True)
                if self.tts.enqueue_text(raw_text, turn_id):
                    queued_any_speech = True

            if stream_to_stdout:
                print()

            if self._is_conceptual_query(normalized_text) and not self._is_explicit_detail_request(normalized_text):
                raw_text = self._briefen_response(raw_text)

            raw_text = self._enforce_assistant_identity(raw_text, user_text=normalized_text)
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
        finally:
            with self._stream_response_lock:
                if self._active_stream_response is response:
                    self._active_stream_response = None
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    def greet(self, *, stream_to_stdout: bool = True) -> str:
        day_period = self._day_period_label()
        greeting = f"Good {day_period}, Sir. Ready when you are. What should we work on first?"
        return self._respond_local(
            user_text="",
            response_text=greeting,
            persist_user=False,
            stream_to_stdout=stream_to_stdout,
        )

    def close(self) -> None:
        self.network_service.close()
        self.tts.close()
