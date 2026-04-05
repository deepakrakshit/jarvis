# ==============================================================================
# File: agent/executor.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Tool Execution Engine — Parallel/Sequential with Retry & Validation
#
#    - Executes planned tool steps with production-grade reliability guarantees.
#    - Parallel execution: if all tools are parallel_safe, uses asyncio.gather()
#      with ThreadPoolExecutor for concurrent tool invocation.
#    - Sequential execution: ordered step execution with result accumulation.
#    - Retry with backoff: each step gets 2 attempts for transient failures
#      (timeout, connection, rate limit, HTTP 429/5xx).
#    - Post-execution validation: integrates ToolOutputValidator for tool-specific
#      invariant checks on every result.
#    - Success inference: _infer_success_and_error() heuristic fallback when
#      tool output lacks explicit success/error fields.
#    - Confidence scoring: _tool_confidence() assigns high/medium/low based on
#      verification status, retry count, and content quality.
#    - Structured result accumulation for downstream synthesis.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from agent.planner import PlanStep
from agent.tool_registry import ToolRegistry
from agent.validator import ToolOutputValidator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionRecord:
    """Structured output for one tool execution."""

    tool: str
    args: dict[str, Any]
    success: bool
    output: Any
    error: str
    duration_ms: int
    confidence: str
    attempts: int


