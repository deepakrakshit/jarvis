from __future__ import annotations

import unittest

from agent.executor import ToolExecutor
from agent.planner import PlanStep
from agent.synthesizer import Synthesizer
from agent.tool_registry import ToolDefinition, ToolRegistry
from agent.validator import ToolOutputValidator
from core.settings import AppConfig
from services.search_service import SearchResult, SearchService


class ToolAccuracyPipelineTest(unittest.TestCase):
    def test_executor_marks_empty_search_results_as_failure(self) -> None:
        registry = ToolRegistry()

        def _search_tool(args: dict[str, object]) -> dict[str, object]:
            return {
                "query": str(args.get("query") or ""),
                "results": [],
                "error": "no_results_or_gemini_search_unavailable",
            }

        registry.register(
            ToolDefinition(
                name="internet_search",
                description="Search tool",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
                fn=_search_tool,
                timeout_seconds=5.0,
                safe_to_parallelize=True,
            )
        )

        executor = ToolExecutor(registry, output_validator=ToolOutputValidator())
        result = executor.execute([PlanStep(tool="internet_search", args={"query": "latest ai chips"})])
        payload = result["internet_search"]

        self.assertFalse(bool(payload.get("success")))
        self.assertEqual(str(payload.get("confidence")), "low")
        self.assertGreaterEqual(int(payload.get("attempts") or 0), 1)

    def test_executor_sets_high_confidence_for_verified_system_action(self) -> None:
        registry = ToolRegistry()

        def _system_tool(_args: dict[str, object]) -> dict[str, object]:
            return {
                "status": "success",
                "action": "set_volume",
                "success": True,
                "verified": True,
                "error": "",
                "state": {"volume": 35},
                "message": "Volume set to 35%.",
            }

        registry.register(
            ToolDefinition(
                name="system_control",
                description="System control tool",
                input_schema={
                    "type": "object",
                    "required": ["action"],
                    "properties": {
                        "action": {"type": "string"},
                        "params": {"type": "object"},
                    },
                },
                fn=_system_tool,
                timeout_seconds=5.0,
                safe_to_parallelize=False,
            )
        )

        executor = ToolExecutor(registry, output_validator=ToolOutputValidator())
        result = executor.execute([PlanStep(tool="system_control", args={"action": "set volume to 35"})])
        payload = result["system_control"]

        self.assertTrue(bool(payload.get("success")))
        self.assertEqual(str(payload.get("confidence")), "high")

    def test_synthesizer_search_fallback_prefers_stronger_evidence(self) -> None:
        output = {
            "query": "latest ai chips",
            "results": [
                {
                    "title": "General market discussion",
                    "snippet": "sports and entertainment roundup",
                    "link": "https://example.com/general",
                    "trusted": False,
                },
                {
                    "title": "AI chip launch announced",
                    "snippet": "Reuters reports the latest AI chip launch and partner timeline.",
                    "link": "https://www.reuters.com/technology/ai-chip-launch",
                    "trusted": True,
                },
            ],
        }

        rendered = Synthesizer._render_search_fallback(output)

        self.assertIn("AI chip launch announced", rendered)
        self.assertIn("reuters", rendered.lower())

    def test_search_service_ranks_and_diversifies_domains(self) -> None:
        service = SearchService(AppConfig.from_env(".env"))
        ranked = service._rank_and_diversify_results(
            query="ai policy update",
            results=[
                SearchResult(
                    title="AI policy update from Reuters",
                    snippet="Latest policy briefing and timeline",
                    link="https://www.reuters.com/world/ai-policy-update",
                    trusted=True,
                ),
                SearchResult(
                    title="Same-domain secondary article",
                    snippet="Additional context from same publisher",
                    link="https://www.reuters.com/world/ai-policy-secondary",
                    trusted=True,
                ),
                SearchResult(
                    title="Government policy statement",
                    snippet="Official release on policy implementation",
                    link="https://www.gov.example/policy/ai-update",
                    trusted=True,
                ),
            ],
            max_results=2,
        )

        self.assertEqual(len(ranked), 2)
        domains = [service._result_domain(item.link) for item in ranked]
        self.assertEqual(len(set(domains)), 2)

    def test_validator_accepts_file_controller_bulk_contract(self) -> None:
        validator = ToolOutputValidator()
        result = validator.validate_tool_output(
            "file_controller",
            {},
            {
                "status": "success",
                "action": "create_random_text_files",
                "success": True,
                "verified": True,
                "error": "",
                "message": "ok",
                "data": {
                    "target_count": 50,
                    "total_available": 50,
                    "failed_count": 0,
                    "fill_to_count": True,
                },
            },
        )
        self.assertTrue(result.valid, result.reason)

    def test_validator_rejects_cmd_success_with_nonzero_exit(self) -> None:
        validator = ToolOutputValidator()
        result = validator.validate_tool_output(
            "cmd_control",
            {},
            {
                "status": "success",
                "action": "run_command",
                "success": True,
                "verified": True,
                "error": "",
                "message": "Command executed.",
                "exit_code": 3,
                "timed_out": False,
                "stdout": "",
                "stderr": "",
            },
        )
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "cmd_success_exit_code_mismatch")


if __name__ == "__main__":
    unittest.main()
