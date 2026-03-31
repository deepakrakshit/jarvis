from __future__ import annotations

import unittest
from unittest.mock import patch

from services.system.system_models import SystemControlConfig
from services.system.system_service import SystemControlService
from services.system.system_validator import SystemControlValidator


class SystemControlValidatorTest(unittest.TestCase):
    def test_clamps_volume_and_brightness_levels(self) -> None:
        validator = SystemControlValidator(SystemControlConfig(safe_mode=True))

        vol = validator.validate("set_volume", {"level": 145})
        bright = validator.validate("set_brightness", {"level": -7})

        self.assertTrue(vol.valid)
        self.assertEqual(vol.params.get("level"), 100)
        self.assertTrue(bright.valid)
        self.assertEqual(bright.params.get("level"), 0)

    def test_blocks_risky_actions(self) -> None:
        validator = SystemControlValidator(SystemControlConfig(safe_mode=True))

        blocked = validator.validate("shutdown", {})
        sleep_blocked = validator.validate("sleep", {})

        self.assertFalse(blocked.valid)
        self.assertTrue(blocked.blocked)
        self.assertFalse(sleep_blocked.valid)
        self.assertTrue(sleep_blocked.blocked)

    def test_window_actions_require_valid_app_name(self) -> None:
        validator = SystemControlValidator(SystemControlConfig(safe_mode=True))

        invalid = validator.validate("focus_window", {"app": ""})
        valid = validator.validate("focus_window", {"app": "Chrome"})

        self.assertFalse(invalid.valid)
        self.assertTrue(valid.valid)

    def test_natural_language_brightness_actions_are_canonicalized(self) -> None:
        validator = SystemControlValidator(SystemControlConfig(safe_mode=True))

        set_result = validator.validate("set the brightness to 50", {})
        lower_result = validator.validate("lower the brightness", {})
        underscore_result = validator.validate("set the brightness to 50_", {})
        still_phrase = validator.validate("its still 50, i want it 35 for brightness", {})

        self.assertTrue(set_result.valid)
        self.assertEqual(set_result.action, "set_brightness")
        self.assertEqual(set_result.params.get("level"), 50)

        self.assertTrue(lower_result.valid)
        self.assertEqual(lower_result.action, "decrease_brightness")
        self.assertEqual(lower_result.params.get("step"), 10)

        self.assertTrue(underscore_result.valid)
        self.assertEqual(underscore_result.action, "set_brightness")
        self.assertEqual(underscore_result.params.get("level"), 50)

        self.assertTrue(still_phrase.valid)
        self.assertEqual(still_phrase.action, "set_brightness")
        self.assertEqual(still_phrase.params.get("level"), 35)

    def test_max_min_volume_and_brightness_are_canonicalized(self) -> None:
        validator = SystemControlValidator(SystemControlConfig(safe_mode=True))

        max_volume = validator.validate("max volume", {})
        min_volume = validator.validate("min volume", {})
        max_brightness = validator.validate("max brightness", {})
        min_brightness = validator.validate("min brightness", {})

        self.assertTrue(max_volume.valid)
        self.assertEqual(max_volume.action, "set_volume")
        self.assertEqual(max_volume.params.get("level"), 100)

        self.assertTrue(min_volume.valid)
        self.assertEqual(min_volume.action, "set_volume")
        self.assertEqual(min_volume.params.get("level"), 0)

        self.assertTrue(max_brightness.valid)
        self.assertEqual(max_brightness.action, "set_brightness")
        self.assertEqual(max_brightness.params.get("level"), 100)

        self.assertTrue(min_brightness.valid)
        self.assertEqual(min_brightness.action, "set_brightness")
        self.assertEqual(min_brightness.params.get("level"), 0)


class SystemControlServiceTest(unittest.TestCase):
    def test_blocks_more_than_three_actions_per_request(self) -> None:
        service = SystemControlService(SystemControlConfig(safe_mode=True))

        result = service.control(action="set_volume", params={"level": 40, "actions_in_request": 4})

        self.assertFalse(bool(result.get("success")))
        self.assertEqual(result.get("error"), "too_many_actions_in_request")

    def test_dispatches_safe_action_and_logs(self) -> None:
        service = SystemControlService(SystemControlConfig(safe_mode=True))

        with patch.object(service, "_dispatcher", {"set_volume": lambda _a, _p: {
            "status": "success",
            "action": "set_volume",
            "success": True,
            "verified": True,
            "error": "",
            "state": {"volume": 60},
            "message": "Volume increased to 60%",
        }}):
            result = service.control(action="set_volume", params={"level": 60})

        self.assertTrue(bool(result.get("success")))
        self.assertTrue(bool(result.get("verified")))
        self.assertEqual(result.get("action"), "set_volume")
        self.assertGreaterEqual(len(service.get_action_logs()), 1)

    def test_reports_blocked_sleep_in_safe_mode(self) -> None:
        service = SystemControlService(SystemControlConfig(safe_mode=True))

        result = service.control(action="sleep", params={})

        self.assertFalse(bool(result.get("success")))
        self.assertEqual(result.get("status"), "blocked")
        self.assertEqual(result.get("error"), "action_blocked_safe_mode")

    def test_service_handles_natural_language_brightness_request(self) -> None:
        service = SystemControlService(SystemControlConfig(safe_mode=True))

        with patch.object(service, "_dispatcher", {"set_brightness": lambda _a, params: {
            "status": "success",
            "action": "set_brightness",
            "success": True,
            "verified": True,
            "error": "",
            "state": {"brightness": int(params.get("level", 0))},
            "message": f"Brightness set to {int(params.get('level', 0))}%.",
        }}):
            result = service.control(action="set the brightness to 50", params={})

        self.assertTrue(bool(result.get("success")))
        self.assertEqual(result.get("action"), "set_brightness")
        self.assertEqual((result.get("state") or {}).get("brightness"), 50)


if __name__ == "__main__":
    unittest.main()
