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
            "screen_process": {
                "tool": "screen_process",
                "args": plan[0].args,
                "success": True,
                "output": {
                    "status": "success",
                    "action": "screen_process",
                    "success": True,
                    "verified": True,
                    "error": "",
                    "message": "Captured screen frame and generated local analysis.",
                    "analysis": {
                        "summary": "Screen frame 320x180 with balanced lighting.",
                        "objects": [],
                        "history": {"frames_stored": 1},
                    },
                    "live_session": {"queued": False},
                },
                "error": "",
                "duration_ms": 10,
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


class AgentScreenProcessRoutingTest(unittest.TestCase):
    def test_direct_screen_path_handles_view_screen(self) -> None:
        planner = _PlannerStub()
        executor = _ExecutorStub()
        synth = _SynthStub()

        loop = AgentLoop(
            planner=planner,  # type: ignore[arg-type]
            executor=executor,  # type: ignore[arg-type]
            synthesizer=synth,  # type: ignore[arg-type]
            validator=_ValidatorStub(),  # type: ignore[arg-type]
        )

        result = loop.run("view my screen now")

        self.assertTrue(result.handled)
        self.assertIn("screen frame", result.response.lower())
        self.assertEqual(len(executor.last_plan), 1)
        self.assertEqual(executor.last_plan[0].tool, "screen_process")
        self.assertEqual(executor.last_plan[0].args.get("action"), "view_now")
        self.assertEqual(executor.last_plan[0].args.get("angle"), "screen")
        self.assertFalse(planner.called)
        self.assertFalse(synth.called)

    def test_direct_screen_path_handles_latest_screen(self) -> None:
        planner = _PlannerStub()
        executor = _ExecutorStub()
        synth = _SynthStub()

        loop = AgentLoop(
            planner=planner,  # type: ignore[arg-type]
            executor=executor,  # type: ignore[arg-type]
            synthesizer=synth,  # type: ignore[arg-type]
            validator=_ValidatorStub(),  # type: ignore[arg-type]
        )

        result = loop.run("show latest screen capture")

        self.assertTrue(result.handled)
        self.assertEqual(executor.last_plan[0].tool, "screen_process")
        self.assertEqual(executor.last_plan[0].args.get("action"), "view_latest")
        self.assertEqual(executor.last_plan[0].args.get("live_enrichment"), False)


if __name__ == "__main__":
    unittest.main()
