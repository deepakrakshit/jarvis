from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from core.settings import AppConfig
from agent.executor import ToolExecutor
from agent.planner import PlanStep, Planner
from agent.synthesizer import Synthesizer
from agent.tool_registry import ToolRegistry
from agent.validator import PlanValidator, ToolOutputValidator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentLoopResult:
    """Final result of one autonomous agent loop pass."""

    handled: bool
    response: str
    plan: list[dict[str, Any]]
    tool_outputs: dict[str, dict[str, Any]]
    reasoning: str = ""
    error: str = ""


class AgentLoop:
    """Production-grade autonomous loop: plan, execute, synthesize."""

    _FAST_PATH_CHAT_EXACT = {
        "hi",
        "hello",
        "hey",
        "yo",
        "how are you",
        "who are you",
        "what are you",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "cool",
    }
    _FAST_PATH_CHAT_PREFIXES = (
        "who are you",
        "what are you",
        "how are you",
        "tell me about yourself",
    )
    _TOOL_HINTS = (
        "weather",
        "temperature",
        "forecast",
        "news",
        "headline",
        "search",
        "internet",
        "web",
        "speedtest",
        "speed test",
        "download",
        "upload",
        "latency",
        "ping",
        "public ip",
        "ip address",
        "where am i",
        "location",
        "system status",
        "network status",
        "time",
        "date",
        "update status",
        "latest",
        "current",
        "who won",
        "winner",
        "ipl",
        "holiday",
        "prime minister",
        "president",
        "document",
        "analyze",
        "pdf",
        "docx",
        "summarize this",
        "extract from",
        "read this",
    )

    def __init__(
        self,
        planner: Planner,
        executor: ToolExecutor,
        synthesizer: Synthesizer,
        validator: PlanValidator,
        get_session_location: Callable[[], str | None] | None = None,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.synthesizer = synthesizer
        self.validator = validator
        self._get_session_location = get_session_location

    @classmethod
    def from_registry(
        cls,
        *,
        config: AppConfig,
        tool_registry: ToolRegistry,
        get_session_location: Callable[[], str | None] | None = None,
    ) -> "AgentLoop":
        """Construct an agent loop with default planner/executor/synthesizer/validator."""
        planner = Planner(config, tool_registry)
        executor = ToolExecutor(tool_registry, output_validator=ToolOutputValidator())
        synthesizer = Synthesizer(config)
        validator = PlanValidator(tool_registry)
        return cls(
            planner=planner,
            executor=executor,
            synthesizer=synthesizer,
            validator=validator,
            get_session_location=get_session_location,
        )

    def should_use_agent(self, user_query: str) -> bool:
        """Return whether input should enter planner->tool->synthesizer flow."""
        query = self._normalize(user_query)
        if not query:
            return False

        if query in self._FAST_PATH_CHAT_EXACT:
            return False

        for prefix in self._FAST_PATH_CHAT_PREFIXES:
            if query.startswith(prefix):
                return False

        for marker in self._TOOL_HINTS:
            if marker in query:
                return True

        # Short acknowledgements and casual one-liners should bypass tools.
        if len(query.split()) <= 5:
            return False

        return False

    def should_handle(self, user_query: str) -> bool:
        """Backward-compatible alias for existing integration points."""
        return self.should_use_agent(user_query)

    def run(self, user_query: str) -> AgentLoopResult:
        """Run a full autonomous cycle for tool-backed requests."""
        if self._is_tool_use_forbidden_request(user_query):
            return AgentLoopResult(
                handled=True,
                response="I cannot provide real-time weather or live facts without using tools.",
                plan=[],
                tool_outputs={},
                reasoning="Tool usage explicitly disallowed for a real-time request.",
            )

        if not self.should_use_agent(user_query):
            return AgentLoopResult(False, "", [], {})

        plan_draft = self.planner.plan(user_query)
        if plan_draft is None:
            return AgentLoopResult(False, "", [], {}, error="planner_output_unparseable")

        plan_steps = self._prepare_plan_for_execution(plan_draft.plan, user_query)
        if not plan_steps:
            return AgentLoopResult(False, "", [], {})

        validation = self.validator.validate(plan_steps)
        if not validation.approved:
            logger.warning("Rejected plan: %s", validation.reason)
            return AgentLoopResult(
                True,
                "I could not safely execute that plan. Please rephrase with a clear request.",
                self._serialize_plan(plan_steps),
                {},
                reasoning=plan_draft.reasoning,
                error=validation.reason,
            )

        tool_outputs = self.executor.execute(plan_steps)
        synthesized = self.synthesizer.synthesize(user_query, tool_outputs)
        return AgentLoopResult(
            handled=True,
            response=synthesized,
            plan=self._serialize_plan(plan_steps),
            tool_outputs=tool_outputs,
            reasoning=plan_draft.reasoning,
        )

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join((text or "").strip().lower().split())

    def _prepare_plan_for_execution(self, plan_steps: list[PlanStep], user_query: str) -> list[PlanStep]:
        prepared: list[PlanStep] = []
        inferred_query_location = self._extract_query_location(user_query)
        session_location = ""
        if self._get_session_location is not None:
            try:
                session_location = str(self._get_session_location() or "").strip()
            except Exception:
                session_location = ""

        for step in plan_steps:
            if step.tool != "weather":
                prepared.append(step)
                continue

            args = dict(step.args)
            explicit_location = str(args.get("location") or "").strip()
            if not explicit_location:
                explicit_location = inferred_query_location or session_location or "here"

            args["location"] = explicit_location
            args.setdefault("query", user_query)
            prepared.append(PlanStep(tool=step.tool, args=args))

        return prepared

    @staticmethod
    def _extract_query_location(query: str) -> str:
        source = " ".join((query or "").strip().split())
        patterns = (
            r"\b(?:weather|temperature|forecast)\s+(?:in|at|for)\s+([a-zA-Z][a-zA-Z\s\-]{1,80})",
            r"\b(?:in|at|for)\s+([a-zA-Z][a-zA-Z\s\-]{1,80})",
        )
        for pattern in patterns:
            match = re.search(pattern, source, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = re.split(r"\b(?:and|also|please|currently|right now)\b", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
            cleaned = candidate.strip(" .,!?;:")
            if cleaned:
                return cleaned
        return ""

    def _is_tool_use_forbidden_request(self, user_query: str) -> bool:
        normalized = self._normalize(user_query)
        if not normalized:
            return False

        forbidden_markers = (
            "without tools",
            "without using tools",
            "without any tools",
            "dont use tools",
            "dont use any tools",
            "don't use tools",
            "don't use any tools",
            "do not use tools",
            "do not use any tools",
            "no tools",
        )
        if not any(marker in normalized for marker in forbidden_markers):
            return False

        realtime_markers = (
            "weather",
            "news",
            "latest",
            "public ip",
            "ip address",
            "forecast",
            "temperature",
        )
        return any(marker in normalized for marker in realtime_markers)

    @staticmethod
    def _serialize_plan(plan_steps: list[PlanStep]) -> list[dict[str, Any]]:
        return [{"tool": step.tool, "args": step.args} for step in plan_steps]
