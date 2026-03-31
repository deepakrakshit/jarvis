from __future__ import annotations

import unittest

from agent.agent_loop import AgentLoop
from agent.planner import PlanStep
from agent.validator import ValidationResult


class _PlannerStub:
    def __init__(self) -> None:
        self.called = False

    def plan(self, _query: str):
        self.called = True
        return None


class _ExecutorStub:
    def __init__(self) -> None:
        self.last_plan: list[PlanStep] = []

    def execute(self, plan: list[PlanStep]) -> dict[str, dict]:
        self.last_plan = list(plan)
        return {
            "system_control": {
                "tool": "system_control",
                "args": plan[0].args,
                "success": True,
                "output": {
                    "status": "success",
                    "action": "set_brightness",
                    "success": True,
                    "verified": True,
                    "error": "",
                    "state": {"brightness": 35},
                    "message": "Brightness set to 35%.",
                },
                "error": "",
                "duration_ms": 7,
            }
        }


class _SynthStub:
    def __init__(self) -> None:
        self.called = False

    def synthesize(self, _user_query: str, _tool_outputs: dict[str, dict]) -> str:
        self.called = True
        return "synth"


class _ValidatorStub:
    @staticmethod
    def validate(_plan: list[PlanStep]) -> ValidationResult:
        return ValidationResult(True, "approved")


class AgentSystemControlFollowupTest(unittest.TestCase):
    def test_followup_set_it_phrase_routes_with_brightness_context(self) -> None:
        planner = _PlannerStub()
        executor = _ExecutorStub()
        synth = _SynthStub()

        loop = AgentLoop(
            planner=planner,  # type: ignore[arg-type]
            executor=executor,  # type: ignore[arg-type]
            synthesizer=synth,  # type: ignore[arg-type]
            validator=_ValidatorStub(),  # type: ignore[arg-type]
        )
        loop._last_system_control_topic = "brightness"

        self.assertTrue(loop.should_use_agent("you set it to 35"))

        result = loop.run("you set it to 35")

        self.assertTrue(result.handled)
        self.assertEqual(result.response, "Brightness set to 35%.")
        self.assertEqual(len(executor.last_plan), 1)
        self.assertEqual(executor.last_plan[0].tool, "system_control")
        self.assertIn("brightness", str(executor.last_plan[0].args.get("action") or "").lower())
        self.assertFalse(planner.called)
        self.assertFalse(synth.called)


if __name__ == "__main__":
    unittest.main()
