# ==============================================================================
# File: agent/validator.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Plan & Output Validation Engine — Safety & Invariant Checks
#
#    - Dual-purpose validation system for pre-execution and post-execution checks.
#    - PlanValidator (pre-execution): enforces max 8 steps per plan, max 3
#      system_control steps, tool existence, and argument schema validation.
#    - ToolOutputValidator (post-execution): per-tool invariant verification.
#    - Weather validation: checks temperature is numeric, location matches request,
#      generates corrected args for one-shot retry on location mismatch.
#    - Internet search validation: verifies results list structure, checks
#      title/snippet/link fields, measures query-result relevance overlap.
#    - App control validation: verifies status in {success, ambiguous, error},
#      checks verified field, validates app name presence.
#    - System control validation: checks action, status, success, verified, message.
#    - Screen process validation: structural check including analysis.summary,
#      analysis.objects, and live_session fields.
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
        if tool_name == "internet_search":
            return self._validate_internet_search_output(input_args, output)

        if tool_name == "public_ip":
            return self._validate_public_ip_output(output)

        if tool_name == "app_control":
            return self._validate_app_control_output(output)

        if tool_name == "system_control":
            return self._validate_system_control_output(output)

        if tool_name in {"computer_control", "computer_settings"}:
            return self._validate_action_tool_output(output)

        if tool_name == "screen_process":
            return self._validate_screen_process_output(output)

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
    def _normalize_search_query(query: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(query or "").strip().lower())
        cleaned = re.sub(
            r"^\s*(?:check|search|lookup|find|please|could you|can you)\b(?:\s+(?:the\s+)?)?(?:latest\s+|recent\s+|current\s+)?(?:news\s+)?(?:about\s+|on\s+|for\s+)?",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,!?:;-")
        return cleaned

    @staticmethod
    def _query_tokens(text: str) -> set[str]:
        stop = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "to",
            "of",
            "in",
            "on",
            "for",
            "latest",
            "current",
            "news",
            "about",
        }
        return {token for token in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(token) >= 2 and token not in stop}

    def _validate_internet_search_output(self, input_args: dict[str, Any], output: Any) -> ToolOutputValidationResult:
        if not isinstance(output, dict):
            return ToolOutputValidationResult(False, "search_output_not_object")

        query = str(output.get("query") or input_args.get("query") or "").strip()
        results = output.get("results")
        error_text = str(output.get("error") or "").strip()

        if not isinstance(results, list):
            return ToolOutputValidationResult(False, "search_results_not_list")

        if not results:
            normalized_retry_query = self._normalize_search_query(str(input_args.get("query") or ""))
            corrected_args = None
            if normalized_retry_query and normalized_retry_query != str(input_args.get("query") or "").strip().lower():
                corrected_args = dict(input_args)
                corrected_args["query"] = normalized_retry_query
            return ToolOutputValidationResult(False, error_text or "search_no_results", corrected_args=corrected_args)

        query_tokens = self._query_tokens(query)
        overlap_total = 0

        for item in results:
            if not isinstance(item, dict):
                return ToolOutputValidationResult(False, "search_result_item_not_object")

            title = str(item.get("title") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            link = str(item.get("link") or "").strip()

            if not (title or snippet or link):
                return ToolOutputValidationResult(False, "search_result_item_empty")

            probe = f"{title} {snippet}".lower()
            overlap_total += sum(1 for token in query_tokens if token in probe)

        if query_tokens and overlap_total <= 0:
            return ToolOutputValidationResult(False, "search_results_low_relevance")

        return ToolOutputValidationResult(True, "ok")

    @staticmethod
    def _validate_public_ip_output(output: Any) -> ToolOutputValidationResult:
        if not isinstance(output, dict):
            return ToolOutputValidationResult(False, "public_ip_output_not_object")

        ip = str(output.get("ip") or "").strip()
        error_text = str(output.get("error") or "").strip()
        if ip:
            return ToolOutputValidationResult(True, "ok")

        return ToolOutputValidationResult(False, error_text or "public_ip_unavailable")

    @staticmethod
    def _normalize_location(value: str) -> str:
        lowered = str(value or "").strip().lower()
        lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
        lowered = re.sub(r"\b(city|district|state|province)\b", " ", lowered)
        cleaned = re.sub(r"\s+", " ", lowered).strip()
        return cleaned

    @staticmethod
    def _is_numeric(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _location_matches(requested: str, actual: str) -> bool:
        if not requested or not actual:
            return False

        if requested == actual:
            return True

        if requested.startswith(f"{actual} ") or actual.startswith(f"{requested} "):
            return True

        requested_tokens = {tok for tok in requested.split() if tok}
        actual_tokens = {tok for tok in actual.split() if tok}
        if not requested_tokens or not actual_tokens:
            return False

        overlap = len(requested_tokens.intersection(actual_tokens))
        if overlap <= 0:
            return False

        # Accept city-only tool labels when the request is city/state/country.
        if len(actual_tokens) == 1 or len(requested_tokens) == 1:
            return True

        required_overlap = min(2, len(requested_tokens), len(actual_tokens))
        return overlap >= required_overlap

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

    @staticmethod
    def _validate_app_control_output(output: Any) -> ToolOutputValidationResult:
        if not isinstance(output, dict):
            return ToolOutputValidationResult(False, "app_output_not_object")

        status = str(output.get("status") or "").strip().lower()
        if status not in {"success", "ambiguous", "error"}:
            return ToolOutputValidationResult(False, "app_invalid_status")

        if status == "success":
            verified = output.get("verified")
            if not isinstance(verified, bool):
                return ToolOutputValidationResult(False, "app_missing_verified")

        if status == "ambiguous":
            candidates = output.get("candidates")
            if not isinstance(candidates, list):
                return ToolOutputValidationResult(False, "app_missing_candidates")

        if status == "error":
            reason = str(output.get("reason") or "").strip()
            if not reason:
                return ToolOutputValidationResult(False, "app_missing_reason")

        return ToolOutputValidationResult(True, "ok")

    @staticmethod
    def _validate_action_tool_output(output: Any) -> ToolOutputValidationResult:
        if not isinstance(output, dict):
            return ToolOutputValidationResult(False, "action_output_not_object")

        status = str(output.get("status") or "").strip().lower()
        success = output.get("success")
        verified = output.get("verified")
        action = str(output.get("action") or "").strip().lower()

        if status not in {"success", "error"}:
            return ToolOutputValidationResult(False, "action_invalid_status")
        if not action:
            return ToolOutputValidationResult(False, "action_missing_name")
        if not isinstance(success, bool):
            return ToolOutputValidationResult(False, "action_missing_success")
        if not isinstance(verified, bool):
            return ToolOutputValidationResult(False, "action_missing_verified")

        message = str(output.get("message") or "").strip()
        if not message:
            return ToolOutputValidationResult(False, "action_missing_message")

        return ToolOutputValidationResult(True, "ok")

    @staticmethod
    def _validate_screen_process_output(output: Any) -> ToolOutputValidationResult:
        if not isinstance(output, dict):
            return ToolOutputValidationResult(False, "screen_output_not_object")

        status = str(output.get("status") or "").strip().lower()
        success = output.get("success")
        verified = output.get("verified")
        action = str(output.get("action") or "").strip().lower()
        message = str(output.get("message") or "").strip()

        if status not in {"success", "error"}:
            return ToolOutputValidationResult(False, "screen_invalid_status")
        if action != "screen_process":
            return ToolOutputValidationResult(False, "screen_invalid_action")
        if not isinstance(success, bool):
            return ToolOutputValidationResult(False, "screen_missing_success")
        if not isinstance(verified, bool):
            return ToolOutputValidationResult(False, "screen_missing_verified")
        if not message:
            return ToolOutputValidationResult(False, "screen_missing_message")

        analysis = output.get("analysis")
        if not isinstance(analysis, dict):
            return ToolOutputValidationResult(False, "screen_missing_analysis")

        summary = str(analysis.get("summary") or "").strip()
        if success and not summary:
            return ToolOutputValidationResult(False, "screen_missing_summary")

        objects = analysis.get("objects")
        if not isinstance(objects, list):
            return ToolOutputValidationResult(False, "screen_objects_not_list")

        metrics = analysis.get("metrics")
        if success and not isinstance(metrics, dict):
            return ToolOutputValidationResult(False, "screen_metrics_not_object")

        history = analysis.get("history")
        if not isinstance(history, dict):
            return ToolOutputValidationResult(False, "screen_history_not_object")

        live_session = output.get("live_session")
        if not isinstance(live_session, dict):
            return ToolOutputValidationResult(False, "screen_live_session_not_object")

        return ToolOutputValidationResult(True, "ok")
