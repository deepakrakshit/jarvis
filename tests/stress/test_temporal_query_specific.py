from __future__ import annotations

import unittest

from core.settings import AppConfig
from services.network_service import NetworkService


class _PersonalityStub:
    @staticmethod
    def finalize(text: str, user_text: str = "") -> str:
        return text


class TemporalQuerySpecificTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = NetworkService(AppConfig.from_env(".env"), _PersonalityStub())

    def test_time_query_returns_time_focused_text(self) -> None:
        reply = self.service.get_temporal_snapshot("what time is it")
        self.assertIn("Local time is", reply)
        self.assertNotIn("and today is", reply)

    def test_date_query_returns_date_focused_text(self) -> None:
        reply = self.service.get_temporal_snapshot("tell me today's date")
        self.assertIn("Today's date is", reply)

    def test_day_query_returns_day_focused_text(self) -> None:
        reply = self.service.get_temporal_snapshot("what day is it today")
        self.assertIn("Today is", reply)

    def test_month_query_returns_month_focused_text(self) -> None:
        reply = self.service.get_temporal_snapshot("what month is this")
        self.assertIn("Current month is", reply)

    def test_year_query_returns_year_focused_text(self) -> None:
        reply = self.service.get_temporal_snapshot("what year is this")
        self.assertIn("Current year is", reply)


if __name__ == "__main__":
    unittest.main()
