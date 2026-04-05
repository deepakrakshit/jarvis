from __future__ import annotations

import unittest

from core.settings import AppConfig
from services.actions.computer_control import ComputerController


class ComputerControlTest(unittest.TestCase):
    def test_sanitize_url_rejects_whitespace_payload(self) -> None:
        self.assertEqual(ComputerController._sanitize_url("not a url"), "")

    def test_infer_browser_bootstrap_builds_youtube_results_url(self) -> None:
        controller = ComputerController(AppConfig.from_env(".env"), dry_run=True)
        browser, url = controller._infer_browser_bootstrap(
            "open chrome and search on youtube about python tutorials",
            {},
        )

        self.assertEqual(browser, "chrome")
        self.assertIn("youtube.com/results?search_query=python+tutorials", url)

    def test_extract_search_query_handles_google_phrase(self) -> None:
        query = ComputerController._extract_search_query("open chrome and search for jarvis on google")
        self.assertEqual(query, "jarvis")

    def test_notepad_goal_uses_deterministic_shortcut_script(self) -> None:
        controller = ComputerController(AppConfig.from_env(".env"), dry_run=True)
        script = controller._build_shortcut_script(
            "open notepad and create a new file and write a python program for a calculator",
            {},
        )

        self.assertTrue(script)
        self.assertEqual(script[0][0], "open_app_manual")
        self.assertTrue(any(step[0] == "smart_type" for step in script))

    def test_notepad_write_close_shortcut_types_requested_text_and_closes(self) -> None:
        controller = ComputerController(AppConfig.from_env(".env"), dry_run=True)
        script = controller._build_shortcut_script(
            "Open Notepad, write 'Stress Test Successful', and close it.",
            {},
        )

        self.assertTrue(script)
        self.assertEqual(script[0][0], "open_app_manual")
        typed_steps = [step for step in script if step[0] == "smart_type"]
        self.assertTrue(typed_steps)
        self.assertEqual(typed_steps[0][1].get("text"), "Stress Test Successful")
        self.assertTrue(any(step[0] == "hotkey" and step[1].get("keys") == "alt+f4" for step in script))

    def test_planner_hotkey_validation_accepts_key_alias(self) -> None:
        controller = ComputerController(AppConfig.from_env(".env"), dry_run=True)
        is_valid, reason = controller._validate_planner_action("hotkey", {"key": "alt+f4"})
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")

    def test_autonomous_task_prefers_planner_before_shortcuts(self) -> None:
        controller = ComputerController(AppConfig.from_env(".env"), dry_run=True)

        controller._build_shortcut_script = (  # type: ignore[method-assign]
            lambda _goal, _params: [("open_app_manual", {"app": "notepad"})]
        )

        decisions = iter(
            [
                {"action": "wait", "args": {"seconds": 0.1}, "reason": "load"},
                {"action": "done", "args": {}, "reason": "completed"},
            ]
        )
        controller._decide_next_action = (  # type: ignore[method-assign]
            lambda **_kwargs: next(decisions)
        )

        shortcut_calls = {"count": 0}

        def _fake_run_shortcut_script(**_kwargs: object) -> dict[str, object]:
            shortcut_calls["count"] += 1
            return {
                "status": "success",
                "action": "autonomous_task",
                "success": True,
                "verified": True,
                "message": "shortcut",
                "error": "",
                "state": {},
            }

        controller._run_shortcut_script = _fake_run_shortcut_script  # type: ignore[method-assign]

        result = controller._autonomous_task({"goal": "open notepad", "max_steps": 3})

        self.assertTrue(bool(result.get("success")))
        self.assertEqual(shortcut_calls["count"], 0)
        self.assertEqual(result.get("message"), "Autonomous task completed.")

    def test_autonomous_task_uses_shortcut_fallback_after_planner_failures(self) -> None:
        controller = ComputerController(AppConfig.from_env(".env"), dry_run=True)

        controller._build_shortcut_script = (  # type: ignore[method-assign]
            lambda _goal, _params: [("wait", {"seconds": 0.1})]
        )
        controller._decide_next_action = (  # type: ignore[method-assign]
            lambda **_kwargs: {"action": "fail", "args": {}, "reason": "Model response could not be parsed."}
        )

        shortcut_calls = {"count": 0}

        def _fake_run_shortcut_script(**_kwargs: object) -> dict[str, object]:
            shortcut_calls["count"] += 1
            return {
                "status": "success",
                "action": "autonomous_task",
                "success": True,
                "verified": True,
                "message": "Autonomous task completed using fallback deterministic steps after planner retries.",
                "error": "",
                "state": {"final_reason": "planner_fallback_shortcut"},
            }

        controller._run_shortcut_script = _fake_run_shortcut_script  # type: ignore[method-assign]

        result = controller._autonomous_task({"goal": "open notepad", "max_steps": 3})

        self.assertTrue(bool(result.get("success")))
        self.assertEqual(shortcut_calls["count"], 1)
        self.assertEqual((result.get("state") or {}).get("final_reason"), "planner_fallback_shortcut")

    def test_reason_marker_detects_planner_failure(self) -> None:
        self.assertTrue(ComputerController._reason_indicates_planner_issue("rate limit 429 from planner"))
        self.assertFalse(ComputerController._reason_indicates_planner_issue("completed all steps"))


if __name__ == "__main__":
    unittest.main()
