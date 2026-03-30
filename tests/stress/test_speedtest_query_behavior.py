from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from core.personality import PersonalityEngine
from core.settings import AppConfig
from services.network_service import NetworkService, SpeedtestResult


class SpeedtestQueryBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = NetworkService(AppConfig.from_env(".env"), PersonalityEngine())

    def test_default_speedtest_query_runs_synchronously(self) -> None:
        self.service.run_speedtest_now = lambda: "sync-speedtest"  # type: ignore[assignment]
        response = self.service.handle_speedtest_query("test internet speed")
        self.assertEqual(response, "sync-speedtest")

    def test_result_query_runs_sync_when_no_snapshot(self) -> None:
        self.service.is_speedtest_running = lambda: False  # type: ignore[assignment]
        self.service.get_last_speedtest_snapshot = lambda: None  # type: ignore[assignment]
        self.service.run_speedtest_now = lambda: "sync-speedtest"  # type: ignore[assignment]

        response = self.service.handle_speedtest_query("what are the speed test results now")
        self.assertEqual(response, "sync-speedtest")

    def test_result_query_uses_cached_result_when_snapshot_exists(self) -> None:
        self.service.is_speedtest_running = lambda: False  # type: ignore[assignment]
        self.service.get_last_speedtest_snapshot = lambda: {  # type: ignore[assignment]
            "download_mbps": 100.0,
            "upload_mbps": 50.0,
            "ping_ms": 12.0,
            "timestamp": 1.0,
        }
        self.service.get_speedtest_result = lambda: "cached-result"  # type: ignore[assignment]

        response = self.service.handle_speedtest_query("show speed result")
        self.assertEqual(response, "cached-result")

    def test_background_keyword_keeps_async_mode(self) -> None:
        self.service.start_speedtest = lambda: "background-speedtest"  # type: ignore[assignment]
        response = self.service.handle_speedtest_query("run speed test in background")
        self.assertEqual(response, "background-speedtest")

    def test_assessment_keyword_uses_assessment_path(self) -> None:
        self.service.get_speedtest_assessment = lambda: "assessment"  # type: ignore[assignment]
        response = self.service.handle_speedtest_query("is my internet speed good")
        self.assertEqual(response, "assessment")

    def test_compact_speedtest_result_contains_only_download_upload(self) -> None:
        message = self.service._render_speedtest_result(
            SpeedtestResult(
                download_mbps=92.5,
                upload_mbps=35.4,
                ping_ms=16.2,
                timestamp=time.time(),
            )
        )
        self.assertIn("Download Speed:", message)
        self.assertIn("Upload Speed:", message)
        self.assertNotIn("Ping:", message)

    def test_sync_speedtest_waits_for_minimum_duration(self) -> None:
        self.service._execute_speedtest_once = lambda: (  # type: ignore[assignment]
            SpeedtestResult(
                download_mbps=80.0,
                upload_mbps=20.0,
                ping_ms=10.0,
                timestamp=time.time(),
            ),
            None,
        )

        with patch("services.network_service.time.sleep") as mocked_sleep:
            self.service.run_speedtest_now()

        mocked_sleep.assert_called_once()
        self.assertGreater(float(mocked_sleep.call_args.args[0]), 0.0)


if __name__ == "__main__":
    unittest.main()