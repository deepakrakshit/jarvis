from __future__ import annotations

import unittest

from agent.agent_loop import AgentLoop
from agent.executor import ToolExecutor
from agent.planner import PlanStep, Planner
from agent.synthesizer import Synthesizer
from agent.tool_registry import ToolDefinition, ToolRegistry
from agent.validator import PlanValidator
from core.settings import AppConfig


def _echo_tool(args: dict[str, object]) -> dict[str, object]:
    return {"ok": True, "args": args}


class AgentContractsStressTest(unittest.TestCase):
    def _registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="app_control",
                description="Control apps",
                input_schema={
                    "type": "object",
                    "required": ["action"],
                    "properties": {
                        "action": {"type": "string"},
                        "app_name": {"type": "string"},
                    },
                },
                fn=_echo_tool,
                timeout_seconds=5.0,
                safe_to_parallelize=False,
            )
        )
        return registry

    def test_tool_registry_argument_contract(self) -> None:
        registry = self._registry()
        valid, reason = registry.validate_args("app_control", {"action": "open", "app_name": "chrome"})
        self.assertTrue(valid, reason)

        missing, _ = registry.validate_args("app_control", {"app_name": "chrome"})
        self.assertFalse(missing)

        wrong_type, _ = registry.validate_args("app_control", {"action": 1})
        self.assertFalse(wrong_type)

    def test_plan_validator_rejects_unknown_tool(self) -> None:
        validator = PlanValidator(self._registry())
        result = validator.validate([PlanStep(tool="unknown", args={})])
        self.assertFalse(result.approved)
        self.assertIn("unknown tool", result.reason.lower())

    def test_planner_json_extraction_and_dedup(self) -> None:
        planner = Planner(AppConfig.from_env(".env"), self._registry())

        extracted = planner._extract_first_json_object("prefix {\"plan\": [], \"reasoning\": \"ok\"} suffix")
        self.assertIsNotNone(extracted)

        deduped = planner._remove_duplicate_steps(
            [
                PlanStep(tool="app_control", args={"action": "open", "app_name": "chrome"}),
                PlanStep(tool="app_control", args={"action": "open", "app_name": "chrome"}),
                PlanStep(tool="app_control", args={"action": "close", "app_name": "chrome"}),
            ]
        )
        self.assertEqual(len(deduped), 2)

    def test_agent_loop_gates_file_manager_and_picker_prompts(self) -> None:
        config = AppConfig.from_env(".env")
        registry = self._registry()
        loop = AgentLoop(
            planner=Planner(config, registry),
            executor=ToolExecutor(registry),
            synthesizer=Synthesizer(config),
            validator=PlanValidator(registry),
        )

        self.assertTrue(loop.should_use_agent("open file explorer"))
        self.assertTrue(loop.should_use_agent("open file picker"))
        self.assertTrue(loop.should_use_agent("close it"))
        self.assertTrue(loop.should_use_agent("what is my ip"))


if __name__ == "__main__":
    unittest.main()
