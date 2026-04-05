# ==============================================================================
# File: agent/planner.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    LLM-Driven Task Planner — Intent to Structured JSON Plans
#
#    - Converts natural language intents into executable JSON tool step sequences.
#    - Rich system prompt with 11 few-shot examples covering weather, search,
#      app control, system control, and multi-step composite queries.
#    - Tool selection guide: maps query categories to optimal tool choices.
#    - Canonical action lists for system_control and app_control tools.
#    - Output format: {plan: [...], reasoning: '...', is_complete: bool}.
#    - Execution history aware: injects previous tool results with success/failure
#      status so the planner can adapt strategy in Re-Act loop iterations.
#    - Duplicate step deduplication via JSON signature hashing.
#    - Strict JSON parsing with retry on malformed LLM output.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from core.settings import AppConfig
from core.llm_api import chat_complete
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
    is_complete: bool = False


class Planner:
    """Provider-backed planner that converts user intent into structured tool plans."""

    def __init__(self, config: AppConfig, tool_registry: ToolRegistry) -> None:
        self.config = config
        self.tool_registry = tool_registry
        self._conversation_history: list[dict[str, str]] = []

    def plan(
        self, 
        user_query: str, 
        *, 
        max_retries: int = 2, 
        conversation_history: list[dict[str, str]] | None = None,
        execution_history: list[dict[str, Any]] | None = None,
    ) -> PlanDraft | None:
        """Return a structured plan draft from model output.

        Returns None when parsing fails repeatedly.
        """
        if not (user_query or "").strip():
            return PlanDraft(plan=[], reasoning="No executable user query provided.", is_complete=True)

        if conversation_history is not None:
            self._conversation_history = conversation_history

        system_prompt = self._build_system_prompt()
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Inject recent conversation context for multi-turn awareness.
        for turn in self._conversation_history[-4:]:
            role = turn.get("role", "")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content.strip():
                messages.append({"role": role, "content": content.strip()[:300]})

        messages.append({"role": "user", "content": user_query.strip()})

        if execution_history:
            history_text = "PREVIOUS TOOL EXECUTIONS THIS TURN:\n"
            for idx, item in enumerate(execution_history, 1):
                tool = item.get("tool", "unknown")
                args = item.get("args", {})
                success = item.get("success", False)
                error = item.get("error", "")
                result = item.get("output", "")
                history_text += f"{idx}. '{tool}' ({args}) -> Success: {success}\n"
                if not success:
                    history_text += f"   Error: {error}\n"
                else:
                    history_text += f"   Result: {str(result)[:200]}...\n"
            history_text += "\nDevise the NEXT steps to satisfy the user query based on the above results. Do NOT repeat failed steps."
            messages.append({"role": "user", "content": history_text})

        for _attempt in range(max_retries + 1):
            raw = self._call_model(messages)
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
            "# Role\n"
            "You are an autonomous Re-Act planner for a desktop assistant.\n"
            "Your ONLY job: convert the user's request into a tool execution plan as strict JSON, considering past execution history if resolving multi-step problems.\n\n"
            "# Output Format\n"
            "Return a JSON object with exactly: {\"plan\": [...], \"reasoning\": \"...\", \"is_complete\": bool}\n"
            "- \"is_complete\": true IF no more tools are needed to answer the user fully, else false.\n"
            "- \"plan\": array of {\"tool\": \"tool_name\", \"args\": {...}}\n"
            "- If no tool applies: {\"plan\": [], \"reasoning\": \"No tools required.\", \"is_complete\": true}\n\n"
            "# Planning Rules\n"
            "1. If previous tools failed according to execution history, alter your strategy or update arguments.\n"
            "2. Never answer the user directly. Never add text outside JSON.\n"
            "3. Use ONLY the tools listed below \u2014 match argument schemas exactly.\n"
            "4. Never plan shutdown, restart, or destructive delete actions.\n"
            "5. Never fabricate live data. If user forbids tools, return empty plan.\n"
            "6. If user asks to create/build/scaffold/generate a project, you MUST call coding_assist action='create_project' (not action='plan').\n\n"
            "# Tool Selection Guide\n"
            "- Weather/temperature/forecast \u2192 weather (ALWAYS include args.location)\n"
            "- Factual questions, news, 'who won', current events \u2192 internet_search\n"
            "- Open/close/launch/terminate apps \u2192 app_control (action='open'/'close')\n"
            "- Volume/brightness/mute/window/desktop/lock/media keys \u2192 system_control\n"
            "- Browser navigation, open URL, YouTube search, UI clicks \u2192 computer_control\n"
            "- Multi-step desktop workflows (click/type/hit enter/wait/revert) \u2192 computer_control action='autonomous_task' with goal=user request\n"
            "- Screen/camera understanding, 'view my screen', 'what is on my screen' \u2192 screen_process\n"
            "- 'Open file explorer' \u2192 app_control (NOT system_control)\n"
            "- Speed test \u2192 speedtest\n"
            "- IP/location queries \u2192 public_ip or network_location\n"
            "- System status/CPU/RAM \u2192 system_status\n"
            "- Time/date queries \u2192 temporal\n"
            "- Document analysis \u2192 document\n"
            "- Folder-wide PDF/doc processing (e.g., all PDFs in Downloads) \u2192 document with file_path set to folder path\n"
            "- File/folder operations (create/list/read/write/replace/move/delete) \u2192 file_controller\n"
            "- Bulk file generation requests (e.g., create N text files with random content) \u2192 "
            "file_controller action='create_random_text_files'\n"
            "- Move files based on content match (e.g., files containing a letter/text) \u2192 "
            "file_controller action='filter_move_by_content'\n"
            "- Project scaffolding, code generation, implementation planning \u2192 coding_assist\n"
            "- Dependency mismatch checks between requirements/setup/pyproject \u2192 coding_assist action='compare_dependencies'\n"
            "- Run a file/project/terminal command from natural language \u2192 coding_assist action='run_from_request'\n"
            "- Directly run known file path \u2192 coding_assist action='run_file' with file_path\n"
            "- Run a known project directory \u2192 coding_assist action='run_project' with project_path (and command if provided)\n"
            "- For project creation use coding_assist action='create_project' with name, project_type, and objective\n"
            "- For create/build project requests, never return coding_assist action='plan'\n"
            "- 'Close it' with no app name \u2192 app_control with app_name='it'\n\n"
            "# System Control Canonical Actions\n"
            "increase_volume, decrease_volume, set_volume, mute, unmute, "
            "increase_brightness, decrease_brightness, set_brightness, "
            "switch_window, minimize_window, maximize_window, restore_window, "
            "focus_window, close_window, minimize_all_windows, restore_all_windows, "
            "show_desktop, lock_screen, media_play_pause, media_next_track, "
            "media_previous_track, media_stop, new_tab, close_tab, next_tab, "
            "previous_tab, refresh_page, go_back, go_forward, "
            "zoom_in, zoom_out, zoom_reset, copy, paste, cut, undo, redo, save, find\n\n"
            "# Few-Shot Examples\n\n"
            "User: \"what's the weather in Tokyo\"\n"
            '{\"plan\": [{\"tool\": \"weather\", \"args\": {\"location\": \"Tokyo\", \"query\": \"what\'s the weather in Tokyo\"}}], '
            '\"reasoning\": \"Weather query for specific city.\"}\n\n'
            "User: \"who won the FIFA World Cup 2022\"\n"
            '{\"plan\": [{\"tool\": \"internet_search\", \"args\": {\"query\": \"who won FIFA World Cup 2022\"}}], '
            '\"reasoning\": \"Factual question requiring web search.\"}\n\n'
            "User: \"open chrome\"\n"
            '{\"plan\": [{\"tool\": \"app_control\", \"args\": {\"action\": \"open\", \"app_name\": \"chrome\"}}], '
            '\"reasoning\": \"App launch request.\"}\n\n'
            "User: \"set volume to 70\"\n"
            '{\"plan\": [{\"tool\": \"system_control\", \"args\": {\"action\": \"set_volume\", \"params\": {\"level\": 70}}}], '
            '\"reasoning\": \"Direct volume control.\"}\n\n'
            "User: \"search for cat videos on YouTube\"\n"
            '{\"plan\": [{\"tool\": \"computer_control\", \"args\": {\"action\": \"autonomous_task\", \"goal\": \"search for cat videos on YouTube\", \"max_steps\": 14, \"safety_mode\": \"strict\"}}], '
            '\"reasoning\": \"Browser automation for YouTube search.\"}\n\n'
            "User: \"what is on my screen right now\"\n"
            '{\"plan\": [{\"tool\": \"screen_process\", \"args\": {\"action\": \"view_now\", \"angle\": \"screen\", \"text\": \"what is on my screen right now\"}}], '
            '\"reasoning\": \"Immediate screen understanding request.\"}\n\n'
            "User: \"close it\"\n"
            '{\"plan\": [{\"tool\": \"app_control\", \"args\": {\"action\": \"close\", \"app_name\": \"it\"}}], '
            '\"reasoning\": \"Close last opened app via pronoun resolution.\"}\n\n'
            "User: \"what is my IP address\"\n"
            '{\"plan\": [{\"tool\": \"public_ip\", \"args\": {}}], '
            '\"reasoning\": \"IP address lookup.\"}\n\n'
            "User: \"run a speed test\"\n"
            '{\"plan\": [{\"tool\": \"speedtest\", \"args\": {}}], '
            '\"reasoning\": \"Internet speed test requested.\"}\n\n'
            "User: \"how are you\"\n"
            '{\"plan\": [], \"reasoning\": \"No tools required \u2014 conversational greeting.\"}\n\n'
            "User: \"weather in Delhi and also check my IP\"\n"
            '{\"plan\": [{\"tool\": \"weather\", \"args\": {\"location\": \"Delhi\", \"query\": \"weather in Delhi\"}}, {\"tool\": \"public_ip\", \"args\": {}}], '
            '\"reasoning\": \"Two independent requests \u2014 weather and IP lookup.\"}\n\n'
            "User: \"create a project named Calculator with most advanced calculator in python\"\n"
            '{\"plan\": [{\"tool\": \"coding_assist\", \"args\": {\"action\": \"create_project\", \"name\": \"Calculator\", \"project_type\": \"python\", \"objective\": \"Build an advanced Python calculator project with tests and documentation.\"}}], '
            '\"reasoning\": \"Project scaffolding request should use coding_assist create_project.\"}\n\n'
            "User: \"Create 50 text files in a folder named StressTest with random content in each\"\n"
            '{\"plan\": [{\"tool\": \"file_controller\", \"args\": {\"action\": \"create_random_text_files\", \"path\": \"StressTest\", \"count\": 50, \"fill_to_count\": true, \"prefix\": \"file_\", \"extension\": \".txt\"}}], '
            '\"reasoning\": \"Deterministic bulk file generation request should use file_controller, not shell syntax.\"}\n\n'
            "User: \"Create 100 random text files in a new directory called StressTest, each with exactly 1024 characters. After creating them, find all files containing the letter z and move them to a Filtered subfolder.\"\n"
            '{\"plan\": [{\"tool\": \"file_controller\", \"args\": {\"action\": \"create_random_text_files\", \"path\": \"StressTest\", \"count\": 100, \"fill_to_count\": true, \"prefix\": \"file_\", \"extension\": \".txt\", \"exact_chars\": 1024}}, {\"tool\": \"file_controller\", \"args\": {\"action\": \"filter_move_by_content\", \"path\": \"StressTest\", \"search_text\": \"z\", \"destination_subfolder\": \"Filtered\", \"extension\": \".txt\"}}], '
            '\"reasoning\": \"Chained file workflow should stay in file_controller with deterministic content filtering and move.\"}\n\n'
            "User: \"I want you to create a project name calculator. It should be production grade and modular.\"\n"
            '{\"plan\": [{\"tool\": \"coding_assist\", \"args\": {\"action\": \"create_project\", \"name\": \"Calculator\", \"project_type\": \"python\", \"target_dir\": \"Projects\", \"objective\": \"Create a production-grade modular calculator project with tests and documentation.\", \"open_after_create\": true}}], '
            '\"reasoning\": \"Explicit create-project intent must execute coding_assist create_project.\"}\n\n'
            "User: \"plan architecture for a FastAPI auth microservice\"\n"
            '{\"plan\": [{\"tool\": \"coding_assist\", \"args\": {\"action\": \"plan\", \"objective\": \"Architecture plan for a FastAPI authentication microservice.\"}}], '
            '\"reasoning\": \"Implementation planning request should use coding_assist planning action.\"}\n\n'
            "User: \"Click the Windows start button, type 'calendar', and hit enter.\"\n"
            '{\"plan\": [{\"tool\": \"computer_control\", \"args\": {\"action\": \"autonomous_task\", \"goal\": \"Click the Windows start button, type calendar, and hit enter\", \"max_steps\": 14, \"safety_mode\": \"strict\"}}], '
            '\"reasoning\": \"Desktop UI sequence should use computer_control autonomous workflow.\"}\n\n'
            "User: \"Read all PDF files in the Downloads folder and give me a table of titles, dates, and total amounts if they are invoices.\"\n"
            '{\"plan\": [{\"tool\": \"document\", \"args\": {\"file_path\": \"~/Downloads\", \"query\": \"Read all PDF files in the Downloads folder and provide a table of title, date, and total amount for invoice documents.\"}}], '
            '\"reasoning\": \"Folder-wide PDF request should use document tool with directory path.\"}\n\n'
            "User: \"Compare the project dependencies listed in requirements.txt against setup.py and find the mismatches.\"\n"
            '{\"plan\": [{\"tool\": \"coding_assist\", \"args\": {\"action\": \"compare_dependencies\", \"requirements_path\": \"requirements.txt\", \"setup_path\": \"setup.py\", \"pyproject_path\": \"pyproject.toml\"}}], '
            '\"reasoning\": \"Dependency mismatch audit should use coding_assist compare_dependencies.\"}\n\n'
            "User: \"Open the Calculator project folder and run the project in terminal.\"\n"
            '{\"plan\": [{\"tool\": \"coding_assist\", \"args\": {\"action\": \"run_from_request\", \"request\": \"Open the Calculator project folder and run the project in terminal.\", \"open_folder\": true, \"timeout_seconds\": 240}}], '
            '\"reasoning\": \"Run workflow request should use coding_assist terminal orchestration.\"}\n\n'
            "# Available Tools\n"
            f"{tools_json}"
        )

    def _call_model(self, messages: list[dict[str, str]]) -> str:
        return chat_complete(
            self.config,
            messages=messages,
            temperature=0.05,
            timeout=35,
            response_format_json=True,
        )

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

        try:
            steps: list[PlanStep] = []
            for item in payload.get("plan", []):
                tool = str(item.get("tool") or "").strip()
                if not tool:
                    continue
                args = item.get("args")
                if args is None:
                    args = {}
                elif not isinstance(args, dict):
                    continue
                steps.append(PlanStep(tool=tool, args=args))

            steps = self._remove_duplicate_steps(steps)
            reasoning = str(payload.get("reasoning") or "").strip()
            is_complete = bool(payload.get("is_complete", False))
            
            # Auto-complete if plan is empty
            if not steps:
                is_complete = True
                
            return PlanDraft(plan=steps, reasoning=reasoning, is_complete=is_complete)
        except Exception:
            return None

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
