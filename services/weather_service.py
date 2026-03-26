from __future__ import annotations

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
                if city:
                    return city
        return None

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

    def get_weather_brief(self, user_text: str) -> str:
        location, location_error = self._resolve_location(user_text)
        if not location:
            return self.personality.finalize(location_error or "Weather lookup failed before launch.", user_text=user_text)

        current = self._fetch_current_weather(location)
        if not current:
            return self.personality.finalize("Open-Meteo did not return weather data right now.", user_text=user_text)

        try:
            temp_c = float(current.get("temperature_2m"))
            feels_c = float(current.get("apparent_temperature"))
            humidity = float(current.get("relative_humidity_2m"))
            wind_kmh = float(current.get("wind_speed_10m"))
            code = int(current.get("weather_code"))
        except Exception:
            return self.personality.finalize("Weather response was incomplete. Please ask once more.", user_text=user_text)

        return self._format_weather_response(
            location=location,
            temp_c=temp_c,
            feels_c=feels_c,
            humidity=humidity,
            wind_kmh=wind_kmh,
            code=code,
            user_text=user_text,
        )
