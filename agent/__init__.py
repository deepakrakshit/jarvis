# ==============================================================================
# File: agent/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Autonomous Agent Package — Re-Act Architecture Exports
#
#    - Exports the core agent loop components for the reasoning architecture.
#    - AgentLoop: the autonomous plan-execute-observe-synthesize cycle engine.
#    - Planner: LLM-driven task decomposition into structured JSON plans.
#    - ToolExecutor: parallel/sequential tool execution with retry logic.
#    - Synthesizer: natural language response generation from tool outputs.
#    - ToolRegistry: centralized tool definitions and service bindings.
#    - Validator: pre-execution safety checks and post-execution invariants.
#    - Designed as a self-contained, pluggable reasoning subsystem.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from agent.agent_loop import AgentLoop, AgentLoopResult
from agent.executor import ToolExecutor
from agent.planner import PlanDraft, Planner, PlanStep
from agent.synthesizer import Synthesizer
from agent.tool_registry import ToolDefinition, ToolRegistry, build_default_tool_registry
from agent.validator import PlanValidator, ToolOutputValidator, ValidationResult

__all__ = [
    "AgentLoop",
    "AgentLoopResult",
    "Planner",
    "PlanDraft",
    "PlanStep",
    "Synthesizer",
    "ToolExecutor",
    "ToolDefinition",
    "ToolRegistry",
    "build_default_tool_registry",
    "PlanValidator",
    "ToolOutputValidator",
    "ValidationResult",
]
