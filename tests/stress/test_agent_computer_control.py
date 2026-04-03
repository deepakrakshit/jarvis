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
            "computer_control": {
                "tool": "computer_control",
                "args": plan[0].args,
                "success": True,
                "output": {
                    "status": "success",
                    "action": "autonomous_task",
                    "success": True,
                    "verified": True,
                    "error": "",
                    "message": "Computer automation completed and was verified.",
                    "state": {},
                },
                "error": "",
                "duration_ms": 11,
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


class AgentComputerControlTest(unittest.TestCase):
    def test_direct_computer_path_handles_browser_automation_request(self) -> None:
        planner = _PlannerStub()
        executor = _ExecutorStub()
        synth = _SynthStub()

        loop = AgentLoop(
            planner=planner,  # type: ignore[arg-type]
            executor=executor,  # type: ignore[arg-type]
            synthesizer=synth,  # type: ignore[arg-type]
            validator=_ValidatorStub(),  # type: ignore[arg-type]
        )

        result = loop.run("open chrome and search on youtube about python tutorials")

        self.assertTrue(result.handled)
        self.assertIn("completed", result.response.lower())
        self.assertEqual(len(executor.last_plan), 1)
        self.assertEqual(executor.last_plan[0].tool, "computer_control")
        self.assertEqual(executor.last_plan[0].args.get("action"), "autonomous_task")
        self.assertEqual(executor.last_plan[0].args.get("goal"), "open chrome and search on youtube about python tutorials")
        self.assertFalse(planner.called)
        self.assertFalse(synth.called)


if __name__ == "__main__":
    unittest.main()
