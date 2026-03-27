from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import requests

from core.settings import AppConfig
from agent.tool_registry import ToolRegistry


@dataclass(frozen=True)
class PlanStep:
    """A single planned tool invocation produced by the planner model."""

    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class PlanDraft:
    """Planner output including steps and internal reasoning metadata."""

    plan: list[PlanStep]
    reasoning: str


class Planner:
    """Groq-backed planner that converts user intent into structured tool plans."""

    def __init__(self, config: AppConfig, tool_registry: ToolRegistry) -> None:
        self.config = config
        self.tool_registry = tool_registry

    def plan(self, user_query: str, *, max_retries: int = 2) -> PlanDraft | None:
        """Return a structured plan draft from model output.

        Returns None when parsing fails repeatedly.
        """
        if not (user_query or "").strip():
            return PlanDraft(plan=[], reasoning="No executable user query provided.")

        system_prompt = self._build_system_prompt()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query.strip()},
        ]

        for _attempt in range(max_retries + 1):
            raw = self._call_groq(messages)
            payload = self._parse_json_payload(raw)
            if payload is None:
                continue

            draft = self._parse_plan(payload)
            if draft is not None:
                return draft

        return None

    def _build_system_prompt(self) -> str:
        tools_json = json.dumps(self.tool_registry.describe_for_planner(), ensure_ascii=True, indent=2)
        return (
            "You are a deterministic planning engine.\n"
            "Your only job is to produce a tool execution plan in strict JSON.\n"
            "Never answer the user directly. Never add explanations outside JSON.\n"
            "Use internal reasoning to choose the smallest correct plan.\n"
            "Optimization rules:\n"
            "1) Minimize total tool calls.\n"
            "2) Combine related asks into one plan when possible.\n"
            "3) Avoid redundant repeated tools with identical args.\n"
            "4) Prefer parallel-safe tools together when independent.\n"
            "Weather rule: every weather step must include args.location explicitly.\n"
            "If user gives city, pass that city in args.location. If user asks 'here', pass location='here'.\n"
            "Never fabricate live data. If user forbids tools for live data, return empty plan with reasoning.\n"
            "If no tool is applicable, return {\"plan\": [], \"reasoning\": \"No tools required.\"}.\n"
            "Use ONLY tools listed below and match argument schema exactly.\n"
            "Return JSON object with exactly these top-level keys: plan, reasoning.\n"
            "Each plan item must be: {\"tool\": \"tool_name\", \"args\": { ... }}\n"
            "reasoning must be 1-2 concise lines and must not exceed 240 characters.\n"
            "Tools:\n"
            f"{tools_json}"
        )

    def _call_groq(self, messages: list[dict[str, str]]) -> str:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.config.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.groq_model,
                "messages": messages,
                "temperature": 0,
                "stream": False,
                "response_format": {"type": "json_object"},
            },
            timeout=35,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            return ""

        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else {}
        content = message.get("content") if isinstance(message, dict) else ""
        return str(content or "")

    @staticmethod
    def _extract_first_json_object(raw: str) -> str | None:
        source = (raw or "").strip()
        if not source:
            return None

        if source.startswith("{") and source.endswith("}"):
            return source

        match = re.search(r"\{[\s\S]*\}", source)
        if match:
            return match.group(0)

        return None

    def _parse_json_payload(self, raw: str) -> dict[str, Any] | None:
        json_text = self._extract_first_json_object(raw)
        if not json_text:
            return None

        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        return payload

    def _parse_plan(self, payload: dict[str, Any]) -> PlanDraft | None:
        candidate = payload.get("plan")
        if candidate is None:
            return None

        if not isinstance(candidate, list):
            return None

        reasoning = str(payload.get("reasoning") or "").strip()
        if not reasoning:
            return None

        if len(reasoning) > 240:
            reasoning = reasoning[:240].rstrip()

        parsed: list[PlanStep] = []
        for item in candidate:
            if not isinstance(item, dict):
                return None

            tool = str(item.get("tool") or "").strip()
            args = item.get("args", {})
            if not tool or not isinstance(args, dict):
                return None

            parsed.append(PlanStep(tool=tool, args=args))

        normalized = self._remove_duplicate_steps(parsed)
        return PlanDraft(plan=normalized, reasoning=reasoning)

    @staticmethod
    def _remove_duplicate_steps(plan: list[PlanStep]) -> list[PlanStep]:
        seen: set[str] = set()
        unique: list[PlanStep] = []
        for step in plan:
            signature = json.dumps(
                {
                    "tool": step.tool,
                    "args": step.args,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
            if signature in seen:
                continue
            seen.add(signature)
            unique.append(step)
        return unique