class ToolExecutor:
    """Executes planner steps with timeout, error handling, and optional parallelism."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        *,
        max_workers: int = 4,
        output_validator: ToolOutputValidator | None = None,
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.max_workers = max(1, max_workers)
        self.output_validator = output_validator
        self.event_sink = event_sink

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_sink is None:
            return
        try:
            self.event_sink(str(event_type or "").strip(), payload if isinstance(payload, dict) else {})
        except Exception:
            return

    def execute(self, plan: list[PlanStep]) -> dict[str, dict[str, Any]]:
        """Execute a plan and return tool keyed execution records."""
        if not plan:
            return {}

        if self._can_execute_in_parallel(plan):
            return self._execute_parallel(plan)

        return self._execute_sequential(plan)

    def _can_execute_in_parallel(self, plan: list[PlanStep]) -> bool:
        if len(plan) <= 1:
            return False

        for step in plan:
            definition = self.tool_registry.get(step.tool)
            if definition is None or not definition.parallel_safe:
                return False

        return True

    @staticmethod
    def _error_text_from_output(output: Any) -> str:
        if isinstance(output, dict):
            for key in ("error", "reason", "message"):
                value = str(output.get(key) or "").strip()
                if value:
                    return value
            return ""
        if isinstance(output, str):
            return output.strip()
        return ""

    @staticmethod
    def _looks_like_failure_text(text: str) -> bool:
        lowered = (text or "").strip().lower()
        if not lowered:
            return False
        markers = (
            "could not",
            "unable",
            "failed",
            "error",
            "unavailable",
            "missing",
            "timeout",
            "timed out",
            "not found",
            "blocked",
        )
        return any(marker in lowered for marker in markers)

    def _infer_success_and_error(self, tool_name: str, output: Any) -> tuple[bool, str]:
        if isinstance(output, dict):
            if isinstance(output.get("success"), bool):
                ok = bool(output.get("success"))
                return ok, "" if ok else self._error_text_from_output(output)

            status = str(output.get("status") or "").strip().lower()
            if status in {"error", "failed", "blocked"}:
                return False, self._error_text_from_output(output) or status
            if status == "success":
                return True, ""

            if tool_name == "internet_search":
                results = output.get("results")
                if isinstance(results, list) and results:
                    return True, ""
                return False, self._error_text_from_output(output) or "search_no_results"

            if tool_name == "public_ip":
                ip = str(output.get("ip") or "").strip()
                if ip:
                    return True, ""
                return False, self._error_text_from_output(output) or "public_ip_unavailable"

            error_text = self._error_text_from_output(output)
            if error_text and self._looks_like_failure_text(error_text):
                return False, error_text
            return True, ""

        if isinstance(output, str):
            text = output.strip()
            if not text:
                return False, "empty_output"
            if self._looks_like_failure_text(text):
                return False, text
            return True, ""

        if output is None:
            return False, "empty_output"

        return True, ""

    @staticmethod
    def _is_retryable_error_text(error_text: str) -> bool:
        lowered = (error_text or "").strip().lower()
        if not lowered:
            return False
        retryable = (
            "timeout",
            "timed out",
            "temporar",
            "connection",
            "network",
            "rate limit",
            "429",
            "5xx",
            "service unavailable",
            "try again",
        )
        return any(token in lowered for token in retryable)

    @staticmethod
    def _tool_confidence(tool_name: str, output: Any, *, success: bool, attempts: int, validated: bool) -> str:
        if not success:
            return "low"

        confidence = "high" if validated else "medium"

        if tool_name in {"app_control", "system_control", "computer_control", "computer_settings"} and isinstance(output, dict):
            verified = bool(output.get("verified"))
            confidence = "high" if verified else "medium"

        if tool_name == "internet_search" and isinstance(output, dict):
            results = output.get("results")
            if isinstance(results, list):
                trusted_count = sum(1 for item in results if isinstance(item, dict) and bool(item.get("trusted")))
                if len(results) >= 3 and trusted_count >= 1:
                    confidence = "high"
                elif len(results) >= 1:
                    confidence = "medium"
                else:
                    confidence = "low"

        if tool_name == "weather" and isinstance(output, dict):
            has_temp = isinstance(output.get("temperature_c"), (int, float)) and not isinstance(output.get("temperature_c"), bool)
            has_tool_location = bool(str(output.get("tool_location") or output.get("tool_location_label") or "").strip())
            confidence = "high" if (has_temp and has_tool_location) else "medium"

        if attempts > 1 and confidence == "high":
            confidence = "medium"

        return confidence

    def _execute_sequential(self, plan: list[PlanStep]) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        seen: dict[str, int] = {}
        for step in plan:
            key = self._next_key(step.tool, seen)
            _result_key, payload = self._run_coro(self._run_step_async(step, key))
            output[_result_key] = payload
        return output

    def _execute_parallel(self, plan: list[PlanStep]) -> dict[str, dict[str, Any]]:
        seen: dict[str, int] = {}
        indexed: list[tuple[str, PlanStep]] = []
        for step in plan:
            key = self._next_key(step.tool, seen)
            indexed.append((key, step))

        results = self._run_coro(self._gather_parallel(indexed))
        return {key: payload for key, payload in results}

    async def _gather_parallel(self, indexed_plan: list[tuple[str, PlanStep]]) -> list[tuple[str, dict[str, Any]]]:
        tasks = [self._run_step_async(step, key) for key, step in indexed_plan]
        return await asyncio.gather(*tasks)

    async def _run_step_async(self, step: PlanStep, key: str) -> tuple[str, dict[str, Any]]:
        if not isinstance(step.args, dict):
            self._emit_event(
                "tool_invalid_args",
                {
                    "result_key": key,
                    "tool": str(step.tool or ""),
                    "reason": "planner_args_not_object",
                },
            )
            record = ExecutionRecord(
                tool=step.tool,
                args={},
                success=False,
                output=None,
                error="Invalid planner arguments: args must be an object",
                duration_ms=0,
                confidence="low",
                attempts=0,
            )
            return key, self._to_payload(record)

        definition = self.tool_registry.get(step.tool)
        if definition is None:
            self._emit_event(
                "tool_unknown",
                {
                    "result_key": key,
                    "tool": str(step.tool or ""),
                },
            )
            record = ExecutionRecord(
                tool=step.tool,
                args=step.args,
                success=False,
                output=None,
                error="Unknown tool",
                duration_ms=0,
                confidence="low",
                attempts=0,
            )
            return key, self._to_payload(record)

        started_total = time.perf_counter()
        attempt_args = dict(step.args)
        last_error = ""
        last_output: Any = None
        attempts_used = 0

        self._emit_event(
            "tool_invoked",
            {
                "result_key": key,
                "tool": str(step.tool or ""),
                "timeout_seconds": float(definition.timeout_seconds),
            },
        )

        for attempt in (1, 2):
            attempts_used = attempt
            self._emit_event(
                "tool_attempt_started",
                {
                    "result_key": key,
                    "tool": str(step.tool or ""),
                    "attempt": attempt,
                },
            )
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(definition.fn, attempt_args),
                    timeout=definition.timeout_seconds,
                )
                last_output = result

                validated = False

                if self.output_validator is not None:
                    validation = self.output_validator.validate_tool_output(step.tool, attempt_args, result)
                    if not validation.valid:
                        last_error = validation.reason
                        self._emit_event(
                            "tool_attempt_validation_failed",
                            {
                                "result_key": key,
                                "tool": str(step.tool or ""),
                                "attempt": attempt,
                                "reason": str(validation.reason or "invalid_output"),
                            },
                        )
                        if attempt == 1:
                            logger.warning("Tool '%s' output invalid (%s); retrying once", step.tool, validation.reason)
                            if validation.corrected_args:
                                attempt_args = validation.corrected_args
                            continue

                        record = ExecutionRecord(
                            tool=step.tool,
                            args=attempt_args,
                            success=False,
                            output=last_output,
                            error=validation.reason,
                            duration_ms=int((time.perf_counter() - started_total) * 1000),
                            confidence="low",
                            attempts=attempts_used,
                        )
                        return key, self._to_payload(record)
                    validated = True

                inferred_success, inferred_error = self._infer_success_and_error(step.tool, result)
                if not inferred_success:
                    last_error = inferred_error or "tool_reported_failure"
                    if attempt == 1 and self._is_retryable_error_text(last_error):
                        logger.warning("Tool '%s' reported transient failure (%s); retrying once", step.tool, last_error)
                        continue

                    self._emit_event(
                        "tool_attempt_failed",
                        {
                            "result_key": key,
                            "tool": str(step.tool or ""),
                            "attempt": attempt,
                            "reason": str(last_error or "tool_reported_failure"),
                        },
                    )
                    record = ExecutionRecord(
                        tool=step.tool,
                        args=attempt_args,
                        success=False,
                        output=result,
                        error=last_error,
                        duration_ms=int((time.perf_counter() - started_total) * 1000),
                        confidence=self._tool_confidence(
                            step.tool,
                            result,
                            success=False,
                            attempts=attempts_used,
                            validated=validated,
                        ),
                        attempts=attempts_used,
                    )
                    self._emit_event(
                        "tool_failed",
                        {
                            "result_key": key,
                            "tool": str(step.tool or ""),
                            "attempts": attempts_used,
                            "duration_ms": record.duration_ms,
                            "error": str(record.error or "tool_reported_failure"),
                        },
                    )
                    return key, self._to_payload(record)

                record = ExecutionRecord(
                    tool=step.tool,
                    args=attempt_args,
                    success=inferred_success,
                    output=result,
                    error="",
                    duration_ms=int((time.perf_counter() - started_total) * 1000),
                    confidence=self._tool_confidence(
                        step.tool,
                        result,
                        success=inferred_success,
                        attempts=attempts_used,
                        validated=validated,
                    ),
                    attempts=attempts_used,
                )
                self._emit_event(
                    "tool_completed",
                    {
                        "result_key": key,
                        "tool": str(step.tool or ""),
                        "attempts": attempts_used,
                        "duration_ms": record.duration_ms,
                        "confidence": str(record.confidence or ""),
                    },
                )
                return key, self._to_payload(record)
            except asyncio.TimeoutError:
                last_error = f"Timed out after {definition.timeout_seconds}s"
                self._emit_event(
                    "tool_attempt_timeout",
                    {
                        "result_key": key,
                        "tool": str(step.tool or ""),
                        "attempt": attempt,
                        "reason": str(last_error),
                    },
                )
                if attempt == 1:
                    logger.warning("Tool '%s' timed out; retrying once", step.tool)
                    continue
            except Exception as exc:
                logger.exception("Tool '%s' failed", step.tool)
                last_error = str(exc)
                self._emit_event(
                    "tool_attempt_exception",
                    {
                        "result_key": key,
                        "tool": str(step.tool or ""),
                        "attempt": attempt,
                        "reason": str(last_error),
                    },
                )
                if attempt == 1:
                    logger.warning("Tool '%s' raised error; retrying once", step.tool)
                    continue

        record = ExecutionRecord(
            tool=step.tool,
            args=attempt_args,
            success=False,
            output=last_output,
            error=last_error or "tool_failed_after_retry",
            duration_ms=int((time.perf_counter() - started_total) * 1000),
            confidence="low",
            attempts=attempts_used,
        )
        self._emit_event(
            "tool_failed",
            {
                "result_key": key,
                "tool": str(step.tool or ""),
                "attempts": attempts_used,
                "duration_ms": record.duration_ms,
                "error": str(record.error or "tool_failed_after_retry"),
            },
        )
        return key, self._to_payload(record)

    @staticmethod
    def _run_coro(coro: Any) -> Any:
        try:
            asyncio.get_running_loop()
            running = True
        except RuntimeError:
            running = False

        if not running:
            return asyncio.run(coro)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()

    @staticmethod
    def _to_payload(record: ExecutionRecord) -> dict[str, Any]:
        return {
            "tool": record.tool,
            "args": record.args,
            "success": record.success,
            "output": record.output,
            "error": record.error,
            "duration_ms": record.duration_ms,
            "confidence": record.confidence,
            "attempts": record.attempts,
        }

    @staticmethod
    def _next_key(tool_name: str, seen: dict[str, int]) -> str:
        count = seen.get(tool_name, 0) + 1
        seen[tool_name] = count
        if count == 1:
            return tool_name
        return f"{tool_name}_{count}"
