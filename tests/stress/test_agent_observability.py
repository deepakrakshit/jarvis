# ==============================================================================
# File: tests/stress/test_agent_observability.py
# Project: J.A.R.V.I.S. - Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Core module for test_agent_observability functionalities.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import unittest
from typing import Any

from agent.agent_loop import AgentLoop
from agent.executor import ToolExecutor
from agent.planner import PlanDraft, PlanStep
from agent.tool_registry import ToolDefinition, ToolRegistry
from agent.validator import PlanValidator


class _StubPlanner:
    def __init__(self, drafts: list[PlanDraft]) -> None:
        self._drafts = list(drafts)
        self._cursor = 0

    def plan(
        self,
        user_query: str,
        *,
        max_retries: int = 2,
        conversation_history: list[dict[str, str]] | None = None,
        execution_history: list[dict[str, Any]] | None = None,
    ) -> PlanDraft | None:
        _ = user_query, max_retries, conversation_history, execution_history
        if self._cursor >= len(self._drafts):
            return PlanDraft(plan=[], reasoning="done", is_complete=True)
        draft = self._drafts[self._cursor]
        self._cursor += 1
        return draft


class _StubSynthesizer:
    def synthesize(
        self,
        user_query: str,
        tool_outputs: dict[str, dict[str, Any]],
        *,
        conversation_history: list[dict[str, str]] | None = None,
        user_profile: dict[str, str] | None = None,
    ) -> str:
        _ = user_query, tool_outputs, conversation_history, user_profile
        return "synthesized"


def _search_tool(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "")
    return {
        "status": "success",
        "success": True,
        "verified": True,
        "query": query,
        "results": [
            {
                "title": "Result",
                "snippet": f"Matched {query}",
                "link": "https://example.com",
                "trusted": True,
            }
        ],
    }


class AgentObservabilityStressTest(unittest.TestCase):
    def test_skipped_query_emits_start_skip_and_completion_events(self) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        loop = AgentLoop(
            planner=_StubPlanner([]),
            executor=ToolExecutor(ToolRegistry()),
            synthesizer=_StubSynthesizer(),
            validator=PlanValidator(ToolRegistry()),
            event_sink=lambda event_type, payload: events.append((event_type, payload)),
        )

        result = loop.run("hello")

        self.assertFalse(result.handled)
        event_names = [name for name, _payload in events]
        self.assertIn("agent_run_started", event_names)
        self.assertIn("agent_run_skipped", event_names)
        self.assertIn("agent_run_completed", event_names)

    def test_planner_route_emits_turn_validation_and_completion_events(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="internet_search",
                description="Search tool",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                    },
                },
                fn=_search_tool,
                timeout_seconds=5.0,
                safe_to_parallelize=True,
            )
        )

        events: list[tuple[str, dict[str, Any]]] = []
        planner = _StubPlanner(
            [
                PlanDraft(
                    plan=[PlanStep(tool="internet_search", args={"query": "release notes"})],
                    reasoning="Need live search results.",
                    is_complete=True,
                )
            ]
        )

        loop = AgentLoop(
            planner=planner,
            executor=ToolExecutor(registry),
            synthesizer=_StubSynthesizer(),
            validator=PlanValidator(registry),
            event_sink=lambda event_type, payload: events.append((event_type, payload)),
        )

        result = loop.run("search latest release notes")

        self.assertTrue(result.handled)
        self.assertTrue(bool(result.tool_outputs))
        event_names = [name for name, _payload in events]
        self.assertIn("agent_route_selected", event_names)
        self.assertIn("planner_turn_started", event_names)
        self.assertIn("planner_turn_planned", event_names)
        self.assertIn("plan_validation_started", event_names)
        self.assertIn("planner_turn_executed", event_names)
        self.assertIn("synthesis_strategy_selected", event_names)
        self.assertIn("agent_run_completed", event_names)


if __name__ == "__main__":
    unittest.main()
