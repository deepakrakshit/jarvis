from __future__ import annotations

import unittest
from unittest.mock import patch

from core.settings import AppConfig
from services.weather_service import WeatherService


class _PersonalityStub:
    @staticmethod
    def finalize(text: str, user_text: str = "") -> str:
        return text


class _HumorStub:
    @staticmethod
    def weather_line(**_: object) -> str:
        return ""


class _MemoryStub:
    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    def get(self, key: str) -> object:
        return self._store.get(key, "")

    def set(self, key: str, value: object) -> None:
        self._store[key] = value


class _NetworkStub:
    def get_location_from_ip(self):
        return None


class WeatherServiceForecastStressTest(unittest.TestCase):
    def _service(self) -> WeatherService:
        return WeatherService(
            config=AppConfig.from_env(".env"),
            network_service=_NetworkStub(),
            personality=_PersonalityStub(),
            humor=_HumorStub(),
            memory=_MemoryStub(),
        )

    def test_forecast_for_tomorrow_uses_daily_data(self) -> None:
        service = self._service()

        payload = {
            "success": True,
            "tool_location_label": "Delhi, India",
            "tool_location": "Delhi",
            "latitude": 28.61,
            "longitude": 77.23,
            "timezone": "Asia/Kolkata",
            "temperature_c": 26.0,
            "feels_like_c": 27.0,
            "humidity_percent": 58.0,
            "wind_kmh": 8.0,
            "weather_code": 2,
            "condition": "partly cloudy",
        }
        daily = {
            "weather_code": [2, 3],
            "temperature_2m_max": [32.0, 33.0],
            "temperature_2m_min": [21.0, 22.0],
            "precipitation_probability_max": [10.0, 35.0],
        }

        with patch.object(service, "get_weather_data", return_value=payload), patch.object(service, "_fetch_daily_weather", return_value=daily):
            response = service.get_weather_brief("forecast for tomorrow")

        self.assertIn("Forecast for Delhi, India tomorrow", response)
        self.assertIn("22.0C to 33.0C", response)
        self.assertIn("precipitation chance 35%", response)

    def test_rain_today_query_uses_precipitation_probability(self) -> None:
        service = self._service()

        payload = {
            "success": True,
            "tool_location_label": "Mumbai, India",
            "tool_location": "Mumbai",
            "latitude": 19.07,
            "longitude": 72.88,
            "timezone": "Asia/Kolkata",
            "temperature_c": 30.0,
            "feels_like_c": 33.0,
            "humidity_percent": 72.0,
            "wind_kmh": 10.0,
            "weather_code": 1,
            "condition": "mainly clear",
        }
        daily = {
            "weather_code": [1, 2],
            "temperature_2m_max": [35.0, 34.0],
            "temperature_2m_min": [26.0, 25.0],
            "precipitation_probability_max": [40.0, 20.0],
        }

        with patch.object(service, "get_weather_data", return_value=payload), patch.object(service, "_fetch_daily_weather", return_value=daily):
            response = service.get_weather_brief("will it rain today")

        self.assertEqual(response, "There is a 40% chance of precipitation in Mumbai, India today.")


if __name__ == "__main__":
    unittest.main()
