from __future__ import annotations

import unittest
from unittest.mock import patch

from services.system.volume_control import VolumeController


class VolumeControlStressTest(unittest.TestCase):
    def test_set_volume_falls_back_to_keyboard_events_when_dependencies_missing(self) -> None:
        controller = VolumeController()

        with patch.object(controller, "_endpoint", return_value=None), patch("services.system.volume_control.shutil.which", return_value=None), patch.object(
            controller,
            "_key_press",
            return_value=None,
        ):
            result = controller.execute("set_volume", {"level": 40})

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("action"), "set_volume")
        self.assertTrue(bool(result.get("success")))
        self.assertFalse(bool(result.get("verified")))
        self.assertEqual(result.get("error"), "")
        self.assertIn("keyboard events", str(result.get("message") or "").lower())


if __name__ == "__main__":
    unittest.main()
