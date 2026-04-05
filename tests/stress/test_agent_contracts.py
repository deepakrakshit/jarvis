# ==============================================================================
# File: tests/stress/test_agent_contracts.py
# Project: J.A.R.V.I.S. - Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Core module for test_agent_contracts functionalities.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import unittest

from agent.agent_loop import AgentLoop
from agent.executor import ToolExecutor
from agent.planner import PlanStep, Planner
from agent.synthesizer import Synthesizer
from agent.tool_registry import ToolDefinition, ToolRegistry
from agent.validator import PlanValidator, ToolOutputValidator
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

    def test_prepare_plan_adds_missing_computer_action_and_document_marker(self) -> None:
        config = AppConfig.from_env(".env")
        registry = self._registry()
        loop = AgentLoop(
            planner=Planner(config, registry),
            executor=ToolExecutor(registry),
            synthesizer=Synthesizer(config),
            validator=PlanValidator(registry),
        )

        prepared = loop._prepare_plan_for_execution(
            [
                PlanStep(tool="computer_control", args={"goal": "search for cat videos on YouTube"}),
                PlanStep(tool="document", args={"query": "summarize this document"}),
            ],
            user_query="summarize this document",
        )

        self.assertEqual(prepared[0].tool, "computer_control")
        self.assertEqual(prepared[0].args.get("action"), "autonomous_task")
        self.assertEqual(prepared[0].args.get("goal"), "search for cat videos on YouTube")
        self.assertEqual(prepared[1].tool, "document")
        self.assertEqual(prepared[1].args.get("file_path"), "__active_document__")

    def test_direct_coding_step_extracts_project_name(self) -> None:
        step = AgentLoop._direct_coding_assist_step(
            "I want you to create a project name calculator. It should be production grade and modular."
        )
        self.assertIsNotNone(step)
        assert step is not None
        self.assertEqual(step.tool, "coding_assist")
        self.assertEqual(step.args.get("action"), "create_project")
        self.assertEqual(step.args.get("name"), "calculator")
        self.assertEqual(step.args.get("target_dir"), "Projects")
        self.assertTrue(bool(step.args.get("open_after_create")))

    def test_direct_coding_step_ignores_from_scratch_suffix_in_name(self) -> None:
        step = AgentLoop._direct_coding_assist_step(
            "Create the project named Calculator from the Scratch again."
        )
        self.assertIsNotNone(step)
        assert step is not None
        self.assertEqual(step.tool, "coding_assist")
        self.assertEqual(step.args.get("action"), "create_project")
        self.assertEqual(step.args.get("name"), "Calculator")

    def test_direct_coding_step_supports_named_as_phrase(self) -> None:
        step = AgentLoop._direct_coding_assist_step(
            "create a prodcution grade project named as CALCULATOR_"
        )
        self.assertIsNotNone(step)
        assert step is not None
        self.assertEqual(step.tool, "coding_assist")
        self.assertEqual(step.args.get("action"), "create_project")
        self.assertEqual(step.args.get("name"), "CALCULATOR_")

    def test_direct_coding_step_routes_run_request(self) -> None:
        query = "Open the Calculator project folder and run the project in terminal"
        step = AgentLoop._direct_coding_assist_step(query)
        self.assertIsNotNone(step)
        assert step is not None
        self.assertEqual(step.tool, "coding_assist")
        self.assertEqual(step.args.get("action"), "run_from_request")
        self.assertEqual(step.args.get("request"), query)
        self.assertTrue(bool(step.args.get("open_folder")))

    def test_direct_coding_step_does_not_hijack_app_launch(self) -> None:
        step = AgentLoop._direct_coding_assist_step("start calculator app")
        self.assertIsNone(step)

    def test_direct_file_step_extracts_bulk_generation_intent(self) -> None:
        config = AppConfig.from_env(".env")
        registry = self._registry()
        loop = AgentLoop(
            planner=Planner(config, registry),
            executor=ToolExecutor(registry),
            synthesizer=Synthesizer(config),
            validator=PlanValidator(registry),
        )

        step = loop._direct_file_controller_step(
            "Create 50 text files in a folder named 'StressTest' with random content in each."
        )
        self.assertIsNotNone(step)
        assert step is not None
        self.assertEqual(step.tool, "file_controller")
        self.assertEqual(step.args.get("action"), "create_random_text_files")
        self.assertEqual(step.args.get("path"), "StressTest")
        self.assertEqual(step.args.get("count"), 50)
        self.assertTrue(bool(step.args.get("fill_to_count")))

    def test_direct_file_step_resolves_create_rest_followup(self) -> None:
        config = AppConfig.from_env(".env")
        registry = self._registry()
        loop = AgentLoop(
            planner=Planner(config, registry),
            executor=ToolExecutor(registry),
            synthesizer=Synthesizer(config),
            validator=PlanValidator(registry),
        )

        loop.set_conversation_context(
            conversation_history=[
                {
                    "role": "user",
                    "content": "Create 50 text files in a folder named StressTest with random content in each.",
                }
            ]
        )

        step = loop._direct_file_controller_step("create the rest")
        self.assertIsNotNone(step)
        assert step is not None
        self.assertEqual(step.tool, "file_controller")
        self.assertEqual(step.args.get("action"), "create_random_text_files")
        self.assertEqual(step.args.get("path"), "StressTest")
        self.assertEqual(step.args.get("count"), 50)

    def test_prefer_planner_route_defaults_to_true(self) -> None:
        self.assertTrue(AgentLoop._prefer_planner_route("Mute volume and set brightness to 10 percent"))
        self.assertTrue(AgentLoop._prefer_planner_route("Click start and type calendar"))

    def test_prefer_planner_route_keeps_deterministic_shortcuts(self) -> None:
        self.assertFalse(
            AgentLoop._prefer_planner_route(
                "Create 50 text files in a folder named StressTest with random content in each"
            )
        )
        self.assertFalse(
            AgentLoop._prefer_planner_route(
                "Create a project named Calculator with modular structure"
            )
        )

    def test_prefer_planner_route_for_chained_bulk_file_workflow(self) -> None:
        query = (
            "Create 100 random text files in a new directory called StressTest, each with exactly 1024 characters. "
            "After creating them, find all files containing the letter z and move them to a Filtered subfolder."
        )
        self.assertTrue(AgentLoop._prefer_planner_route(query))

    def test_extract_exact_char_count_from_bulk_request(self) -> None:
        query = "Create 100 random text files in folder StressTest, each with exactly 1024 characters."
        self.assertEqual(AgentLoop._extract_exact_char_count(query), 1024)

    def test_weather_location_match_accepts_city_with_label_suffix(self) -> None:
        validator = ToolOutputValidator()
        result = validator.validate_tool_output(
            "weather",
            {"location": "Nagpur, Maharashtra, India"},
            {
                "success": True,
                "temperature_c": 31.2,
                "tool_location": "Nagpur",
                "tool_location_label": "Nagpur, Maharashtra, India",
            },
        )
        self.assertTrue(result.valid, result.reason)

    def test_weather_location_match_still_rejects_unrelated_city(self) -> None:
        validator = ToolOutputValidator()
        result = validator.validate_tool_output(
            "weather",
            {"location": "Paris"},
            {
                "success": True,
                "temperature_c": 22.0,
                "tool_location": "Nagpur",
                "tool_location_label": "Nagpur, Maharashtra, India",
            },
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "location_mismatch")


if __name__ == "__main__":
    unittest.main()
