from __future__ import annotations

import logging
import re
from typing import Any

from core.humor import HumorEngine
from core.personality import PersonalityEngine
from core.settings import AppConfig
from memory.store import MemoryStore
from services.network_service import NetworkService
from services.utils.http_client import HttpClient
from services.utils.location_utils import LocationInfo
from utils.geocode_resolver import resolve_geocode
from utils.text_cleaner import TextCleaner

logger = logging.getLogger(__name__)


_WEATHER_CODE_MAP: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


class WeatherService:
    """Weather module backed by Open-Meteo APIs."""

    def __init__(
        self,
        config: AppConfig,
        network_service: NetworkService,
        personality: PersonalityEngine,
        humor: HumorEngine,
        memory: MemoryStore,
    ) -> None:
        self.config = config
        self.network_service = network_service
        self.personality = personality
        self.humor = humor
        self.memory = memory
        self.text_cleaner = TextCleaner()
        self.http = HttpClient(timeout=8.0)

    @staticmethod
    def _extract_city(query: str) -> str | None:
        patterns = [
            r"\bweather\s+(?:in|at|for)\s+([a-zA-Z\s\-]+)",
            r"\btemperature\s+(?:in|at|for)\s+([a-zA-Z\s\-]+)",
            r"\bforecast\s+(?:in|at|for)\s+([a-zA-Z\s\-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if match:
                city = match.group(1).strip(" .,!?")
                city = re.split(r"\b(?:and|also|please|currently|right now)\b", city, maxsplit=1, flags=re.IGNORECASE)[0]
                city = city.strip(" .,!?")
                if city:
                    return city
        return None

    @staticmethod
    def _normalize_location_text(text: str) -> str:
        collapsed = re.sub(r"\s+", " ", (text or "").strip())
        return collapsed.strip(" .,!?;:")

    @staticmethod
    def _is_local_request(query: str) -> bool:
        lowered = query.lower()
        local_markers = [
            "weather here",
            "weather now",
            "weather outside",
            "local weather",
            "weather at my location",
            "weather near me",
            "temperature here",
        ]
        return any(marker in lowered for marker in local_markers)

    @staticmethod
    def _describe(code: int) -> str:
        return _WEATHER_CODE_MAP.get(code, "variable conditions")

    def _format_weather_response(
        self,
        *,
        location: LocationInfo,
        temp_c: float,
        feels_c: float,
        humidity: float,
        wind_kmh: float,
        code: int,
        user_text: str,
    ) -> str:
        desc = self._describe(code)
        advisory = self.humor.weather_line(
            temp_c=temp_c,
            condition=desc,
            weather_code=code,
            context=location.label,
        )

        message = (
            f"Weather for {location.label}: {temp_c:.1f}C, feels like {feels_c:.1f}C, "
            f"{desc}, humidity {humidity:.0f}%, wind {wind_kmh:.1f} km/h. {advisory}"
        )
        return self.personality.finalize(message, user_text=user_text)

    def _resolve_location(self, user_text: str) -> tuple[LocationInfo | None, str | None]:
        cleaned = self.text_cleaner.clean(user_text)
        query = cleaned.cleaned_text or user_text

        if self._is_local_request(query):
            location = self.network_service.get_location_from_ip()
            if not location:
                return None, "I could not resolve local weather because IP location lookup failed."
            if location.city:
                self.memory.set("last_city", location.city)
            return location, None

        city = self._extract_city(query)
        if cleaned.had_again and not city:
            remembered_city = str(self.memory.get("last_city") or "").strip()
            if remembered_city:
                city = remembered_city

        if city:
            user_location = self.network_service.get_location_from_ip()
            user_country = user_location.country if user_location else None
            location = resolve_geocode(
                self.http,
                city,
                user_country=user_country,
                query=query,
            )
            if not location:
                return None, f"I could not geocode {city}. Try another city name."
            if location.city:
                self.memory.set("last_city", location.city)
            return location, None

        # If user asked generic weather, default to local location.
        location = self.network_service.get_location_from_ip()
        if location:
            if location.city:
                self.memory.set("last_city", location.city)
            return location, None

        return None, "I need a city name or local IP location to fetch weather."

    def _fetch_current_weather(self, location: LocationInfo) -> dict[str, Any] | None:
        payload = self.http.get_json(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": location.latitude,
                "longitude": location.longitude,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                "timezone": location.timezone or "auto",
            },
        )
        if not payload:
            return None

        current = payload.get("current")
        if isinstance(current, dict):
            return current
        return None

    def get_weather_data(
        self,
        *,
        query: str,
        explicit_location: str = "",
        session_location: str = "",
        allow_ip_fallback: bool = True,
    ) -> dict[str, Any]:
        """Return structured weather payload for agent execution and validation."""
        cleaned = self.text_cleaner.clean(query)
        query_text = cleaned.cleaned_text or query

        explicit = self._normalize_location_text(explicit_location)
        parsed_query_city = self._normalize_location_text(self._extract_city(query_text) or "")
        session_loc = self._normalize_location_text(session_location)

        location: LocationInfo | None = None
        resolution_source = ""
        requested_location = ""

        # Priority:
        # 1) explicit location argument
        # 2) query-provided location phrase
        # 3) session location
        # 4) ip fallback
        for candidate, source in (
            (explicit, "explicit_location"),
            (parsed_query_city, "query_location"),
            (session_loc, "session_location"),
        ):
            if not candidate or candidate.lower() in {"here", "local", "my location", "current location"}:
                continue

            resolved = resolve_geocode(
                self.http,
                candidate,
                user_country=None,
                query=query_text,
            )
            if resolved:
                location = resolved
                requested_location = candidate
                resolution_source = source
                break

        if location is None and allow_ip_fallback:
            location = self.network_service.get_location_from_ip()
            if location:
                requested_location = requested_location or self._normalize_location_text(location.city or location.label)
                resolution_source = "ip_fallback"

        if not location:
            return {
                "success": False,
                "error": "location_unresolved",
                "query": query_text,
                "requested_location": requested_location,
                "tool_location": "",
                "tool_location_label": "",
                "resolution_source": resolution_source,
            }

        current = self._fetch_current_weather(location)
        if not current:
            return {
                "success": False,
                "error": "weather_provider_unavailable",
                "query": query_text,
                "requested_location": requested_location,
                "tool_location": location.city,
                "tool_location_label": location.label,
                "resolution_source": resolution_source,
            }

        try:
            temp_c = float(current.get("temperature_2m"))
            feels_c = float(current.get("apparent_temperature"))
            humidity = float(current.get("relative_humidity_2m"))
            wind_kmh = float(current.get("wind_speed_10m"))
            code = int(current.get("weather_code"))
        except Exception:
            logger.exception("Weather payload parsing failed")
            return {
                "success": False,
                "error": "weather_payload_incomplete",
                "query": query_text,
                "requested_location": requested_location,
                "tool_location": location.city,
                "tool_location_label": location.label,
                "resolution_source": resolution_source,
            }

        if location.city:
            self.memory.set("last_city", location.city)

        return {
            "success": True,
            "error": "",
            "query": query_text,
            "requested_location": requested_location,
            "tool_location": self._normalize_location_text(location.city or location.label),
            "tool_location_label": location.label,
            "resolution_source": resolution_source,
            "temperature_c": round(temp_c, 1),
            "feels_like_c": round(feels_c, 1),
            "humidity_percent": round(humidity, 1),
            "wind_kmh": round(wind_kmh, 1),
            "weather_code": code,
            "condition": self._describe(code),
        }

    def get_weather_brief(self, user_text: str) -> str:
        payload = self.get_weather_data(
            query=user_text,
            explicit_location="",
            session_location=str(self.memory.get("last_city") or "").strip(),
            allow_ip_fallback=True,
        )
        if not bool(payload.get("success")):
            return self.personality.finalize(
                "I could not fetch weather data right now.",
                user_text=user_text,
            )

        temp_c = float(payload.get("temperature_c") or 0.0)
        feels_c = float(payload.get("feels_like_c") or 0.0)
        humidity = float(payload.get("humidity_percent") or 0.0)
        wind_kmh = float(payload.get("wind_kmh") or 0.0)
        condition = str(payload.get("condition") or "variable conditions")
        weather_code = int(payload.get("weather_code") or 0)
        label = str(payload.get("tool_location_label") or payload.get("tool_location") or "your area")

        advisory = self.humor.weather_line(
            temp_c=temp_c,
            condition=condition,
            weather_code=weather_code,
            context=label,
        )

        message = (
            f"Weather for {label}: {temp_c:.1f}C, feels like {feels_c:.1f}C, "
            f"{condition}, humidity {humidity:.0f}%, wind {wind_kmh:.1f} km/h. {advisory}"
        )
        return self.personality.finalize(message, user_text=user_text)
