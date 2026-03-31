from __future__ import annotations

import unittest

from agent.synthesizer import Synthesizer


class SynthesizerFallbackStressTest(unittest.TestCase):
    def test_app_control_fallback_is_human_readable(self) -> None:
        response = Synthesizer._fallback_response(
            {
                "app_control": {
                    "tool": "app_control",
                    "success": True,
                    "output": {
                        "status": "success",
                        "action": "close",
                        "app": "Calculator",
                        "verified": True,
                    },
                    "error": "",
                }
            }
        )

        self.assertEqual(response, "Calculator has been closed successfully.")

    def test_system_control_fallback_uses_verification_safe_wording(self) -> None:
        response = Synthesizer._fallback_response(
            {
                "system_control": {
                    "tool": "system_control",
                    "success": True,
                    "output": {
                        "status": "success",
                        "action": "set_volume",
                        "success": True,
                        "verified": False,
                        "error": "",
                        "message": "Volume adjusted via keyboard events.",
                    },
                    "error": "",
                }
            }
        )

        self.assertIn("could not verify completion", response)


if __name__ == "__main__":
    unittest.main()
