# ==============================================================================
# File: tests/stress/test_executor_observability.py
# Project: J.A.R.V.I.S. - Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Core module for test_executor_observability functionalities.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import unittest

from agent.executor import ToolExecutor
from agent.planner import PlanStep
from agent.tool_registry import ToolDefinition, ToolRegistry


class ExecutorObservabilityStressTest(unittest.TestCase):
    def test_emits_invoked_and_completed_events(self) -> None:
        registry = ToolRegistry()

        def _ok_tool(_args: dict[str, object]) -> dict[str, object]:
            return {"status": "success", "success": True, "verified": True, "message": "ok"}

        registry.register(
            ToolDefinition(
                name="temporal",
                description="Temporal tool",
                input_schema={"type": "object", "properties": {}},
                fn=_ok_tool,
                timeout_seconds=5.0,
                safe_to_parallelize=True,
            )
        )

        events: list[tuple[str, dict[str, object]]] = []

        def _sink(event_type: str, payload: dict[str, object]) -> None:
            events.append((event_type, payload))

        executor = ToolExecutor(registry, event_sink=_sink)
        result = executor.execute([PlanStep(tool="temporal", args={})])

        self.assertTrue(bool(result["temporal"].get("success")), result)
        event_types = {name for name, _payload in events}
        self.assertIn("tool_invoked", event_types)
        self.assertIn("tool_attempt_started", event_types)
        self.assertIn("tool_completed", event_types)

    def test_emits_unknown_tool_event(self) -> None:
        registry = ToolRegistry()
        events: list[tuple[str, dict[str, object]]] = []

        def _sink(event_type: str, payload: dict[str, object]) -> None:
            events.append((event_type, payload))

        executor = ToolExecutor(registry, event_sink=_sink)
        result = executor.execute([PlanStep(tool="does_not_exist", args={})])

        self.assertFalse(bool(result["does_not_exist"].get("success")), result)
        event_types = {name for name, _payload in events}
        self.assertIn("tool_unknown", event_types)

    def test_sink_failure_does_not_break_execution(self) -> None:
        registry = ToolRegistry()

        def _ok_tool(_args: dict[str, object]) -> dict[str, object]:
            return {"status": "success", "success": True, "verified": True, "message": "ok"}

        registry.register(
            ToolDefinition(
                name="temporal",
                description="Temporal tool",
                input_schema={"type": "object", "properties": {}},
                fn=_ok_tool,
                timeout_seconds=5.0,
                safe_to_parallelize=True,
            )
        )

        def _failing_sink(_event_type: str, _payload: dict[str, object]) -> None:
            raise RuntimeError("sink unavailable")

        executor = ToolExecutor(registry, event_sink=_failing_sink)
        result = executor.execute([PlanStep(tool="temporal", args={})])

        self.assertTrue(bool(result["temporal"].get("success")), result)


if __name__ == "__main__":
    unittest.main()