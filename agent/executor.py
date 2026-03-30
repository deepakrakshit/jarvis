from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

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


class ToolExecutor:
    """Executes planner steps with timeout, error handling, and optional parallelism."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        *,
        max_workers: int = 4,
        output_validator: ToolOutputValidator | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.max_workers = max(1, max_workers)
        self.output_validator = output_validator

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
            record = ExecutionRecord(
                tool=step.tool,
                args={},
                success=False,
                output=None,
                error="Invalid planner arguments: args must be an object",
                duration_ms=0,
            )
            return key, self._to_payload(record)

        definition = self.tool_registry.get(step.tool)
        if definition is None:
            record = ExecutionRecord(
                tool=step.tool,
                args=step.args,
                success=False,
                output=None,
                error="Unknown tool",
                duration_ms=0,
            )
            return key, self._to_payload(record)

        started_total = time.perf_counter()
        attempt_args = dict(step.args)
        last_error = ""
        last_output: Any = None

        for attempt in (1, 2):
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(definition.fn, attempt_args),
                    timeout=definition.timeout_seconds,
                )
                last_output = result

                if self.output_validator is not None:
                    validation = self.output_validator.validate_tool_output(step.tool, attempt_args, result)
                    if not validation.valid:
                        last_error = validation.reason
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
                        )
                        return key, self._to_payload(record)

                record = ExecutionRecord(
                    tool=step.tool,
                    args=attempt_args,
                    success=True,
                    output=result,
                    error="",
                    duration_ms=int((time.perf_counter() - started_total) * 1000),
                )
                return key, self._to_payload(record)
            except asyncio.TimeoutError:
                last_error = f"Timed out after {definition.timeout_seconds}s"
                if attempt == 1:
                    logger.warning("Tool '%s' timed out; retrying once", step.tool)
                    continue
            except Exception as exc:
                logger.exception("Tool '%s' failed", step.tool)
                last_error = str(exc)
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
        }

    @staticmethod
    def _next_key(tool_name: str, seen: dict[str, int]) -> str:
        count = seen.get(tool_name, 0) + 1
        seen[tool_name] = count
        if count == 1:
            return tool_name
        return f"{tool_name}_{count}"
