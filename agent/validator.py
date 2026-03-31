from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from agent.planner import PlanStep
from agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationResult:
    """Validation decision for a generated execution plan."""

    approved: bool
    reason: str


@dataclass(frozen=True)
class ToolOutputValidationResult:
    """Validation result for one tool output payload."""

    valid: bool
    reason: str
    corrected_args: dict[str, Any] | None = None


class PlanValidator:
    """Validates planner output before execution."""

    def __init__(self, tool_registry: ToolRegistry, *, max_steps: int = 8) -> None:
        self.tool_registry = tool_registry
        self.max_steps = max_steps

    def validate(self, plan: list[PlanStep]) -> ValidationResult:
        """Validate tool names and argument shape for each step."""
        if len(plan) > self.max_steps:
            return ValidationResult(False, f"Plan has too many steps: {len(plan)} > {self.max_steps}")

        system_control_steps = sum(1 for step in plan if step.tool == "system_control")
        if system_control_steps > 3:
            return ValidationResult(False, "Plan exceeds max 3 system_control actions per request")

        for idx, step in enumerate(plan, start=1):
            if not self.tool_registry.has(step.tool):
                return ValidationResult(False, f"Step {idx} uses unknown tool '{step.tool}'")

            valid, reason = self.tool_registry.validate_args(step.tool, step.args)
            if not valid:
                return ValidationResult(False, f"Step {idx} args invalid for '{step.tool}': {reason}")

        return ValidationResult(True, "approved")


class ToolOutputValidator:
    """Validates executed tool payloads and suggests one-shot retry corrections."""

    def validate_tool_output(
        self,
        tool_name: str,
        input_args: dict[str, Any],
        output: Any,
    ) -> ToolOutputValidationResult:
        """Validate output payload against tool-specific invariants."""
        if tool_name == "system_control":
            return self._validate_system_control_output(output)

        if tool_name != "weather":
            return ToolOutputValidationResult(True, "ok")

        if not isinstance(output, dict):
            logger.warning("[WEATHER] requested_location=%s tool_location=%s status=INVALID", input_args.get("location"), "")
            return ToolOutputValidationResult(False, "weather_output_not_object")

        requested_location = self._normalize_location(str(input_args.get("location") or ""))
        tool_location = self._normalize_location(str(output.get("tool_location") or output.get("tool_location_label") or ""))

        if not bool(output.get("success", False)):
            logger.warning(
                "[WEATHER] requested_location=%s tool_location=%s status=INVALID",
                requested_location,
                tool_location,
            )
            return ToolOutputValidationResult(False, str(output.get("error") or "weather_tool_failed"))

        temp_value = output.get("temperature_c")
        if temp_value is None:
            logger.warning(
                "[WEATHER] requested_location=%s tool_location=%s status=INVALID",
                requested_location,
                tool_location,
            )
            return ToolOutputValidationResult(False, "missing_temperature")

        if not self._is_numeric(temp_value):
            logger.warning(
                "[WEATHER] requested_location=%s tool_location=%s status=INVALID",
                requested_location,
                tool_location,
            )
            return ToolOutputValidationResult(False, "invalid_temperature_type")

        if requested_location and requested_location not in {"here", "local", "my location", "current location"}:
            if not self._location_matches(requested_location, tool_location):
                logger.warning(
                    "[WEATHER] requested_location=%s tool_location=%s status=INVALID",
                    requested_location,
                    tool_location,
                )
                corrected = dict(input_args)
                corrected["location"] = requested_location
                return ToolOutputValidationResult(False, "location_mismatch", corrected_args=corrected)

        logger.info(
            "[WEATHER] requested_location=%s tool_location=%s status=VALID",
            requested_location,
            tool_location,
        )
        return ToolOutputValidationResult(True, "ok")

    @staticmethod
    def _normalize_location(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", (value or "").strip().lower())
        return cleaned.strip(" .,!?;:")

    @staticmethod
    def _is_numeric(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _location_matches(requested: str, actual: str) -> bool:
        if not requested or not actual:
            return False

        if requested == actual:
            return True

        requested_tokens = {tok for tok in requested.split() if tok}
        actual_tokens = {tok for tok in actual.split() if tok}
        if not requested_tokens or not actual_tokens:
            return False

        overlap = len(requested_tokens.intersection(actual_tokens))
        return overlap >= max(1, min(2, len(requested_tokens)))

    @staticmethod
    def _validate_system_control_output(output: Any) -> ToolOutputValidationResult:
        if not isinstance(output, dict):
            return ToolOutputValidationResult(False, "system_output_not_object")

        action = str(output.get("action") or "").strip().lower()
        status = str(output.get("status") or "").strip().lower()
        success = output.get("success")
        verified = output.get("verified")

        if not action:
            return ToolOutputValidationResult(False, "system_missing_action")
        if status not in {"success", "error", "blocked"}:
            return ToolOutputValidationResult(False, "system_invalid_status")
        if not isinstance(success, bool):
            return ToolOutputValidationResult(False, "system_missing_success")
        if not isinstance(verified, bool):
            return ToolOutputValidationResult(False, "system_missing_verified")

        if not success:
            error_code = str(output.get("error") or "").strip()
            if not error_code:
                return ToolOutputValidationResult(False, "system_missing_error")
            return ToolOutputValidationResult(True, "ok")

        message = str(output.get("message") or "").strip()
        if not message:
            return ToolOutputValidationResult(False, "system_missing_message")
        return ToolOutputValidationResult(True, "ok")
