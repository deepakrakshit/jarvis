from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.synthesizer import Synthesizer
from core.settings import AppConfig


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

    def test_file_controller_bulk_fallback_reports_verified_counts(self) -> None:
        response = Synthesizer._fallback_response(
            {
                "file_controller": {
                    "tool": "file_controller",
                    "success": True,
                    "output": {
                        "status": "success",
                        "action": "create_random_text_files",
                        "success": True,
                        "verified": True,
                        "error": "",
                        "message": "ok",
                        "data": {
                            "path": "StressTest",
                            "target_count": 50,
                            "total_available": 50,
                            "created_count": 45,
                            "existing_count": 5,
                            "overwritten_count": 0,
                            "failed_count": 0,
                        },
                    },
                    "error": "",
                }
            }
        )

        self.assertIn("50/50", response)
        self.assertIn("created 45", response)

    def test_cmd_control_failure_fallback_reports_exit_code(self) -> None:
        response = Synthesizer._fallback_response(
            {
                "cmd_control": {
                    "tool": "cmd_control",
                    "success": False,
                    "output": {
                        "status": "error",
                        "action": "run_command",
                        "success": False,
                        "verified": False,
                        "error": "command_failed",
                        "message": "Command returned a non-zero exit code.",
                        "exit_code": 1,
                        "timed_out": False,
                        "stdout": "",
                        "stderr": "syntax error near unexpected token",
                    },
                    "error": "command_failed",
                }
            }
        )

        self.assertIn("exit code 1", response)
        self.assertIn("syntax error", response)

    def test_synthesize_bypasses_llm_for_deterministic_file_tool_outputs(self) -> None:
        synth = Synthesizer(AppConfig.from_env(".env"))
        tool_outputs = {
            "file_controller": {
                "tool": "file_controller",
                "success": True,
                "output": {
                    "status": "success",
                    "action": "create_random_text_files",
                    "success": True,
                    "verified": True,
                    "error": "",
                    "message": "ok",
                    "data": {
                        "path": "StressTest",
                        "target_count": 50,
                        "total_available": 50,
                        "created_count": 45,
                        "existing_count": 5,
                        "overwritten_count": 0,
                        "failed_count": 0,
                    },
                },
                "error": "",
            }
        }

        with patch("agent.synthesizer.chat_complete", side_effect=AssertionError("LLM should not be called")):
            response = synth.synthesize("create 50 files", tool_outputs)

        self.assertIn("50/50", response)

    def test_fallback_dedupes_repeated_error_lines(self) -> None:
        response = Synthesizer._fallback_response(
            {
                "file_controller": {
                    "tool": "file_controller",
                    "success": False,
                    "output": {
                        "status": "error",
                        "action": "read",
                        "success": False,
                        "verified": False,
                        "error": "invalid_path",
                        "message": "File not found: setup.py",
                    },
                    "error": "invalid_path",
                },
                "file_controller_2": {
                    "tool": "file_controller",
                    "success": False,
                    "output": {
                        "status": "error",
                        "action": "read",
                        "success": False,
                        "verified": False,
                        "error": "invalid_path",
                        "message": "File not found: setup.py",
                    },
                    "error": "invalid_path",
                },
            }
        )

        self.assertEqual(response.count("File not found: setup.py"), 1)

    def test_app_control_fallback_prefers_tool_message(self) -> None:
        response = Synthesizer._render_fallback_payload(
            {
                "tool": "app_control",
                "success": True,
                "output": {
                    "status": "success",
                    "action": "close",
                    "app": "Calculator",
                    "verified": True,
                    "message": "Calculator was already not running.",
                },
            }
        )

        self.assertIn("already not running", response)


if __name__ == "__main__":
    unittest.main()
