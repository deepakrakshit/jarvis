from __future__ import annotations
import datetime
import json
import logging
import re
import threading
import time
from typing import Callable
from agent.agent_loop import AgentLoop
from agent.tool_registry import build_default_tool_registry
from core.humor import HumorEngine
from core.llm_api import chat_complete
from core.personality import PersonalityEngine
from core.settings import AppConfig, RESET, SYSTEM_PROMPT, WHITE
from memory.store import MemoryStore, extract_user_name
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
    - orchestrate LLM responses for general requests
    - coordinate TTS and UI callbacks
    """
    FIRST_CHUNK_MIN_CHARS = 14
    FIRST_CHUNK_MAX_CHARS = 26
    EARLY_CHUNK_MIN_CHARS = 20
    EARLY_CHUNK_TARGET_CHARS = 34
    EARLY_CHUNK_MAX_CHARS = 36
    EARLY_CHUNK_MAX_WAIT_SECONDS = 0.22
    WEATHER_RE = re.compile('\\b(weather|temperature|forecast)\\b', re.IGNORECASE)
    NEWS_RE = re.compile('\\b(news|headline|headlines|breaking)\\b', re.IGNORECASE)
    GREETING_RE = re.compile('^\\s*(hello|hi|hey|yo|good morning|good afternoon|good evening|good night)\\b', re.IGNORECASE)
    WELLBEING_RE = re.compile(r"\b(how are you|how are you feeling|how's it going|how do you feel|how r u|hru|how ru)\b", re.IGNORECASE)
    IDENTITY_QUERY_RE = re.compile(r"\b(who are you|what are you|what(?:'s| is) your name|are you human)\b", re.IGNORECASE)
    NAME_QUERY_RE = re.compile(r"\b(what(?:'s| is)? my name|do you know my name|who am i)\b", re.IGNORECASE)
    NAME_SET_RE = re.compile('\\b(my name is|name is|call me)\\b', re.IGNORECASE)
    CORRECTION_RE = re.compile(r"\b(that'?s wrong|that is wrong|incorrect|not correct|wrong answer|you are wrong|that's completely wrong|hallucinating|hallucination)\b", re.IGNORECASE)
    SPEEDTEST_RE = re.compile('\\b(speed\\s*test|speedtest|internet speed|network speed)\\b', re.IGNORECASE)
    CONNECTIVITY_RE = re.compile('\\b(internet connectivity|network connectivity|connectivity status|am i online|online status|check connectivity|check internet connectivity|check network connectivity)\\b', re.IGNORECASE)
    PUBLIC_IP_RE = re.compile('\\b(public ip|my ip|ip address|external ip|current ip|current ip address)\\b', re.IGNORECASE)
    LOCATION_RE = re.compile('\\b(where am i|my location|current location|location from ip|network location)\\b', re.IGNORECASE)
    STATUS_RE = re.compile('\\b(system status|device status|pc status|computer status|network status|status of (?:my )?(?:system|pc|computer|device)|how is (?:my )?(?:system|pc|computer|device))\\b', re.IGNORECASE)
    TEMPORAL_RE = re.compile(r"\b(current time|time now|what time|local time|current date|date today|today's date|what date|what day is it|current year|what year|current month|what month)\b", re.IGNORECASE)
    UPDATE_RE = re.compile('\\b(system update|software update|update status|version|patch|upgrade)\\b', re.IGNORECASE)
    HELP_RE = re.compile('^\\s*(help|help me|commands|list commands|list available commands|available commands|show commands)\\s*$', re.IGNORECASE)
    CAPABILITIES_RE = re.compile('\\b(what can you do|your capabilities|capabilities|what do you do|how can you help)\\b', re.IGNORECASE)
    SEARCH_RE = re.compile('\\b(search|internet|web|google|look up|lookup|find online)\\b', re.IGNORECASE)
    SEARCH_POLICY_RE = re.compile('\\b(check|use|verify)\\b.*\\b(internet|web|online)\\b|\\bknowledge cutoff\\b', re.IGNORECASE)
    ABUSE_RE = re.compile('\\b(trash|useless|stupid|idiot|dumb|worst)\\b', re.IGNORECASE)
    FACTUAL_RE = re.compile('\\b(who won|what happened|latest|recent|facts?|history|record|ipl|season|champion|winner|news|current|prime minister|pm|president|chief minister|capital|population|replacement|replace|replaced|confirm|holiday)\\b', re.IGNORECASE)
    AMBIGUOUS_SEASON_RE = re.compile('^\\s*(?:the\\s+)?(?:\\d{4}|20\\d{2})\\s+season\\.?\\s*$|^\\s*season\\s+\\d{4}\\.?\\s*$', re.IGNORECASE)
    LOCATION_DECLARE_RE = re.compile(r"\b(?:i am|i'm|im|my location is|currently in|i live in)\s+([a-zA-Z][a-zA-Z\s\-]{1,80})", re.IGNORECASE)
    DOCUMENT_RE = re.compile('\\b(analyze|summarize|read|extract|parse|process|review|upload|select|compare)\\b.*\\b(document|documents|doc|docs|pdf|pdfs|docx|file|files|image|images|scan)\\b|\\b(open|load)\\b.*\\b(document|documents|doc|docs|pdf|pdfs|docx|image|images|scan)\\b|\\b(document|pdf|docx)\\b', re.IGNORECASE)
    DOCUMENT_PICKER_RE = re.compile('\\b(open|show|launch|start)\\b.*\\b(file\\s*picker|document\\s*selector|document\\s*picker)\\b|\\b(select|choose|pick|upload)\\b.*\\b(document|pdf|docx|doc|image|scan|file)\\b', re.IGNORECASE)
    FILE_MANAGER_RE = re.compile('\\b(file\\s*explorer|file\\s*manager|windows\\s*explorer|explorer)\\b', re.IGNORECASE)
    DOCUMENT_COMPARE_RE = re.compile('\\b(compare|comparison|versus|\\bvs\\b|difference|differences)\\b.*\\b(document|documents|doc|docs|pdf|pdfs|docx|file|files)\\b|\\bcompare\\s+(?:the\\s+)?(?:\\d+|two|three|four|five)\\s+(?:documents?|files?|docs?|pdfs?)\\b|\\bcompare\\s+these\\b', re.IGNORECASE)
    DOCUMENT_QA_HINT_RE = re.compile('\\b(pricing|price|cost|risk|risks|plan|plans|feature|features|entity|entities|key point|key points|find all|what does this|in this document|from this file)\\b', re.IGNORECASE)

    def __init__(self, config: AppConfig | None=None) -> None:
        self.config = config or AppConfig.from_env('.env')
        self.personality = PersonalityEngine(controlled_humor=False)
        self.humor = HumorEngine()
        self.memory = MemoryStore(self.config.memory_store_path)
        self.text_cleaner = TextCleaner()
        self.messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
        self._on_mode_change: Callable[[str], None] | None = None
        self._on_text_delta: Callable[[str], None] | None = None
        self._on_api_activity: Callable[[bool], None] | None = None
        self._request_lock = threading.Lock()
        self._last_fact_query = ''
        self._last_fact_source = ''
        self._last_fact_handler: Callable[[str], str] | None = None
        self._last_assistant_reply = ''
        self._last_user_query = ''
        self._last_search_query = str(self.memory.get('last_search_query') or '').strip()
        self._last_speedtest_requested_at = float(self.memory.get('last_speedtest_requested_at') or 0.0)
        self._session_location = ''
        self._api_active = False
        self._cancel_event = threading.Event()
        self._stream_response_lock = threading.Lock()
        self._active_stream_response: object | None = None
        self.tts = RealtimePiperTTS(self.config, on_speaking_start=self._handle_tts_start, on_speaking_stop=self._handle_tts_stop)
        self.network_service = NetworkService(self.config, self.personality)
        self.search_service = SearchService(self.config, self.personality)
        self.weather_service = WeatherService(self.config, self.network_service, self.personality, self.humor, self.memory)
        self.document_service = self._init_document_service()
        self.tool_registry = build_default_tool_registry(network_service=self.network_service, weather_service=self.weather_service, search_service=self.search_service, document_service=self.document_service, memory_store=self.memory, get_session_location=self._get_session_location, set_session_location=self._set_session_location)
        self.agent_loop = AgentLoop.from_registry(config=self.config, tool_registry=self.tool_registry, get_session_location=self._get_session_location)

    def _get_session_location(self) -> str | None:
        value = ' '.join((self._session_location or '').strip().split())
        return value or None

    def _set_session_location(self, location: str) -> None:
        cleaned = re.sub('\\s+', ' ', (location or '').strip())
        cleaned = cleaned.strip(' .,!?;:')
        if not cleaned:
            return
        self._session_location = cleaned
        self.memory.set('last_city', cleaned)

    def _extract_declared_location(self, text: str) -> str:
        match = self.LOCATION_DECLARE_RE.search(text or '')
        if not match:
            return ''
        candidate = re.split('\\b(?:and|but|so|please|weather|forecast|temperature|check)\\b', match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
        candidate = re.sub('\\s+', ' ', candidate).strip(' .,!?;:')
        if candidate.lower().startswith('in '):
            candidate = candidate[3:].strip(' .,!?;:')
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
            logger.info('Document service unavailable due to missing dependency: %s', exc)
            return None
        except Exception as exc:
            logger.exception('Document service initialization failed: %s', exc)
            return None

    @staticmethod
    def _assistant_identity_fallback() -> str:
        return 'I am JARVIS, your assistant, Sir. I am doing well and ready to help.'

    @staticmethod
    def _strip_role_labels(text: str) -> str:
        cleaned = re.sub('(?im)^\\s*assistant\\s*:?\\s*', '', str(text or ''))
        cleaned = re.sub('(?im)^\\s*jarvis\\s*:?\\s*', '', cleaned)
        return cleaned.strip()

    @staticmethod
    def _looks_like_identity_hallucination(text: str) -> bool:
        lowered = str(text or '').strip().lower()
        if not lowered:
            return False
        hard_triggers = ('i am tony stark', "i'm tony stark", 'my name is tony stark', 'i am john smith', "i'm john smith", 'my name is john smith', 'ceo of stark industries', 'billionaire inventor')
        if any((trigger in lowered for trigger in hard_triggers)):
            return True
        if re.search("\\b(?:i am|i'm|my name is)\\s+(?:a\\s+)?\\d{1,3}-year-old\\b", lowered):
            return True
        if re.search("\\b(?:i am|i'm|my name is)\\s+(?:a\\s+)?(software engineer|developer|doctor|teacher|student)\\b", lowered):
            return True
        return False

    def _enforce_assistant_identity(self, text: str, *, user_text: str='') -> str:
        cleaned = self._strip_role_labels(text)
        if self._looks_like_identity_hallucination(cleaned):
            return self._assistant_identity_fallback()
        if re.search(r"\b(who are you|what are you|what(?:'s| is) your name|are you human)\b", user_text or '', re.IGNORECASE) and 'jarvis' not in cleaned.lower():
            return self._assistant_identity_fallback()
        return cleaned

    def _is_explicit_detail_request(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False
        return any((marker in lowered for marker in ('in detail', 'detailed', 'deep dive', 'step by step', 'comprehensive', 'elaborate', 'full explanation')))

    @staticmethod
    def _is_correction_request(text: str) -> bool:
        lowered = ' '.join((text or '').strip().lower().split())
        if not lowered:
            return False

        if JarvisRuntime.CORRECTION_RE.search(lowered):
            return True

        direct_markers = (
            'i meant',
            'i mean',
            'correction',
            'correct that',
            'not that',
            'that is wrong',
            "that's wrong",
            'wrong answer',
            'instead',
            'you got it wrong',
            'no,',
            'no ',
        )
        if any(marker in lowered for marker in direct_markers):
            return True

        # Handle concise follow-up correction phrasing such as "set it to 35".
        if re.search(r"\b(set|change|make|adjust|update)\b.*\b(it|that)\b", lowered):
            return True

        if re.search(r"\b(it'?s|it is)\s+still\b", lowered) and re.search(r"\b\d{1,3}\b", lowered):
            return True

        if lowered in {'wrong', 'incorrect', 'no', 'nope'}:
            return True

        return False

    def _is_conceptual_query(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False
        return bool(re.search('\\b(how does|how do|explain|teach me|what is|define|difference between|semiconductor|physics|bandgap|paradox|immovable|unstoppable|mobile phone)\\b', lowered))

    @staticmethod
    def _briefen_response(text: str) -> str:
        source = (text or '').strip()
        if not source:
            return ''
        single_line = re.sub('\\s+', ' ', source).strip()
        sentences = re.split('(?<=[.!?])\\s+', single_line)
        if len([part for part in sentences if part.strip()]) <= 2 and len(single_line) <= 260 and (source.count('\n') <= 3):
            return source
        kept = [part.strip() for part in sentences if part.strip()][:2]
        if not kept:
            kept = [single_line[:220].rstrip() + '...']
        brief = ' '.join(kept).strip()
        if not brief.endswith(('.', '?', '!')):
            brief += '.'
        if 'want a deeper' not in brief.lower():
            brief += ' Want a deeper breakdown?'
        return brief

    def _is_search_request(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False

        if self.SEARCH_RE.search(lowered):
            return True

        if re.search(r'\b(who won|what happened)\b', lowered) and self.FACTUAL_RE.search(lowered):
            return True

        return 'latest news' in lowered

    def _is_factual_query(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False

        if self._is_search_request(lowered) and (self.FACTUAL_RE.search(lowered) or re.search(r'\b(who|what|when|where|is there|can|does|did|will)\b', lowered)):
            return True

        if re.search(r'\bipl\b', lowered) and re.search(r'\b20\d{2}\b', lowered):
            return True

        if re.search(r'\b(current|latest)\b', lowered) and re.search(r'\b(prime minister|president|chief minister|capital|population)\b', lowered):
            return True

        if re.search(r'\b(is|are)\b', lowered) and re.search(r'\b(current|prime minister|\bpm\b|president|chief minister|captain)\b', lowered):
            return True

        if re.search(r'\b(confirm|replacement|replace|replaced)\b', lowered) and re.search(r'\b(ipl|season|campaign|team|squad|player)\b', lowered):
            return True

        if 'holiday' in lowered and any((token in lowered for token in ('today', 'tomorrow', 'date', 'day', 'is'))):
            return True

        if self._last_search_query and re.search(r'\b(that season|that team|that winner|which team|that year)\b', lowered):
            return True

        patterns = [r'\bwho\b', r'\bwhen\b', r'\bwhere\b', r'\bwhat\b', r'\bwon\b', r'\bchampion\b', r'\bfacts?\b', r'\bhistory\b']
        return bool(self.FACTUAL_RE.search(lowered)) and any((re.search(pattern, lowered) for pattern in patterns))

    def _is_speedtest_followup_query(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if self._last_fact_source != 'speedtest':
            return False
        if re.search('\\b(holiday|prime minister|\\bpm\\b|president|ipl|season|weather|news|capital|population|who|what|when|where)\\b', lowered):
            return False
        followup_markers = ('speed result', 'speedtest result', 'internet speed', 'network speed', 'results out', 'results out now', 'results now', 'are the results', 'download', 'upload', 'ping', 'average speed', 'just got', 'that speed', 'those speeds', 'below average', 'above average', 'check speed', 'run again')
        return any((marker in lowered for marker in followup_markers))

    @staticmethod
    def _extract_ipl_year(query: str) -> str | None:
        match = re.search('\\b(20\\d{2})\\b', query or '', flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1)

    @staticmethod
    def _normalize_query_typos(text: str) -> str:
        normalized = text or ''
        normalized = re.sub('\\bibill\\b', 'IPL', normalized, flags=re.IGNORECASE)
        normalized = re.sub('\\bipll\\b', 'IPL', normalized, flags=re.IGNORECASE)
        return normalized

    @staticmethod
    def _is_short_ipl_season_prompt(text: str) -> bool:
        lowered = re.sub('\\s+', ' ', (text or '').strip().lower())
        patterns = ('^(?:the\\s+)?ipl\\s+20\\d{2}\\s+season$', '^20\\d{2}\\s+ipl\\s+season$', '^(?:the\\s+)?ipl\\s+season\\s+20\\d{2}$')
        return any((re.search(pattern, lowered) for pattern in patterns))

    @staticmethod
    def _is_non_winner_ipl_context(text: str) -> bool:
        return bool(re.search('\\b(replacement|replace|replaced|confirm|campaign|squad|auction|captain|coach|retained|released|injury)\\b', text or '', flags=re.IGNORECASE))

    @staticmethod
    def _is_generic_search_command(text: str) -> bool:
        lowered = re.sub('\\s+', ' ', (text or '').strip().lower())
        if not lowered:
            return False
        if re.fullmatch('(?:then\\s+|now\\s+|please\\s+)*(?:search(?:\\s+on\\s+(?:the\\s+)?)?(?:internet|web|online)|search|use\\s+internet|check\\s+internet)(?:\\s+(?:pro|bro))?', lowered):
            return True
        return lowered in {'search', 'search internet', 'search on internet', 'search on the internet'}

    def _extract_search_topic(self, text: str) -> str:
        cleaned = self.text_cleaner.clean(text).cleaned_text or text
        lowered_cleaned = cleaned.lower()
        if self._is_generic_search_command(cleaned):
            if self._last_fact_query:
                return self._last_fact_query
            if self._last_user_query and self._is_factual_query(self._last_user_query):
                return self._last_user_query
            return cleaned
        clauses = [part.strip(' .?!') for part in re.split('[?]', cleaned) if part.strip(' .?!')]
        if len(clauses) >= 2:
            for clause in reversed(clauses):
                lowered_clause = clause.lower()
                if 'holiday' in lowered_clause or bool(re.search(r"\b(who won|what happened|latest|recent|facts?|history|record|ipl|season|champion|winner|news|current|prime minister|pm|president|chief minister|capital|population|replacement|replace|replaced|confirm|holiday)\b", lowered_clause, re.IGNORECASE)) or bool(re.search('\\b(who|what|when|where|is there|can|does|did|will)\\b', lowered_clause)):
                    return clause
        if re.match('^\\s*(then\\s+|now\\s+|please\\s+)*search\\b', lowered_cleaned):
            explicit = re.search('^\\s*(?:then\\s+|now\\s+|please\\s+)*search(?:\\s+on\\s+(?:the\\s+)?(?:internet|web|online)|\\s+(?:internet|web|online))?\\s+(.+)$', cleaned, flags=re.IGNORECASE)
            if explicit:
                candidate = explicit.group(1).strip(' .?!')
                if candidate and candidate.lower() not in {'internet', 'web', 'online', 'the internet', 'pro', 'bro'}:
                    return candidate
        prefixed = re.search('^\\s*(?:i\\s+said\\s+)?check\\s+on\\s+(?:the\\s+)?(?:internet|web|online)\\s+(?:that\\s+)?(.+)$', cleaned, flags=re.IGNORECASE)
        if prefixed:
            candidate = prefixed.group(1).strip(' .?!')
            if candidate:
                return candidate
        return cleaned

    def _build_effective_search_query(self, text: str) -> str:
        normalized_text = self._normalize_query_typos(text)
        cleaned = self.text_cleaner.clean(normalized_text).cleaned_text or normalized_text
        lowered = cleaned.lower()
        if re.search('\\bipl\\b', lowered):
            year = self._extract_ipl_year(lowered)
            winner_intent = bool(re.search('\\b(who won|winner|champion|which team won|won)\\b', lowered))
            short_season_prompt = self._is_short_ipl_season_prompt(lowered)
            if year and (winner_intent or short_season_prompt) and (not self._is_non_winner_ipl_context(lowered)):
                return f'who won IPL {year} season'
        if self._last_search_query and re.search('\\b(that season|that team|that winner|that year|which team)\\b', lowered):
            if re.search('\\b(who won|winner|won|which team)\\b', lowered):
                return self._last_search_query
            return f'{cleaned} about {self._last_search_query}'
        if re.search('\\bwon that season\\b', lowered) and self._last_search_query:
            return self._last_search_query
        if re.search('\\bipl\\s+20\\d{2}\\s+season\\b', lowered):
            year = self._extract_ipl_year(lowered)
            if year:
                return f'who won IPL {year} season'
        return cleaned

    @staticmethod
    def _speedtest_benchmark(country: str | None) -> tuple[float, float, str]:
        normalized = (country or '').strip().lower()
        if normalized == 'india':
            return (40.0, 100.0, 'India')
        if normalized in {'united states', 'usa', 'us'}:
            return (100.0, 200.0, 'United States')
        return (50.0, 150.0, country or 'your region')

    def _resolve_user_country(self) -> str | None:
        try:
            location = self.network_service.get_location_from_ip()
        except Exception:
            location = None
        if location and location.country:
            self.memory.set('user_country', location.country)
            return location.country
        remembered = str(self.memory.get('user_country') or '').strip()
        return remembered or None

    def _speed_query_mode(self, text: str) -> str | None:
        lowered = (text or '').lower()
        if any((word in lowered for word in ('run speed', 'run speedtest', 'start speed', 'new speed test', 'run internet speed'))):
            return None
        if any((word in lowered for word in ('average', 'below', 'above', 'fast', 'slow', 'good', 'better', 'improve', 'upgrade'))):
            return 'assessment'
        if any((word in lowered for word in ('result', 'results', 'status', 'report', 'latest', 'show', 'out now', 'done'))):
            return 'result'
        return None

    def _speed_snapshot_is_fresh(self, snapshot: dict[str, object]) -> bool:
        snapshot_ts = float(snapshot.get('timestamp', 0.0))
        if snapshot_ts <= 0:
            return False
        if time.time() - snapshot_ts > 900:
            return False
        if self._last_speedtest_requested_at <= 0:
            return True
        return snapshot_ts >= self._last_speedtest_requested_at

    def _get_memory_speedtest(self) -> dict[str, object] | None:
        payload = self.memory.get('last_speedtest')
        if not isinstance(payload, dict):
            return None
        required = ('download_mbps', 'upload_mbps', 'ping_ms')
        if not all((key in payload for key in required)):
            return None
        try:
            return {'download_mbps': float(payload['download_mbps']), 'upload_mbps': float(payload['upload_mbps']), 'ping_ms': float(payload['ping_ms']), 'timestamp': float(payload.get('timestamp', 0.0)), 'server_name': str(payload.get('server_name') or '').strip(), 'server_host': str(payload.get('server_host') or '').strip(), 'server_country': str(payload.get('server_country') or '').strip(), 'server_sponsor': str(payload.get('server_sponsor') or '').strip()}
        except Exception:
            return None

    def _build_speedtest_result_from_snapshot(self, snapshot: dict[str, object], *, country: str | None) -> str:
        download = float(snapshot.get('download_mbps', 0.0))
        upload = float(snapshot.get('upload_mbps', 0.0))
        if download >= 100 and upload >= 20:
            quality = 'Your connection looks excellent for streaming, calls, and large file transfers.'
        elif download >= 50 and upload >= 10:
            quality = 'Your connection looks good for everyday use, meetings, and HD streaming.'
        elif download >= 25 and upload >= 5:
            quality = 'Your connection is usable, but heavier workloads may feel slower at times.'
        else:
            quality = 'Your connection is currently on the slower side; uploads and high-quality streaming may lag.'
        return f'Internet speed test results:\nDownload Speed: {download:.2f} Mbps\nUpload Speed: {upload:.2f} Mbps\n\n{quality}'

    def _build_speedtest_assessment_from_snapshot(self, snapshot: dict[str, object], *, country: str | None) -> str:
        download = float(snapshot.get('download_mbps', 0.0))
        (avg_low, avg_high, country_label) = self._speedtest_benchmark(country)
        if download < avg_low:
            note = 'below typical'
            guidance = 'You can improve this with Ethernet testing, router placement tuning, and an ISP plan check.'
        elif download <= avg_high:
            note = 'within typical'
            guidance = 'This should handle regular work and streaming reliably.'
        else:
            note = 'above typical'
            guidance = 'This is strong for most high-bandwidth home workloads.'
        return f'Your measured download speed is {download:.1f} Mbps, which is {note} for common {country_label} ranges ({avg_low:.0f}-{avg_high:.0f} Mbps). {guidance}'

    def _remember_fact(self, *, source: str, query: str, handler: Callable[[str], str]) -> None:
        self._last_fact_source = source
        self._last_fact_query = query
        self._last_fact_handler = handler

    def _build_profile_context(self) -> str | None:
        user_name = (self.memory.get('user_name') or '').strip()
        if not user_name:
            return None
        return f"Known user profile: user_name={user_name}. Use this naturally and accurately in relevant replies. When addressing the user directly, prefer 'Sir' and avoid first-name address unless explicitly requested."

    @staticmethod
    def _preferred_address() -> str:
        return 'Sir'

    def _quick_reply(self, *, user_text: str, reply_goal: str, fallback: str, max_tokens: int=120, temperature: float=0.75) -> str:
        api_key = self.config.primary_llm_api_key()
        if not api_key:
            return fallback
        preferred_address = self._preferred_address()
        stored_name = (self.memory.get('user_name') or '').strip()
        memory_line = f'Stored user name for memory only: {stored_name}.' if stored_name else ''
        system_prompt = f'You are JARVIS. Write a short, natural, warm, confident reply. Sound attractive and human, not robotic. Keep it 1-2 lines, no bullet points, no emojis. Address the user as {preferred_address}. Never address by first name.'
        user_prompt = f'User said: {user_text}\nGoal: {reply_goal}\nPreferred address: {preferred_address}.\n{memory_line}\nReturn only the final reply text.'
        try:
            content = chat_complete(self.config, messages=[{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_prompt}], temperature=temperature, max_tokens=max_tokens, timeout=15).strip()
            if content:
                return self._enforce_assistant_identity(content, user_text=user_text)
        except Exception as exc:
            logger.warning('Quick-reply LLM call failed; using fallback response: %s', exc)
            return fallback
        return fallback

    @staticmethod
    def _day_period_label() -> str:
        current_hour = datetime.datetime.now().hour
        if 5 <= current_hour < 12:
            return 'morning'
        if 12 <= current_hour < 17:
            return 'afternoon'
        if 17 <= current_hour < 22:
            return 'evening'
        return 'night'

    def _handle_multi_office_query(self, text: str) -> str | None:
        result = self.agent_loop.run(text)
        if result.handled:
            return result.response
        return None

    def _extract_answer_with_llm(self, query: str, results: list[dict[str, object]]) -> str:
        """Use Gemini to extract a direct answer from search result snippets.

        This replaces hundreds of lines of regex-based extraction (IPL teams, etc.)
        with a single, universal LLM call that works for ANY factual query.
        """
        if not results:
            return ''
        evidence_parts: list[str] = []
        for (idx, item) in enumerate(results[:5], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get('title') or '').strip()
            snippet = str(item.get('snippet') or '').strip()
            if title or snippet:
                evidence_parts.append(f'{idx}. {title}: {snippet}' if title and snippet else f'{idx}. {title or snippet}')
        if not evidence_parts:
            return ''
        evidence = '\n'.join(evidence_parts)
        system_prompt = "You are a fact extraction engine. Given a user question and web search results, extract the direct answer in 1-2 clear sentences. If the search results don't contain a clear answer to the question, respond with exactly: NO_ANSWER\nRules:\n- Use ONLY information from the provided search results.\n- Be specific and concise.\n- Include relevant details (names, dates, numbers) from the results.\n- Do not add any information not present in the results."
        user_prompt = f'Question: {query}\n\nSearch results:\n{evidence}'
        try:
            answer = chat_complete(self.config, messages=[{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_prompt}], temperature=0.1, max_tokens=200, timeout=12).strip()
            if answer and 'NO_ANSWER' not in answer:
                return answer
        except Exception as exc:
            logger.debug('LLM answer extraction failed: %s', exc)
        return ''

    def _deterministic_search_response(self, query: str, *, user_text: str | None=None) -> str:
        payload = self.search_service.search_web_raw(query, max_results=5)
        results = payload.get('results') if isinstance(payload, dict) else []
        if not isinstance(results, list) or not results:
            return self.personality.finalize('I could not complete that web search request right now.', user_text=user_text or query)
        self._last_search_query = query
        self.memory.set('last_search_query', query)
        answer = self._extract_answer_with_llm(query, results)
        if not answer:
            answer = self._extract_ipl_winner_answer(query, results)
        if not answer:
            year = self._extract_ipl_year(query)
            lowered_query = (query or '').lower()
            if year and 'ipl' in lowered_query and re.search('\\b(who won|winner|champion|won)\\b', lowered_query):
                focused_query = f'IPL {year} winner'
                focused_payload = self.search_service.search_web_raw(focused_query, max_results=5)
                focused_results = focused_payload.get('results') if isinstance(focused_payload, dict) else []
                if isinstance(focused_results, list) and focused_results:
                    answer = self._extract_answer_with_llm(focused_query, focused_results)
                    if not answer:
                        answer = self._extract_ipl_winner_answer(focused_query, focused_results)
                    if answer:
                        self._last_search_query = focused_query
                        self.memory.set('last_search_query', focused_query)
        if answer:
            return self.personality.finalize(answer, user_text=user_text or query)
        lines = [f"Top web results for '{query}':"]
        for (index, item) in enumerate(results[:3], start=1):
            if not isinstance(item, dict):
                continue
            title = str(item.get('title') or '').strip()
            link = str(item.get('link') or '').strip()
            if title and link:
                lines.append(f'{index}. {title} — {link}')
            elif title:
                lines.append(f'{index}. {title}')
        return self.personality.finalize('\n'.join(lines), user_text=user_text or query)

    def _extract_ipl_winner_answer(self, query: str, results: list[dict[str, object]]) -> str:
        lowered_query = (query or '').lower()
        if 'ipl' not in lowered_query or not re.search('\\b(who won|winner|champion|won)\\b', lowered_query):
            return ''
        year = self._extract_ipl_year(lowered_query)
        if not year:
            return ''
        winner_patterns = (f"\\b([A-Z][A-Za-z0-9& .'-]{{2,60}}?)\\s+(?:won|wins|clinched|lifted|secured)\\s+(?:the\\s+)?(?:IPL|Indian Premier League)\\s*{year}\\b", f"\\b(?:IPL|Indian Premier League)\\s*{year}\\s*(?:winner|champion)\\s*[:\\-]?\\s*([A-Z][A-Za-z0-9& .'-]{{2,60}})\\b")
        team_aliases: tuple[tuple[str, tuple[str, ...]], ...] = (('Royal Challengers Bengaluru', ('royal challengers bengaluru', 'royal challengers bangalore', 'rcb')), ('Chennai Super Kings', ('chennai super kings', 'csk')), ('Mumbai Indians', ('mumbai indians', 'mi')), ('Kolkata Knight Riders', ('kolkata knight riders', 'kkr')), ('Sunrisers Hyderabad', ('sunrisers hyderabad', 'srh')), ('Rajasthan Royals', ('rajasthan royals', 'rr')), ('Delhi Capitals', ('delhi capitals', 'dc')), ('Punjab Kings', ('punjab kings', 'pbks', 'kings xi punjab')), ('Lucknow Super Giants', ('lucknow super giants', 'lsg')), ('Gujarat Titans', ('gujarat titans', 'gt')))
        for item in results:
            if not isinstance(item, dict):
                continue
            probe = f"{item.get('title') or ''}. {item.get('snippet') or ''}".strip()
            probe_lower = probe.lower()
            if year in probe_lower and re.search('\\b(won|wins|winner|champion|title|trophy|defeated|beat|clinched|lifted|secured)\\b', probe_lower):
                for (team_name, aliases) in team_aliases:
                    for alias in aliases:
                        alias_pattern = re.escape(alias)
                        if re.search(f'\\b{alias_pattern}\\b[^.\\n]{{0,40}}\\b(won|wins|winner|champion|title|trophy|defeated|beat|clinched|lifted|secured)\\b', probe_lower):
                            return f'Based on current web results, {team_name} won IPL {year} season.'
            for pattern in winner_patterns:
                match = re.search(pattern, probe, flags=re.IGNORECASE)
                if not match:
                    continue
                winner = re.sub('\\s+', ' ', str(match.group(1) or '')).strip(' .,-')
                if winner:
                    return f'Based on current web results, {winner} won IPL {year} season.'
        return ''

    def _handle_location_declaration(self, text: str) -> str:
        declared = self._extract_declared_location(text)
        if not declared:
            return 'I caught your location update, but missed the exact place.'
        self._set_session_location(declared)
        return f'Got it, Sir. I will use {declared} for local context.'

    def _is_browser_navigation_request(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False

        opens_browser = bool(re.search(r'\b(open|launch|start)\b.*\b(chrome|browser|firefox|edge|brave|opera)\b', lowered))
        navigation_intent = bool(re.search(r'\b(search|youtube|google|navigate|go to|website|url)\b', lowered))
        if opens_browser and navigation_intent:
            return True

        return bool(re.search(r'\b(go to|navigate to|open)\b\s+(?:https?://|www\.)', lowered))

    def _is_location_declaration_only(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False

        declared = self._extract_declared_location(lowered)
        if not declared:
            return False

        if any((matcher.search(lowered) for matcher in (self.WEATHER_RE, self.NEWS_RE, self.SPEEDTEST_RE, self.PUBLIC_IP_RE, self.LOCATION_RE, self.SEARCH_RE, self.CONNECTIVITY_RE, self.STATUS_RE, self.TEMPORAL_RE, self.UPDATE_RE))):
            return False

        return '?' not in lowered

    def _is_search_or_factual_request(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False

        if self._is_browser_navigation_request(lowered):
            return False

        if any((matcher.search(lowered) for matcher in (self.WEATHER_RE, self.PUBLIC_IP_RE, self.LOCATION_RE, self.SPEEDTEST_RE, self.CONNECTIVITY_RE, self.STATUS_RE, self.TEMPORAL_RE, self.UPDATE_RE))):
            return False

        document_service = getattr(self, 'document_service', None)
        if document_service is not None and (self._is_document_request(lowered) or self._is_document_question_request(lowered)):
            return False

        return bool(self._is_search_request(lowered) or self._is_factual_query(lowered) or self._is_short_ipl_season_prompt(lowered))

    def _is_search_policy_feedback(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False

        if not self.SEARCH_POLICY_RE.search(lowered):
            return False

        if self._is_generic_search_command(lowered) or bool(re.match(r'^\s*(then\s+|now\s+|please\s+)*search\b', lowered)):
            return False

        if any((matcher.search(lowered) for matcher in (self.SPEEDTEST_RE, self.PUBLIC_IP_RE, self.LOCATION_RE, self.WEATHER_RE, self.CONNECTIVITY_RE, self.NEWS_RE, self.STATUS_RE, self.TEMPORAL_RE, self.UPDATE_RE))):
            return False

        if re.search(r'\b(you should|you must|always|why not)\b', lowered):
            return '?' not in lowered

        if self._is_search_request(lowered) and ('?' in lowered or self.FACTUAL_RE.search(lowered)):
            return False

        return True

    def _handle_greeting(self, text: str) -> str:
        lowered = (text or '').strip().lower()
        if 'good afternoon' in lowered:
            period = 'afternoon'
        elif 'good evening' in lowered:
            period = 'evening'
        elif 'good night' in lowered:
            period = 'night'
        elif 'good morning' in lowered:
            period = 'morning'
        else:
            period = self._day_period_label()
        return f'Good {period}, Sir. What should we tackle first?'

    def _is_document_request(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False

        if getattr(self, 'document_service', None) is None:
            return False

        if self._is_document_picker_request(lowered):
            return True

        if self.FILE_MANAGER_RE.search(lowered):
            return False

        return bool(self.DOCUMENT_RE.search(lowered))

    def _is_document_picker_request(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False
        return bool(self.DOCUMENT_PICKER_RE.search(lowered))

    @staticmethod
    def _is_explicit_multi_file_compare_request(text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered:
            return False
        if not re.search('\\b(compare|comparison|versus|\\bvs\\b|difference|differences)\\b', lowered):
            return False
        return bool(re.search('\\b(?:the|these)?\\s*(?:\\d+|one|two|three|four|five|both|pair)\\s*(?:documents?|files?|docs?|pdfs?)\\b', lowered))

    def _is_document_question_request(self, text: str) -> bool:
        lowered = (text or '').strip().lower()
        if not lowered or getattr(self, 'document_service', None) is None:
            return False

        has_active_docs = bool(getattr(self.document_service, 'has_active_documents', lambda: False)())
        if not has_active_docs:
            return False

        if self.DOCUMENT_COMPARE_RE.search(lowered):
            if self._is_explicit_multi_file_compare_request(lowered):
                return False

            explicit_file_selection = re.search(r'\b(upload|select|choose|open|load|pick|analyze|process)\b', lowered)
            if explicit_file_selection:
                return False

            active_names = getattr(self.document_service, 'active_document_names', lambda: [])()
            active_doc_count = len(active_names) if isinstance(active_names, list) else 0
            return active_doc_count >= 2

        if self.DOCUMENT_RE.search(lowered):
            if re.search(r'\b(analyze|summarize|read|open|load|upload|select|process|compare)\b', lowered):
                return False

        if any((matcher.search(lowered) for matcher in (self.WEATHER_RE, self.PUBLIC_IP_RE, self.LOCATION_RE, self.SPEEDTEST_RE, self.STATUS_RE, self.TEMPORAL_RE, self.UPDATE_RE))):
            return False

        if self.DOCUMENT_QA_HINT_RE.search(lowered):
            return True

        if getattr(self, '_last_fact_source', '') in {'document', 'document_qa', 'document_compare'} and re.search(r'^(what|which|how|where|when|why|list|find|show|compare)\b', lowered):
            return True

        if self._is_factual_query(lowered):
            return False

        return False

    def _handle_document_question(self, text: str) -> str:
        if getattr(self, 'document_service', None) is None:
            return 'Document analysis is not available. Install the required dependencies first.'

        try:
            response = self.document_service.answer_question_for_display(text)
        except Exception as exc:
            return f'Document question answering encountered an error: {exc}'

        self._remember_fact(source='document_qa', query=text, handler=lambda q: self.document_service.answer_question_for_display(q))
        return response

    def _handle_document(self, text: str) -> str:
        if getattr(self, 'document_service', None) is None:
            return 'Document analysis is not available. Install the required dependencies first.'

        from services.document.file_selector import select_files, validate_file_path

        compare_mode = bool(self.DOCUMENT_COMPARE_RE.search(text or ''))

        self._emit_mode('processing')
        self._emit_text_delta('Opening file selector...')

        allow_cli_fallback = not any((callback is not None for callback in (getattr(self, '_on_mode_change', None), getattr(self, '_on_text_delta', None), getattr(self, '_on_api_activity', None))))

        selected_paths = select_files(prefer_gui=True, allow_multiple=compare_mode, allow_cli_fallback=allow_cli_fallback)

        if not selected_paths:
            return "No document was selected. Please say 'analyze document' again and choose a file."

        if compare_mode and len(selected_paths) < 2:
            return 'Please select at least two documents to compare.'

        validated_paths: list[str] = []
        for file_path in selected_paths:
            validated_path, error = validate_file_path(file_path)
            if error:
                return f'I cannot process that file: {error}'
            validated_paths.append(validated_path)

        if not validated_paths:
            return 'No valid document was selected.'

        from pathlib import Path
        if compare_mode:
            short_names = ', '.join((Path(path).name for path in validated_paths[:3]))
            self._emit_text_delta(f'Comparing {len(validated_paths)} documents: {short_names}...')
        else:
            file_name = Path(validated_paths[0]).name
            self._emit_text_delta(f' Analyzing {file_name}...')
        self._emit_text_delta(' This may take few moments, stay put.')

        try:
            if compare_mode:
                result = self.document_service.compare_documents_for_display(validated_paths, user_query=text)
            else:
                result = self.document_service.analyze_for_display(validated_paths[0], user_query=text)
        except Exception as exc:
            return f'Document analysis encountered an error: {exc}'

        if compare_mode:
            self._remember_fact(source='document_compare', query=text, handler=lambda q: self.document_service.compare_documents_for_display(validated_paths, user_query=q))
        else:
            selected_path = validated_paths[0]
            self._remember_fact(source='document', query=text, handler=lambda q: self.document_service.analyze_for_display(selected_path, user_query=q))
        return result

    def set_event_callbacks(self, *, on_mode_change: Callable[[str], None] | None=None, on_text_delta: Callable[[str], None] | None=None, on_api_activity: Callable[[bool], None] | None=None) -> None:
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
        response_to_close: object | None = None
        lock = getattr(self, '_stream_response_lock', None)
        if lock is not None:
            try:
                with lock:
                    response_to_close = getattr(self, '_active_stream_response', None)
                    self._active_stream_response = None
            except Exception:
                response_to_close = getattr(self, '_active_stream_response', None)
                self._active_stream_response = None
        else:
            response_to_close = getattr(self, '_active_stream_response', None)
            self._active_stream_response = None
        if response_to_close is not None:
            close_fn = getattr(response_to_close, 'close', None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass

    def _handle_tts_start(self) -> None:
        self._emit_mode('speaking')

    def _handle_tts_stop(self) -> None:
        if self._api_active:
            self._emit_mode('processing')
            return
        self._emit_mode('listening')

    def skip_current_reply(self) -> dict[str, object]:
        self._cancel_current_turn()
        turn_id = self.tts.interrupt()
        self._emit_api_activity(False)
        self._emit_mode('listening')
        return {'skipped': True, 'turn_id': turn_id, 'api_active': self._api_active, 'cancel_requested': True}

    def _trim_history(self) -> None:
        if len(self.messages) > self.config.max_context_messages + 1:
            self.messages = [self.messages[0]] + self.messages[-self.config.max_context_messages:]

    def _should_flush_speech_buffer(self, buffer: str) -> bool:
        stripped = buffer.strip()
        if not stripped:
            return False
        flush_chars = max(24, min(self.config.tts_chunk_chars, self.EARLY_CHUNK_MAX_CHARS))
        if stripped[-1] in '.?!':
            return True
        if len(stripped) >= flush_chars:
            return True
        return False

    def _next_speech_chunk(self, buffer: str, *, final: bool=False) -> tuple[str, str]:
        if not buffer:
            return ('', '')
        if final:
            return (buffer.strip(), '')
        if not self._should_flush_speech_buffer(buffer):
            return ('', buffer)
        boundaries = ['. ', '? ', '! ', ', ', '; ', ': ', '\n', ' ']
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
            return ('', buffer)
        return (chunk, rest)

    def _early_speech_chunk(self, buffer: str) -> tuple[str, str]:
        stripped = buffer.strip()
        if len(stripped) < self.EARLY_CHUNK_MIN_CHARS:
            return ('', buffer)
        target = max(self.EARLY_CHUNK_TARGET_CHARS, min(self.config.tts_chunk_chars, self.EARLY_CHUNK_MAX_CHARS))
        target = min(target, len(buffer))
        cutoff = target
        while cutoff > 0 and buffer[cutoff - 1] not in (' ', '\n', ',', '.', '?', '!', ';', ':'):
            cutoff -= 1
        if cutoff <= 0:
            cutoff = target
        chunk = buffer[:cutoff].strip()
        rest = buffer[cutoff:]
        if len(chunk) < self.EARLY_CHUNK_MIN_CHARS:
            return ('', buffer)
        return (chunk, rest)

    def _first_speech_chunk(self, buffer: str) -> tuple[str, str]:
        stripped = buffer.strip()
        if len(stripped) < self.FIRST_CHUNK_MIN_CHARS:
            return ('', buffer)
        preferred = max(self.FIRST_CHUNK_MIN_CHARS, min(self.config.tts_min_first_fragment_length, self.FIRST_CHUNK_MAX_CHARS))
        target = min(preferred, len(buffer))
        cutoff = target
        while cutoff > 0 and buffer[cutoff - 1] not in (' ', '\n', ',', '.', '?', '!', ';', ':'):
            cutoff -= 1
        if cutoff < self.FIRST_CHUNK_MIN_CHARS:
            cutoff = target
        chunk = buffer[:cutoff].strip()
        rest = buffer[cutoff:]
        if len(chunk) < self.FIRST_CHUNK_MIN_CHARS:
            return ('', buffer)
        return (chunk, rest)

    def _enqueue_speech_chunks(self, text: str, turn_id: int) -> bool:
        buffer = str(text or '').strip()
        if not buffer:
            return False
        queued_any = False
        (first_chunk, buffer) = self._first_speech_chunk(buffer)
        if first_chunk:
            queued_any = self.tts.enqueue_text(first_chunk, turn_id) or queued_any
        remainder = buffer.strip()
        if remainder and self.tts.enqueue_text(remainder, turn_id):
            queued_any = True
        return queued_any

    def _respond_local(self, user_text: str, response_text: str, *, persist_user: bool, stream_to_stdout: bool) -> str:
        if self._is_turn_cancelled():
            self._emit_api_activity(False)
            self._emit_mode('listening')
            return 'Request skipped.'
        normalized_response = self._enforce_assistant_identity(response_text, user_text=user_text)
        finalized = self.personality.finalize(normalized_response, user_text=user_text)
        if persist_user:
            self.messages.append({'role': 'user', 'content': user_text})
            self._trim_history()
        turn_id = self.tts.interrupt()
        self._emit_mode('processing')
        self._emit_api_activity(False)
        self._emit_text_delta(finalized)
        queued_any_speech = self._enqueue_speech_chunks(finalized, turn_id)
        if queued_any_speech and self.config.tts_wait_for_completion:
            self.tts.wait_for_turn_completion(turn_id, timeout_s=self.config.tts_turn_completion_timeout_seconds)
        elif not queued_any_speech or not self.config.tts_wait_for_completion:
            self._emit_mode('listening')
        if stream_to_stdout:
            print(f'{WHITE}JARVIS:{RESET} {finalized}')
        if persist_user:
            self.messages.append({'role': 'assistant', 'content': finalized})
            self._trim_history()
        self._last_assistant_reply = finalized
        return finalized

    def ask(self, text: str, *, persist_user: bool=True, stream_to_stdout: bool=True) -> str:
        with self._request_lock:
            return self._ask_locked(text, persist_user=persist_user, stream_to_stdout=stream_to_stdout)

    def _ask_locked(self, text: str, *, persist_user: bool=True, stream_to_stdout: bool=True) -> str:
        self._clear_turn_cancellation()
        cleaned = self.text_cleaner.clean(text)
        normalized_text = cleaned.cleaned_text or text
        self._capture_session_location(normalized_text)
        if cleaned.had_again and re.search(r"\b(weather|temperature|forecast)\b", normalized_text, re.IGNORECASE):
            has_city = bool(re.search('\\b(?:in|at|for)\\s+[a-zA-Z]', normalized_text, flags=re.IGNORECASE))
            if not has_city:
                last_city = self._get_session_location() or str(self.memory.get('last_city') or '').strip()
                if last_city:
                    normalized_text = f'weather in {last_city}'
        if not self._is_correction_request(normalized_text):
            self._last_user_query = normalized_text
        user_profile: dict[str, str] = {}
        user_name = (self.memory.get('user_name') or '').strip()
        if user_name:
            user_profile['name'] = user_name
        session_loc = self._get_session_location()
        if session_loc:
            user_profile['location'] = session_loc
        self.agent_loop.set_conversation_context(conversation_history=list(self.messages), user_profile=user_profile)
        agent_result = self.agent_loop.run(normalized_text)
        if agent_result.handled and agent_result.response:
            self._remember_fact(source='agent_loop', query=normalized_text, handler=lambda q: self.agent_loop.run(q).response)
            return self._respond_local(text, agent_result.response, persist_user=persist_user, stream_to_stdout=stream_to_stdout)
        if persist_user:
            self.messages.append({'role': 'user', 'content': normalized_text})
            self._trim_history()
            outbound_messages = list(self.messages)
        else:
            outbound_messages = self.messages + [{'role': 'user', 'content': normalized_text}]
        profile_context = self._build_profile_context()
        if profile_context and outbound_messages and (outbound_messages[-1].get('role') == 'user'):
            outbound_messages = outbound_messages[:-1] + [{'role': 'system', 'content': profile_context}] + [outbound_messages[-1]]
        turn_id = self.tts.interrupt()
        self._emit_mode('processing')
        self._emit_api_activity(True)
        try:
            raw_text = chat_complete(self.config, messages=outbound_messages, temperature=0.3, max_tokens=self.config.gemini_response_max_tokens, timeout=self.config.gemini_request_timeout_seconds).strip().strip('"')
            if self._is_turn_cancelled():
                self._emit_mode('listening')
                return 'Request skipped.'
            if not raw_text:
                raw_text = 'I did not receive a valid response. Please try again.'
            if self._is_conceptual_query(normalized_text) and (not self._is_explicit_detail_request(normalized_text)):
                raw_text = self._briefen_response(raw_text)
            raw_text = self._enforce_assistant_identity(raw_text, user_text=normalized_text)
            finalized = self.personality.finalize(raw_text, user_text=text)
            if stream_to_stdout:
                print(f'{WHITE}JARVIS:{RESET} {finalized}')
            self._emit_text_delta(finalized)
            if persist_user:
                self.messages.append({'role': 'assistant', 'content': finalized})
                self._trim_history()
            queued_any_speech = self._enqueue_speech_chunks(finalized, turn_id)
            if queued_any_speech and self.config.tts_wait_for_completion:
                self.tts.wait_for_turn_completion(turn_id, timeout_s=self.config.tts_turn_completion_timeout_seconds)
            elif not queued_any_speech or not self.config.tts_wait_for_completion:
                self._emit_mode('listening')
            self._last_assistant_reply = finalized
            return finalized
        finally:
            self._emit_api_activity(False)

    def greet(self, *, stream_to_stdout: bool=True) -> str:
        day_period = self._day_period_label()
        greeting = f'Good {day_period}, Sir. Ready when you are. What should we work on first?'
        return self._respond_local(user_text='', response_text=greeting, persist_user=False, stream_to_stdout=stream_to_stdout)

    def close(self) -> None:
        self.network_service.close()
        self.tts.close()