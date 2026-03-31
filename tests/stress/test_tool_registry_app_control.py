from __future__ import annotations

import unittest

from agent.tool_registry import build_default_tool_registry


class _NetworkStub:
    def handle_speedtest_query(self, _query: str) -> str:
        return "ok"

    def get_public_ip(self) -> str:
        return "127.0.0.1"

    def describe_ip_location(self) -> dict[str, str]:
        return {"city": "X"}

    def get_system_status_snapshot(self) -> dict[str, object]:
        return {"cpu_percent": 1.0}

    def get_temporal_snapshot(self) -> dict[str, object]:
        return {"time": "now"}

    def get_update_status(self) -> dict[str, object]:
        return {"status": "ok"}


class _WeatherStub:
    def get_weather_data(self, **_: object) -> dict[str, object]:
        return {"success": True}


class _SearchStub:
    def search_web_raw(self, _query: str, max_results: int = 5) -> dict[str, object]:
        return {"query": "q", "results": [], "error": ""}


class ToolRegistryAppControlTest(unittest.TestCase):
    def test_app_control_registered_with_schema_and_non_parallel_flag(self) -> None:
        registry = build_default_tool_registry(
            network_service=_NetworkStub(),
            weather_service=_WeatherStub(),
            search_service=_SearchStub(),
            document_service=None,
            memory_store=None,
            get_session_location=None,
            set_session_location=None,
        )

        definition = registry.get("app_control")

        self.assertIsNotNone(definition)
        assert definition is not None
        self.assertFalse(definition.safe_to_parallelize)
        self.assertEqual(definition.timeout_seconds, 35.0)

        valid, reason = registry.validate_args("app_control", {"action": "open", "app_name": "chrome"})
        self.assertTrue(valid, reason)

        invalid, _ = registry.validate_args("app_control", {"app_name": "chrome"})
        self.assertFalse(invalid)


if __name__ == "__main__":
    unittest.main()
