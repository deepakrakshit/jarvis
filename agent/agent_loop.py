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
        "my ip",
        "external ip",
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
        "open app",
        "close app",
        "launch app",
        "terminate app",
        "close it",
        "file explorer",
        "file manager",
        "file picker",
        "document selector",
        "volume",
        "mute",
        "unmute",
        "brightness",
        "window",
        "switch window",
        "minimize",
        "restore",
        "focus window",
        "show desktop",
        "lock screen",
        "sleep",
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
        self._last_system_control_topic = ""

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

        if re.search(r"^(open|launch|start|close|quit|terminate)\s+[a-z0-9]", query):
            return True

        for marker in self._TOOL_HINTS:
            if marker in query:
                return True

        if self._is_system_followup_request(query):
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

        query_for_tools = self._resolve_system_control_followup_query(user_query)
        reasoning = ""
        if self._is_direct_system_control_candidate(query_for_tools):
            plan_steps = [
                PlanStep(
                    tool="system_control",
                    args={
                        "action": query_for_tools,
                        "params": {},
                    },
                )
            ]
            reasoning = "Direct deterministic system control path."
        else:
            plan_draft = self.planner.plan(query_for_tools)
            if plan_draft is None:
                return AgentLoopResult(False, "", [], {}, error="planner_output_unparseable")

            plan_steps = self._prepare_plan_for_execution(plan_draft.plan, query_for_tools)
            if not plan_steps:
                return AgentLoopResult(False, "", [], {})
            reasoning = plan_draft.reasoning

        validation = self.validator.validate(plan_steps)
        if not validation.approved:
            logger.warning("Rejected plan: %s", validation.reason)
            return AgentLoopResult(
                True,
                "I could not safely execute that plan. Please rephrase with a clear request.",
                self._serialize_plan(plan_steps),
                {},
                reasoning=reasoning,
                error=validation.reason,
            )

        tool_outputs = self.executor.execute(plan_steps)
        self._update_system_control_context(tool_outputs)

        if self._all_steps_are_system_control(plan_steps):
            response = self._synthesize_system_control_response(tool_outputs)
        else:
            response = self.synthesizer.synthesize(user_query, tool_outputs)

        return AgentLoopResult(
            handled=True,
            response=response,
            plan=self._serialize_plan(plan_steps),
            tool_outputs=tool_outputs,
            reasoning=reasoning,
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

    @staticmethod
    def _is_direct_system_control_candidate(query: str) -> bool:
        lowered = AgentLoop._normalize(query)
        if not lowered:
            return False

        direct_markers = (
            "brightness",
            "volume",
            "mute",
            "unmute",
            "window",
            "desktop",
            "lock screen",
            "sleep",
        )
        if any(marker in lowered for marker in direct_markers):
            return True

        if re.search(r"\b(set|increase|decrease|raise|lower|adjust|change)\b.*\b\d{1,3}\b", lowered):
            return True
        return False

    def _is_system_followup_request(self, query: str) -> bool:
        if not self._last_system_control_topic:
            return False

        lowered = self._normalize(query)
        if not lowered:
            return False

        if self._last_system_control_topic in lowered:
            return True

        if re.search(r"\b(set|change|adjust|make|increase|decrease|lower|raise)\b.*\b(it|that)\b", lowered):
            return True

        if re.search(r"\b(it'?s|it is)\s+still\b", lowered) and re.search(r"\b\d{1,3}\b", lowered):
            return True

        if re.search(r"\bi\s+want\s+it\b", lowered) and re.search(r"\b\d{1,3}\b", lowered):
            return True

        return False

    def _resolve_system_control_followup_query(self, query: str) -> str:
        lowered = self._normalize(query)
        if not self._is_system_followup_request(lowered):
            return query

        if self._last_system_control_topic and self._last_system_control_topic not in lowered:
            return f"{query} for {self._last_system_control_topic}"
        return query

    @staticmethod
    def _all_steps_are_system_control(plan_steps: list[PlanStep]) -> bool:
        return bool(plan_steps) and all(step.tool == "system_control" for step in plan_steps)

    def _update_system_control_context(self, tool_outputs: dict[str, dict[str, Any]]) -> None:
        for payload in tool_outputs.values():
            if not isinstance(payload, dict):
                continue
            if str(payload.get("tool") or "") != "system_control":
                continue

            output = payload.get("output")
            if not isinstance(output, dict):
                continue

            action = str(output.get("action") or "").strip().lower()
            topic = self._topic_for_system_action(action)
            if topic:
                self._last_system_control_topic = topic

    @staticmethod
    def _topic_for_system_action(action: str) -> str:
        normalized = str(action or "").strip().lower()
        if "brightness" in normalized:
            return "brightness"
        if "volume" in normalized or normalized in {"mute", "unmute"}:
            return "volume"
        if "window" in normalized:
            return "window"
        if normalized in {"show_desktop", "minimize_all_windows", "restore_all_windows", "restore_specific"}:
            return "desktop"
        if normalized in {"lock_screen", "sleep"}:
            return "system"
        return ""

    @staticmethod
    def _synthesize_system_control_response(tool_outputs: dict[str, dict[str, Any]]) -> str:
        first = next(iter(tool_outputs.values()), None)
        if not isinstance(first, dict):
            return "I could not complete that system control request."

        output = first.get("output")
        if not isinstance(output, dict):
            return "I could not complete that system control request."

        success = bool(output.get("success", False))
        verified = bool(output.get("verified", False))
        message = str(output.get("message") or "").strip()
        error_code = str(output.get("error") or "").strip()
        state = output.get("state") if isinstance(output.get("state"), dict) else {}

        if success and verified:
            return message or "System action completed successfully."

        if success and not verified:
            if message:
                return f"I attempted the action but could not verify completion. {message}"
            return "I attempted the action but could not verify completion."

        if message and error_code:
            return f"{message} ({error_code})"
        if message:
            return message

        if error_code:
            return f"I could not complete that system action: {error_code}."

        if state:
            return f"I could not verify the system action state: {state}."
        return "I could not complete that system control request."
