# ==============================================================================
# File: agent/agent_loop.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Autonomous Re-Act Agent Loop — Plan, Execute, Observe, Synthesize
#
#    - Production-grade autonomous reasoning engine with multi-turn self-correction.
#    - Implements the Re-Act (Reasoning and Acting) cycle with max 4 turns.
#    - Hybrid intent classification: ~95 keyword hints + LLM fallback classifier
#      (cheap Gemini call, max 5 tokens, temp=0) for ambiguous queries.
#    - Three deterministic fast-paths bypass the planner entirely:
#      system control (volume/brightness/window), computer automation (browser),
#      and screen processing (camera/display analysis).
#    - Context injection: last 4 conversation turns (truncated to 300 chars)
#      plus user profile (name, location) for personalized planning.
#    - System follow-up detection: catches 'set it to 50' after volume commands.
#    - AgentLoopResult provides structured response with text, tool outputs,
#      confidence level, and tool execution metadata.
#    - Graceful degradation: falls back to direct LLM chat if agent loop fails.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from core.settings import AppConfig
from core.llm_api import chat_complete
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
        "type this",
        "write this",
        "left click",
        "right click",
        "double click",
        "hotkey",
        "press key",
        "take screenshot",
        "screen find",
        "screen click",
        "analyze screen",
        "analyze camera",
        "view screen",
        "view my screen",
        "show screen",
        "show my screen",
        "see screen",
        "what is on my screen",
        "what's on my screen",
        "my screen",
        "view camera",
        "show camera",
        "see camera",
        "camera view",
        "my camera",
        "youtube",
        "youtube.com",
        "browser",
        "navigate",
        "open url",
        "website",
    )

    def __init__(
        self,
        planner: Planner,
        executor: ToolExecutor,
        synthesizer: Synthesizer,
        validator: PlanValidator,
        get_session_location: Callable[[], str | None] | None = None,
        config: AppConfig | None = None,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.synthesizer = synthesizer
        self.validator = validator
        self._get_session_location = get_session_location
        self._last_system_control_topic = ""
        self._config = config
        self._conversation_history: list[dict[str, str]] = []
        self._user_profile: dict[str, str] = {}

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
            config=config,
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

        # LLM classification is a fallback for non-obvious queries.
        return self._classify_with_llm(query)

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
        plan_steps: list[PlanStep] = []
        tool_outputs: dict[str, dict[str, Any]] = {}
        response = ""
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
            response = self._synthesize_system_control_response(tool_outputs)
        elif (direct_computer_step := self._direct_computer_automation_step(query_for_tools)) is not None:
            plan_steps = [direct_computer_step]
            reasoning = "Direct deterministic computer automation path."

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
            response = self._synthesize_computer_control_response(tool_outputs)
        elif (direct_screen_step := self._direct_screen_process_step(query_for_tools)) is not None:
            plan_steps = [direct_screen_step]
            reasoning = "Direct deterministic screen analysis path."

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
            response = self._synthesize_screen_process_response(tool_outputs)
        else:
            max_turns = 4
            execution_history: list[dict[str, Any]] = []
            all_tool_outputs: dict[str, dict[str, Any]] = {}
            cumulative_steps: list[PlanStep] = []
            reasoning = ""
            
            for turn in range(max_turns):
                plan_draft = self.planner.plan(
                    query_for_tools,
                    conversation_history=self._conversation_history,
                    execution_history=execution_history,
                )
                if plan_draft is None:
                    if turn == 0:
                        return AgentLoopResult(False, "", [], {}, error="planner_output_unparseable")
                    break
                    
                reasoning = plan_draft.reasoning
                if not plan_draft.plan and plan_draft.is_complete:
                    break
                    
                turn_steps = self._prepare_plan_for_execution(plan_draft.plan, query_for_tools)
                if not turn_steps:
                    break
                    
                cumulative_steps.extend(turn_steps)
                
                validation = self.validator.validate(turn_steps)
                if not validation.approved:
                    logger.warning("Rejected plan: %s", validation.reason)
                    if turn == 0:
                        return AgentLoopResult(
                            True,
                            "I could not safely execute that plan. Please rephrase with a clear request.",
                            self._serialize_plan(turn_steps),
                            {},
                            reasoning=reasoning,
                            error=validation.reason,
                        )
                    break
                    
                turn_outputs = self.executor.execute(turn_steps)
                all_tool_outputs.update(turn_outputs)
                
                for key, val in turn_outputs.items():
                    execution_history.append(val)
                
                if plan_draft.is_complete:
                    break
                    
            plan_steps = cumulative_steps
            tool_outputs = all_tool_outputs

            self._update_system_control_context(tool_outputs)

            if self._all_steps_are_system_control(plan_steps):
                response = self._synthesize_system_control_response(tool_outputs)
            elif self._all_steps_are_computer_control(plan_steps):
                response = self._synthesize_computer_control_response(tool_outputs)
            elif self._all_steps_are_screen_process(plan_steps):
                response = self._synthesize_screen_process_response(tool_outputs)
            else:
                response = self.synthesizer.synthesize(
                    user_query,
                    tool_outputs,
                    conversation_history=self._conversation_history,
                    user_profile=self._user_profile,
                )

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

    def set_conversation_context(
        self,
        *,
        conversation_history: list[dict[str, str]] | None = None,
        user_profile: dict[str, str] | None = None,
    ) -> None:
        """Inject conversation context for multi-turn awareness."""
        if conversation_history is not None:
            self._conversation_history = conversation_history
        if user_profile is not None:
            self._user_profile = user_profile

    def _classify_with_llm(self, query: str) -> bool:
        """Use a fast Gemini call to decide if a query needs tool execution.

        This catches queries that keyword matching misses, like:
        - "is it cold outside" → weather
        - "how fast is my connection" → speedtest
        - "tell me about the latest tech news" → internet_search
        """
        if self._config is None:
            return False

        system_prompt = (
            "You are an intent classifier for a desktop assistant with these tools: "
            "weather, internet_search, speedtest, public_ip, network_location, "
            "system_status, temporal, app_control, system_control, computer_control, document.\n\n"
            "Given the user query, respond with ONLY 'yes' or 'no'.\n"
            "'yes' means the query requires calling a tool (weather data, web search, "
            "app control, system control, speed test, IP lookup, time/date queries, etc).\n"
            "'no' means the query is conversational, conceptual, or can be answered "
            "from general knowledge without any tool.\n\n"
            "Examples:\n"
            "- 'is it cold outside' → yes (needs weather tool)\n"
            "- 'how fast is my connection' → yes (needs speedtest)\n"
            "- 'who is the current president of France' → yes (needs search)\n"
            "- 'explain quantum computing' → no (general knowledge)\n"
            "- 'what is 2+2' → no (simple math)\n"
            "- 'thanks for helping' → no (conversational)\n"
            "- 'open the calculator app' → yes (needs app_control)\n"
            "- 'turn down the brightness' → yes (needs system_control)\n"
            "Respond with ONLY 'yes' or 'no'."
        )

        try:
            result = chat_complete(
                self._config,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                temperature=0,
                max_tokens=5,
                timeout=8,
            ).strip().lower()
            return result.startswith("yes")
        except Exception as exc:
            logger.debug("LLM intent classification failed, falling back to no-tool: %s", exc)
            return False

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
            if step.tool == "computer_control":
                args = dict(step.args)
                action = str(args.get("action") or "").strip().lower()
                if not action:
                    goal = str(
                        args.get("goal")
                        or args.get("description")
                        or args.get("query")
                        or user_query
                    ).strip()
                    args["action"] = "autonomous_task"
                    args["goal"] = goal
                    args.setdefault("max_steps", 14)
                    args.setdefault("safety_mode", "strict")
                prepared.append(PlanStep(tool=step.tool, args=args))
                continue

            if step.tool == "document":
                args = dict(step.args)
                file_path = str(args.get("file_path") or "").strip()
                if not file_path:
                    # Sentinel handled by document tool to use active-document context.
                    args["file_path"] = "__active_document__"
                args.setdefault("query", user_query)
                prepared.append(PlanStep(tool=step.tool, args=args))
                continue

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

        if re.search(r"\b(new|close|reopen|next|previous|prev)\s+tab\b", lowered):
            return True

        if re.search(r"\b(next|previous|prev)\s+(track|song)\b", lowered):
            return True

        if re.search(r"\b(play|pause|resume|stop)\b.*\b(media|music|playback)\b", lowered):
            return True

        if re.search(r"\b(turn|switch)\s+(off|on)\s+(display|screen|monitor)\b", lowered):
            return True

        if re.search(r"\b(refresh|reload)\s+(page|tab)\b|\bhard refresh\b", lowered):
            return True

        if re.search(r"\b(go\s+back|go\s+forward|browser\s+back|browser\s+forward)\b", lowered):
            return True

        if re.search(r"\b(copy|paste|cut|undo|redo|select all|save|find|zoom in|zoom out|reset zoom)\b.*\b(shortcut|hotkey|keyboard)\b", lowered):
            return True

        if re.search(r"\b(set|increase|decrease|raise|lower|adjust|change)\b.*\b\d{1,3}\b", lowered):
            return True
        return False

    @staticmethod
    def _direct_computer_automation_step(query: str) -> PlanStep | None:
        lowered = AgentLoop._normalize(query)
        if not lowered:
            return None

        direct_screen_step = AgentLoop._direct_screen_process_step(query)
        if direct_screen_step is not None:
            return None

        browser_or_site_task = bool(
            re.search(r"\b(open|launch|start|navigate|visit|go to)\b", lowered)
            and re.search(r"\b(chrome|edge|firefox|browser|youtube|youtube\.com|https?://|www\.)\b", lowered)
        )
        direct_ui_task = bool(
            re.search(
                r"\b(type this|write this|left click|right click|double click|click at|hotkey|press key|take screenshot|screen find|screen click)\b",
                lowered,
            )
        )

        if browser_or_site_task or direct_ui_task:
            return PlanStep(
                tool="computer_control",
                args={
                    "action": "autonomous_task",
                    "goal": query,
                    "max_steps": 14,
                    "safety_mode": "strict",
                },
            )

        return None

    @staticmethod
    def _direct_screen_process_step(query: str) -> PlanStep | None:
        lowered = AgentLoop._normalize(query)
        if not lowered:
            return None

        latest_requested = bool(
            re.search(r"\b(latest|last|previous|recent)\b.*\b(screen|camera|frame|capture)\b", lowered)
        )

        screen_requested = bool(
            re.search(
                r"\b(view|show|see|watch|analyze|inspect)\b.*\b(screen|display|monitor)\b|"
                r"\bwhat(?:'s| is)\s+on\s+my\s+screen\b",
                lowered,
            )
        )
        camera_requested = bool(
            re.search(
                r"\b(view|show|see|watch|analyze|inspect)\b.*\b(camera|webcam)\b|"
                r"\bwhat(?:'s| is)\s+on\s+my\s+camera\b",
                lowered,
            )
        )

        if not (latest_requested or screen_requested or camera_requested):
            return None

        angle = "camera" if camera_requested else "screen"
        action = "view_latest" if latest_requested else "view_now"

        args: dict[str, Any] = {
            "action": action,
            "angle": angle,
            "text": query,
        }
        if action == "view_latest":
            args["live_enrichment"] = False

        return PlanStep(tool="screen_process", args=args)

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

    @staticmethod
    def _all_steps_are_computer_control(plan_steps: list[PlanStep]) -> bool:
        return bool(plan_steps) and all(step.tool == "computer_control" for step in plan_steps)

    @staticmethod
    def _all_steps_are_screen_process(plan_steps: list[PlanStep]) -> bool:
        return bool(plan_steps) and all(step.tool == "screen_process" for step in plan_steps)

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
        if normalized.startswith("media_"):
            return "media"
        if normalized in {"display_off", "display_on", "toggle_projection_mode"}:
            return "display"
        if normalized in {
            "new_tab",
            "close_tab",
            "reopen_closed_tab",
            "next_tab",
            "previous_tab",
            "refresh_page",
            "hard_refresh",
            "go_back",
            "go_forward",
            "open_history",
            "open_downloads",
        }:
            return "browser"
        if normalized in {"copy", "paste", "cut", "undo", "redo", "select_all", "save", "find", "zoom_in", "zoom_out", "zoom_reset"}:
            return "editing"
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

    @staticmethod
    def _synthesize_computer_control_response(tool_outputs: dict[str, dict[str, Any]]) -> str:
        first = next(iter(tool_outputs.values()), None)
        if not isinstance(first, dict):
            return "I could not complete that computer automation request."

        output = first.get("output")
        if not isinstance(output, dict):
            return "I could not complete that computer automation request."

        success = bool(output.get("success", False))
        verified = bool(output.get("verified", False))
        message = str(output.get("message") or "").strip()
        error_code = str(output.get("error") or "").strip()

        if success and verified:
            return message or "Computer automation completed and was verified."

        if success and not verified:
            if message:
                return f"I executed the automation steps, but could not fully verify completion yet. {message}"
            return "I executed the automation steps, but could not fully verify completion yet."

        if message and error_code:
            return f"{message} ({error_code})"
        if message:
            return message

        if error_code:
            return f"I could not complete that automation action: {error_code}."
        return "I could not complete that computer automation request."

    @staticmethod
    def _synthesize_screen_process_response(tool_outputs: dict[str, dict[str, Any]]) -> str:
        first = next(iter(tool_outputs.values()), None)
        if not isinstance(first, dict):
            return "I could not process that screen analysis request."

        output = first.get("output")
        if not isinstance(output, dict):
            return "I could not process that screen analysis request."

        success = bool(output.get("success", False))
        message = str(output.get("message") or "").strip()
        error_code = str(output.get("error") or "").strip()

        analysis = output.get("analysis") if isinstance(output.get("analysis"), dict) else {}
        summary = str(analysis.get("summary") or "").strip()

        live_session = output.get("live_session") if isinstance(output.get("live_session"), dict) else {}
        queued = bool(live_session.get("queued", False))

        if success:
            if summary and queued:
                return f"{summary} I also queued live visual enrichment."
            if summary:
                return summary
            if message:
                return message
            return "Screen analysis completed successfully."

        if message and error_code:
            return f"{message} ({error_code})"
        if message:
            return message
        if error_code:
            return f"I could not process that screen request: {error_code}."
        return "I could not process that screen analysis request."
