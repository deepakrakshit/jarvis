from __future__ import annotations

import base64
import io
import json
import random
import re
import string
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
import logging
import datetime
import os
from typing import Optional

from core.settings import AppConfig

try:
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _PYAUTOGUI = True
except Exception:
    pyautogui = None  # type: ignore[assignment]
    _PYAUTOGUI = False

try:
    import pyperclip

    _PYPERCLIP = True
except Exception:
    pyperclip = None  # type: ignore[assignment]
    _PYPERCLIP = False

try:
    import psutil
except Exception:
    psutil = None  # type: ignore[assignment]

try:
    import pygetwindow as gw  # type: ignore
except Exception:
    gw = None  # type: ignore[assignment]


_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_FIRST_NAMES = [
    "Alex",
    "Jordan",
    "Taylor",
    "Morgan",
    "Casey",
    "Riley",
    "Drew",
    "Quinn",
    "Avery",
    "Blake",
    "Cameron",
    "Dakota",
    "Emerson",
    "Finley",
    "Harper",
]
_LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Wilson",
    "Moore",
    "Taylor",
    "Anderson",
    "Thomas",
    "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]

_BROWSER_PROCESS_HINTS: dict[str, tuple[str, ...]] = {
    "chrome": ("chrome",),
    "edge": ("msedge", "edge"),
    "firefox": ("firefox",),
}

_RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_PLANNER_ALLOWED_ACTIONS = {
    "click",
    "double_click",
    "right_click",
    "type",
    "press",
    "hotkey",
    "scroll",
    "wait",
    "screen_click",
    "done",
    "fail",
}
_PLANNER_FAILURE_MARKERS = (
    "missing",
    "unavailable",
    "could not",
    "error",
    "failed",
    "rate limit",
    "429",
    "parse",
    "timeout",
)


@dataclass(frozen=True)
class ActionResult:
    status: str
    action: str
    success: bool
    verified: bool
    message: str
    error: str = ""
    state: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action": self.action,
            "success": self.success,
            "verified": self.verified,
            "message": self.message,
            "error": self.error,
            "state": dict(self.state or {}),
        }


@dataclass(frozen=True)
class SafetyPolicy:
    blocked_hotkeys: tuple[tuple[str, ...], ...] = (
        ("ctrl", "alt", "delete"),
        ("win", "r"),
        ("win", "x"),
    )
    blocked_type_patterns: tuple[str, ...] = (
        r"\bshutdown\b",
        r"\brestart\b",
        r"\bformat\b",
        r"\bdel\s+/s\b",
        r"\brm\s+-rf\b",
        r"\breg\s+delete\b",
    )
    max_typed_chars: int = 4000


class VisionProvider:
    """Pluggable vision provider wrapper.

    Currently delegates to the controller's internal screen analysis but
    provides a clear extension point for integrating specialized vision
    backends (local ML models, remote APIs, etc.).
    """

    def __init__(self, controller: "ComputerController") -> None:
        self._controller = controller

    def find_element(self, description: str) -> tuple[int, int] | None:
        try:
            return self._controller._analyze_screen_for_element(description)
        except Exception:
            return None


class ComputerController:
    def __init__(self, config: AppConfig, *, dry_run: bool = False, safety_mode: str = "strict") -> None:
        self._config = config
        self._dry_run = bool(dry_run)
        self._safety_mode = str(safety_mode or "strict").strip().lower() or "strict"
        self._policy = SafetyPolicy()
        # Logger and audit path
        self._logger = logging.getLogger("jarvis.computer_control")
        try:
            audit_cfg = getattr(self._config, "audit_log_path", None)
            if audit_cfg:
                self._audit_path = Path(str(audit_cfg))
            else:
                self._audit_path = Path("data") / "actions_log.jsonl"
        except Exception:
            self._audit_path = Path("data") / "actions_log.jsonl"

        # Vision abstraction (delegates to existing analysis by default)
        self._vision = VisionProvider(self)

    def handle(self, parameters: dict[str, Any]) -> dict[str, Any]:
        action = str((parameters or {}).get("action") or "").strip().lower()
        if not action:
            return self._error("unknown", "missing_action", "Please specify an action for computer_control.")

        if action == "autonomous_task":
            return self._autonomous_task(parameters)

        if action == "open_browser_manual":
            browser = str(parameters.get("browser") or parameters.get("app") or "chrome")
            return self._open_browser_manual(browser).to_dict()

        if action == "open_app_manual":
            app_name = str(parameters.get("app") or parameters.get("name") or "").strip()
            if not app_name:
                return self._error(action, "missing_app", "Missing app name for open_app_manual.")
            return self._open_app_manual(app_name).to_dict()

        if action == "navigate_url_manual":
            url = str(parameters.get("url") or parameters.get("target") or "").strip()
            if not url:
                return self._error(action, "missing_url", "Missing URL for navigate_url_manual.")
            return self._navigate_url_manual(url).to_dict()

        return self._execute_atomic(action, parameters).to_dict()

    def _autonomous_task(self, parameters: dict[str, Any]) -> dict[str, Any]:
        goal = str(parameters.get("goal") or parameters.get("text") or parameters.get("description") or "").strip()
        if not goal:
            return self._error("autonomous_task", "missing_goal", "Autonomous task requires a goal.")

        max_steps = self._clamp_int(parameters.get("max_steps", 14), 1, 25)
        task_id = f"task-{int(time.time() * 1000)}"
        history: list[dict[str, Any]] = []

        shortcut_script = self._build_shortcut_script(goal, parameters)
        allow_shortcut_fallback = bool(parameters.get("allow_shortcut_fallback", True))

        browser, url = self._infer_browser_bootstrap(goal, parameters)
        if browser:
            opened = self._open_browser_manual(browser)
            history.append({"step": 0, "action": opened.action, "success": opened.success, "message": opened.message})
            if not opened.success:
                return self._error(
                    "autonomous_task",
                    opened.error or "execution_failed",
                    f"Failed during browser bootstrap: {opened.message}",
                    state={"task_id": task_id, "history": history},
                )

        if url:
            navigated = self._navigate_url_manual(url)
            history.append({"step": 0, "action": navigated.action, "success": navigated.success, "message": navigated.message})
            if not navigated.success:
                return self._error(
                    "autonomous_task",
                    navigated.error or "execution_failed",
                    f"Failed during URL navigation: {navigated.message}",
                    state={"task_id": task_id, "history": history},
                )

        failures = 0
        planner_failures = 0
        for step in range(1, max_steps + 1):
            decision = self._decide_next_action(goal=goal, history=history, step=step, max_steps=max_steps)
            decision_action = str(decision.get("action") or "").strip().lower()
            decision_args = decision.get("args") if isinstance(decision.get("args"), dict) else {}
            decision_reason = str(decision.get("reason") or "").strip()

            if decision_action in {"", "done"}:
                if self._reason_indicates_planner_issue(decision_reason):
                    planner_failures += 1
                    if planner_failures < 3:
                        time.sleep(0.25 * planner_failures)
                        continue

                    if allow_shortcut_fallback and shortcut_script and not history:
                        return self._run_shortcut_script(
                            task_id=task_id,
                            goal=goal,
                            script=shortcut_script,
                            final_reason="planner_fallback_shortcut",
                            completion_message="Autonomous task completed using fallback deterministic steps after planner retries.",
                        )

                    return self._error(
                        "autonomous_task",
                        "planner_unavailable",
                        f"Autonomous planner could not continue: {decision_reason or 'unknown planner issue.'}",
                        state={"task_id": task_id, "goal": goal, "history": history, "final_reason": decision_reason},
                    )

                if not history:
                    return self._error(
                        "autonomous_task",
                        "completion_unverified",
                        "Autonomous task ended without executing any verified steps.",
                        state={"task_id": task_id, "goal": goal, "history": history, "final_reason": decision_reason},
                    )

                return self._success(
                    "autonomous_task",
                    "Autonomous task completed.",
                    verified=True,
                    state={
                        "task_id": task_id,
                        "goal": goal,
                        "steps_executed": len(history),
                        "history": history,
                        "final_reason": decision_reason,
                    },
                )

            if decision_action == "fail":
                if self._reason_indicates_planner_issue(decision_reason):
                    planner_failures += 1
                    if planner_failures < 3:
                        time.sleep(0.25 * planner_failures)
                        continue

                    if allow_shortcut_fallback and shortcut_script and not history:
                        return self._run_shortcut_script(
                            task_id=task_id,
                            goal=goal,
                            script=shortcut_script,
                            final_reason="planner_fallback_shortcut",
                            completion_message="Autonomous task completed using fallback deterministic steps after planner retries.",
                        )

                    return self._error(
                        "autonomous_task",
                        "planner_unavailable",
                        f"Autonomous planner unavailable: {decision_reason or 'unknown planner issue.'}",
                        state={"task_id": task_id, "history": history},
                    )

                return self._error(
                    "autonomous_task",
                    "model_requested_stop",
                    decision_reason or "Model requested stop.",
                    state={"task_id": task_id, "history": history},
                )

            outcome = self._execute_atomic(decision_action, decision_args)
            planner_failures = 0
            history.append(
                {
                    "step": step,
                    "action": decision_action,
                    "args": dict(decision_args),
                    "success": outcome.success,
                    "verified": outcome.verified,
                    "message": outcome.message,
                    "error": outcome.error,
                    "reason": decision_reason,
                }
            )

            if not outcome.success:
                failures += 1
                if failures >= 3:
                    return self._error(
                        "autonomous_task",
                        outcome.error or "execution_failed",
                        f"Autonomous execution failed repeatedly: {outcome.message}",
                        state={"task_id": task_id, "history": history},
                    )
            else:
                failures = 0

        return self._error(
            "autonomous_task",
            "max_steps_reached",
            "Autonomous task stopped after reaching max_steps.",
            state={"task_id": task_id, "history": history},
        )

    def _execute_atomic(self, action: str, params: dict[str, Any]) -> ActionResult:
        normalized = str(action or "").strip().lower()

        if normalized in {"type", "write", "write_this", "type_this"}:
            text = str(params.get("text") or params.get("value") or "")
            if not text:
                return self._err(normalized, "missing_text", "No text provided.")
            if not self._is_safe_text(text):
                return self._err(normalized, "unsafe_text", "Typed text blocked by safety policy.")
            return self._type_text(text)

        if normalized in {"smart_type"}:
            text = str(params.get("text") or params.get("value") or "")
            if not text:
                return self._err(normalized, "missing_text", "No text provided.")
            if not self._is_safe_text(text):
                return self._err(normalized, "unsafe_text", "Typed text blocked by safety policy.")
            return self._smart_type(text, clear_first=bool(params.get("clear_first", True)))

        if normalized in {"click", "left_click"}:
            return self._click(params, button="left", clicks=1, action_name=normalized)
        if normalized == "double_click":
            return self._click(params, button="left", clicks=2, action_name=normalized)
        if normalized == "right_click":
            return self._click(params, button="right", clicks=1, action_name=normalized)

        if normalized == "move":
            x = self._maybe_int(params.get("x"))
            y = self._maybe_int(params.get("y"))
            if x is None or y is None:
                return self._err(normalized, "missing_coordinates", "x and y are required.")
            duration = self._maybe_float(params.get("duration"), fallback=0.25)
            return self._move_mouse(x, y, duration)

        if normalized == "drag":
            x1 = self._maybe_int(params.get("x1"))
            y1 = self._maybe_int(params.get("y1"))
            x2 = self._maybe_int(params.get("x2"))
            y2 = self._maybe_int(params.get("y2"))
            if None in (x1, y1, x2, y2):
                return self._err(normalized, "missing_coordinates", "x1, y1, x2, and y2 are required.")
            duration = self._maybe_float(params.get("duration"), fallback=0.45)
            return self._drag(int(x1), int(y1), int(x2), int(y2), duration)

        if normalized == "hotkey":
            keys_raw = params.get("keys")
            keys = self._parse_keys(keys_raw)
            if not keys:
                return self._err(normalized, "missing_keys", "Hotkey requires keys.")
            if not self._is_safe_hotkey(keys):
                return self._err(normalized, "blocked_hotkey", "Hotkey blocked by safety policy.")
            return self._hotkey(keys)

        if normalized in {"press", "press_key"}:
            key = str(params.get("key") or params.get("value") or "").strip().lower()
            if not key:
                return self._err(normalized, "missing_key", "Key is required.")
            return self._press(key)

        if normalized == "scroll":
            direction = str(params.get("direction") or "down").strip().lower() or "down"
            amount = self._clamp_int(params.get("amount", 3), 1, 25)
            return self._scroll(direction, amount)

        if normalized == "copy":
            return self._copy_clipboard()

        if normalized == "paste":
            text = str(params.get("text") or params.get("value") or "")
            if not self._is_safe_text(text):
                return self._err(normalized, "unsafe_text", "Paste text blocked by safety policy.")
            return self._paste_clipboard(text)

        if normalized == "screenshot":
            path = str(params.get("path") or "").strip()
            return self._screenshot(path)

        if normalized == "wait":
            seconds = self._maybe_float(params.get("seconds"), fallback=1.0)
            seconds = max(0.0, min(seconds, 12.0))
            if self._dry_run:
                return self._ok("wait", f"Dry-run wait {seconds:.2f}s.", verified=False, state={"seconds": seconds})
            time.sleep(seconds)
            return self._ok("wait", f"Waited {seconds:.2f}s.", verified=True, state={"seconds": seconds})

        if normalized == "screen_size":
            return self._screen_size()

        if normalized == "screen_find":
            description = str(params.get("description") or params.get("text") or "").strip()
            if not description:
                return self._err(normalized, "missing_description", "screen_find requires description.")
            coords = self._vision.find_element(description)
            if coords is None:
                return self._err(normalized, "not_found", "Could not find matching element on screen.")
            return self._ok(
                "screen_find",
                f"Found element at ({coords[0]}, {coords[1]}).",
                verified=True,
                state={"x": coords[0], "y": coords[1], "description": description},
            )

        if normalized == "screen_click":
            description = str(params.get("description") or params.get("text") or "").strip()
            if not description:
                return self._err(normalized, "missing_description", "screen_click requires description.")
            coords = self._vision.find_element(description)
            if coords is None:
                return self._err(normalized, "not_found", "Could not find matching element on screen.")
            button = str(params.get("button") or "left").strip().lower() or "left"
            if button not in {"left", "right"}:
                button = "left"
            click_result = self._click(
                {"x": coords[0], "y": coords[1]},
                button=button,
                clicks=1,
                action_name="screen_click",
            )
            if not click_result.success:
                return click_result
            return self._ok(
                "screen_click",
                f"{button.title()} clicked element at ({coords[0]}, {coords[1]}).",
                verified=True,
                state={"x": coords[0], "y": coords[1], "description": description},
            )

        if normalized == "random_data":
            data_type = str(params.get("type") or "name").strip().lower() or "name"
            value = self._generate_random_data(data_type)
            return self._ok("random_data", value, verified=True, state={"type": data_type, "value": value})

        if normalized == "user_data":
            field = str(params.get("field") or "name").strip().lower() or "name"
            profile = self._load_user_profile()
            value = str(profile.get(field) or "")
            if not value:
                value = self._generate_random_data(field)
            return self._ok("user_data", value, verified=bool(profile.get(field)), state={"field": field, "value": value})

        if normalized == "open_app_manual":
            app_name = str(params.get("app") or params.get("name") or "").strip()
            if not app_name:
                return self._err(normalized, "missing_app", "App name is required.")
            return self._open_app_manual(app_name)

        return self._err(normalized or "unknown", "unsupported_action", f"Unknown computer_control action: '{action}'.")

    def _open_app_manual(self, app_name: str) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("open_app_manual", "dependency_unavailable", "PyAutoGUI is required for manual app launch.")

        target = str(app_name or "").strip()
        if not target:
            return self._err("open_app_manual", "missing_app", "App name is required.")

        if self._dry_run:
            return self._ok(
                "open_app_manual",
                f"Dry-run: would open '{target}' manually using keyboard.",
                verified=False,
                state={"app": target},
            )

        try:
            pyautogui.press("win")
            time.sleep(0.35)
            pyautogui.typewrite(target, interval=0.04)
            pyautogui.press("enter")
            time.sleep(1.7)
        except Exception as exc:
            return self._err("open_app_manual", "execution_failed", f"Could not open app manually: {exc}")

        verified = self._is_process_running(target)
        message = f"Opened {target} manually." if verified else f"Launched {target}, but process verification is incomplete."
        return self._ok(
            "open_app_manual",
            message,
            verified=verified,
            state={"app": target, "process_running": verified},
        )

    def _open_browser_manual(self, browser: str) -> ActionResult:
        browser_name = self._normalize_browser(browser) or "chrome"
        opened = self._open_app_manual(browser_name)
        if not opened.success:
            return self._err("open_browser_manual", opened.error or "execution_failed", opened.message)

        running = self._is_browser_running(browser_name)
        message = f"Opened {browser_name} manually." if running else f"Launched {browser_name}, but process verification is incomplete."
        return self._ok(
            "open_browser_manual",
            message,
            verified=running,
            state={"browser": browser_name, "process_running": running},
        )

    def _navigate_url_manual(self, raw_url: str) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("navigate_url_manual", "dependency_unavailable", "PyAutoGUI is required for manual URL navigation.")

        url = self._sanitize_url(raw_url)
        if not url:
            return self._err("navigate_url_manual", "invalid_url", "The URL is invalid.")

        if self._dry_run:
            return self._ok(
                "navigate_url_manual",
                f"Dry-run: would type URL {url} and press Enter.",
                verified=False,
                state={"url": url},
            )

        try:
            pyautogui.hotkey("ctrl", "l")
            time.sleep(0.15)
            pyautogui.typewrite(url, interval=0.02)
            pyautogui.press("enter")
            time.sleep(1.6)
        except Exception as exc:
            return self._err("navigate_url_manual", "execution_failed", f"Could not navigate manually: {exc}")

        host_token = self._title_token_for_url(url)
        verified, title = self._verify_window_title(host_token)

        if verified:
            message = f"Typed full URL and navigated to {url}."
        else:
            message = f"Typed full URL and sent Enter for {url}, but title verification is pending."

        return self._ok(
            "navigate_url_manual",
            message,
            verified=verified,
            state={"url": url, "window_title": title, "title_verified": verified},
        )

    def _decide_next_action(
        self,
        *,
        goal: str,
        history: list[dict[str, Any]],
        step: int,
        max_steps: int,
    ) -> dict[str, Any]:
        api_key = str(self._config.gemini_api_key or "").strip()
        if not api_key:
            return {"action": "fail", "args": {}, "reason": "GEMINI_API_KEY missing for autonomous planning."}

        screenshot_b64 = self._capture_screen_b64()
        if not screenshot_b64:
            return {"action": "fail", "args": {}, "reason": "Could not capture screen for autonomous planning."}

        short_history = history[-8:]
        planner_prompt = (
            "You are an enterprise desktop automation planner."
            " Choose exactly one next UI action to progress toward the user's goal."
            " Allowed actions: click, double_click, right_click, type, press, hotkey, scroll, wait, screen_click, done, fail."
            " Safety constraints: avoid destructive/system-admin behavior and do not run shell commands."
            " Return strict JSON: {\"action\":\"...\",\"args\":{...},\"reason\":\"...\"}."
            " Keep reason under 140 chars."
            f" Goal: {goal}"
            f" Step: {step}/{max_steps}"
            f" Recent history: {json.dumps(short_history, ensure_ascii=True)}"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": planner_prompt},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": screenshot_b64,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 220,
                "responseMimeType": "application/json",
            },
        }

        response_payload, request_error = self._post_gemini_payload(payload=payload)
        if response_payload is None:
            return {"action": "fail", "args": {}, "reason": f"Planner model unavailable: {request_error}"}

        raw_text = self._extract_text_from_gemini_payload(response_payload)
        parsed = self._extract_json_object(raw_text)
        if not parsed:
            return {"action": "fail", "args": {}, "reason": "Model response could not be parsed."}

        action = str(parsed.get("action") or "").strip().lower()
        args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
        reason = str(parsed.get("reason") or "").strip()

        if action not in _PLANNER_ALLOWED_ACTIONS:
            return {"action": "fail", "args": {}, "reason": f"Unsupported model action: {action or 'empty'}"}

        # Validate action schema / safety before executing
        is_valid, validation_reason = self._validate_planner_action(action, args)
        if not is_valid:
            return {"action": "fail", "args": {}, "reason": f"validation_failed:{validation_reason}"}

        if action == "done" and self._reason_indicates_planner_issue(reason):
            return {"action": "fail", "args": {}, "reason": reason or "planner_unavailable"}

        return {"action": action, "args": args, "reason": reason}

    def _capture_screen_b64(self) -> str:
        if not _PYAUTOGUI:
            return ""
        try:
            image = pyautogui.screenshot()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            return ""

    def _click(self, params: dict[str, Any], *, button: str, clicks: int, action_name: str = "click") -> ActionResult:
        if not _PYAUTOGUI:
            return self._err(action_name, "dependency_unavailable", "PyAutoGUI is required for click automation.")

        x = self._maybe_int(params.get("x"))
        y = self._maybe_int(params.get("y"))
        description = str(params.get("description") or params.get("text") or "").strip()

        if (x is None or y is None) and description:
            coords = self._vision.find_element(description)
            if coords is not None:
                x, y = coords

        if x is None or y is None:
            return self._err(action_name, "missing_target", "Provide x/y coordinates or a description for click action.")
        if not self._within_screen(x, y):
            return self._err(action_name, "invalid_coordinates", "Click coordinates are outside screen bounds.")

        if self._dry_run:
            return self._ok(
                action_name,
                f"Dry-run: would {button} click at ({x}, {y}) with clicks={clicks}.",
                verified=False,
                state={"x": x, "y": y, "button": button, "clicks": clicks},
            )

        last_error = ""
        for attempt in range(3):
            try:
                pyautogui.moveTo(int(x), int(y), duration=0.08 + (attempt * 0.04))
                pyautogui.click(x=int(x), y=int(y), button=button, clicks=int(clicks))
                return self._ok(
                    action_name,
                    f"Clicked at ({x}, {y}) with {button} button.",
                    verified=True,
                    state={"x": x, "y": y, "button": button, "clicks": clicks},
                )
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.07 * (attempt + 1))

        # Recovery: try small nearby offsets to handle slight layout shifts
        offsets = [(-15, 0), (15, 0), (0, -15), (0, 15), (-10, -10), (10, 10)]
        for dx, dy in offsets:
            try:
                nx = int(x) + dx
                ny = int(y) + dy
                if not self._within_screen(nx, ny):
                    continue
                pyautogui.moveTo(nx, ny, duration=0.06)
                pyautogui.click(x=nx, y=ny, button=button, clicks=int(clicks))
                return self._ok(
                    action_name,
                    f"Clicked at nearby ({nx}, {ny}) with {button} button.",
                    verified=True,
                    state={"x": nx, "y": ny, "button": button, "clicks": clicks, "recovered": True},
                )
            except Exception:
                time.sleep(0.05)

        return self._err(action_name, "execution_failed", f"Click failed: {last_error or 'unknown error'}")

    def _move_mouse(self, x: int, y: int, duration: float) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("move", "dependency_unavailable", "PyAutoGUI is required for move action.")
        if not self._within_screen(x, y):
            return self._err("move", "invalid_coordinates", "Move coordinates are outside screen bounds.")

        if self._dry_run:
            return self._ok("move", f"Dry-run: would move to ({x}, {y}).", verified=False, state={"x": x, "y": y})

        try:
            pyautogui.moveTo(int(x), int(y), duration=float(duration))
            return self._ok("move", f"Mouse moved to ({x}, {y}).", verified=True, state={"x": x, "y": y})
        except Exception as exc:
            return self._err("move", "execution_failed", f"Move failed: {exc}")

    def _drag(self, x1: int, y1: int, x2: int, y2: int, duration: float) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("drag", "dependency_unavailable", "PyAutoGUI is required for drag action.")
        if not self._within_screen(x1, y1) or not self._within_screen(x2, y2):
            return self._err("drag", "invalid_coordinates", "Drag coordinates are outside screen bounds.")

        if self._dry_run:
            return self._ok(
                "drag",
                f"Dry-run: would drag from ({x1}, {y1}) to ({x2}, {y2}).",
                verified=False,
                state={"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            )

        try:
            pyautogui.moveTo(int(x1), int(y1), duration=0.1)
            pyautogui.dragTo(int(x2), int(y2), duration=float(duration), button="left")
            return self._ok(
                "drag",
                f"Dragged from ({x1}, {y1}) to ({x2}, {y2}).",
                verified=True,
                state={"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            )
        except Exception as exc:
            return self._err("drag", "execution_failed", f"Drag failed: {exc}")

    def _type_text(self, text: str) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("type", "dependency_unavailable", "PyAutoGUI is required for typing actions.")

        if self._dry_run:
            return self._ok("type", f"Dry-run: would type text ({len(text)} chars).", verified=False, state={"length": len(text)})

        try:
            pyautogui.typewrite(text, interval=0.03)
            preview = text[:80] + ("..." if len(text) > 80 else "")
            return self._ok("type", f"Typed text: {preview}", verified=True, state={"length": len(text)})
        except Exception as exc:
            return self._err("type", "execution_failed", f"Typing failed: {exc}")

    def _smart_type(self, text: str, *, clear_first: bool) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("smart_type", "dependency_unavailable", "PyAutoGUI is required for typing actions.")

        if self._dry_run:
            return self._ok(
                "smart_type",
                f"Dry-run: would smart-type text ({len(text)} chars).",
                verified=False,
                state={"length": len(text), "clear_first": clear_first},
            )

        try:
            if clear_first:
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.05)
                pyautogui.press("delete")
                time.sleep(0.05)

            if len(text) > 20 and _PYPERCLIP and pyperclip is not None:
                pyperclip.copy(text)
                time.sleep(0.05)
                pyautogui.hotkey("ctrl", "v")
            else:
                pyautogui.typewrite(text, interval=0.03)

            preview = text[:80] + ("..." if len(text) > 80 else "")
            return self._ok("smart_type", f"Smart-typed text: {preview}", verified=True, state={"length": len(text)})
        except Exception as exc:
            return self._err("smart_type", "execution_failed", f"Smart typing failed: {exc}")

    def _hotkey(self, keys: tuple[str, ...]) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("hotkey", "dependency_unavailable", "PyAutoGUI is required for hotkey actions.")

        if self._dry_run:
            return self._ok("hotkey", f"Dry-run: would press {'+'.join(keys)}.", verified=False, state={"keys": list(keys)})

        try:
            pyautogui.hotkey(*keys)
            return self._ok("hotkey", f"Pressed hotkey {'+'.join(keys)}.", verified=True, state={"keys": list(keys)})
        except Exception as exc:
            return self._err("hotkey", "execution_failed", f"Hotkey failed: {exc}")

    def _press(self, key: str) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("press", "dependency_unavailable", "PyAutoGUI is required for key press actions.")

        if self._dry_run:
            return self._ok("press", f"Dry-run: would press {key}.", verified=False, state={"key": key})

        try:
            pyautogui.press(key)
            return self._ok("press", f"Pressed key {key}.", verified=True, state={"key": key})
        except Exception as exc:
            return self._err("press", "execution_failed", f"Key press failed: {exc}")

    def _scroll(self, direction: str, amount: int) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("scroll", "dependency_unavailable", "PyAutoGUI is required for scroll actions.")

        if self._dry_run:
            return self._ok(
                "scroll",
                f"Dry-run: would scroll {direction} by {amount}.",
                verified=False,
                state={"direction": direction, "amount": amount},
            )

        signed = int(amount)
        if direction in {"down", "right"}:
            signed = -signed

        try:
            if direction in {"up", "down"}:
                pyautogui.scroll(signed)
            else:
                pyautogui.hscroll(signed)
            return self._ok(
                "scroll",
                f"Scrolled {direction} by {amount}.",
                verified=True,
                state={"direction": direction, "amount": amount},
            )
        except Exception as exc:
            return self._err("scroll", "execution_failed", f"Scroll failed: {exc}")

    def _copy_clipboard(self) -> ActionResult:
        if self._dry_run:
            return self._ok("copy", "Dry-run: would copy current selection.", verified=False)

        try:
            if _PYPERCLIP and pyperclip is not None:
                value = str(pyperclip.paste())
                return self._ok("copy", "Clipboard read complete.", verified=True, state={"value": value})

            if _PYAUTOGUI:
                pyautogui.hotkey("ctrl", "c")
                time.sleep(0.15)
                return self._ok("copy", "Copy command sent.", verified=False)

            return self._err("copy", "dependency_unavailable", "Clipboard access unavailable.")
        except Exception as exc:
            return self._err("copy", "execution_failed", f"Copy failed: {exc}")

    def _paste_clipboard(self, text: str) -> ActionResult:
        if self._dry_run:
            return self._ok("paste", f"Dry-run: would paste text ({len(text)} chars).", verified=False)

        if _PYPERCLIP and pyperclip is not None and _PYAUTOGUI:
            try:
                pyperclip.copy(text)
                time.sleep(0.05)
                pyautogui.hotkey("ctrl", "v")
                return self._ok("paste", "Pasted clipboard text.", verified=True, state={"length": len(text)})
            except Exception as exc:
                return self._err("paste", "execution_failed", f"Paste failed: {exc}")

        return self._err("paste", "dependency_unavailable", "Paste requires pyautogui + pyperclip.")

    def _screenshot(self, path: str) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("screenshot", "dependency_unavailable", "PyAutoGUI is required for screenshots.")

        target = str(path or (Path.home() / "Desktop" / "jarvis_screenshot.png"))
        if self._dry_run:
            return self._ok("screenshot", f"Dry-run: would save screenshot to {target}.", verified=False, state={"path": target})

        try:
            image = pyautogui.screenshot()
            image.save(target)
            return self._ok("screenshot", f"Screenshot saved to {target}.", verified=True, state={"path": target})
        except Exception as exc:
            return self._err("screenshot", "execution_failed", f"Screenshot failed: {exc}")

    def _screen_size(self) -> ActionResult:
        if not _PYAUTOGUI:
            return self._err("screen_size", "dependency_unavailable", "PyAutoGUI is required for screen size.")
        try:
            width, height = pyautogui.size()
            return self._ok("screen_size", f"{width}x{height}", verified=True, state={"width": width, "height": height})
        except Exception as exc:
            return self._err("screen_size", "execution_failed", f"Could not get screen size: {exc}")

    def _analyze_screen_for_element(self, description: str) -> tuple[int, int] | None:
        api_key = str(self._config.gemini_api_key or "").strip()
        if not api_key or not _PYAUTOGUI:
            return None

        try:
            image = pyautogui.screenshot()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            width, height = pyautogui.size()

            prompt = (
                f"Screenshot size is {width}x{height}. "
                f"Find the UI element described as: '{description}'. "
                "Return only 'x,y' center coordinates, or NOT_FOUND."
            )

            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": encoded,
                                }
                            },
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 100,
                },
            }

            response_payload, _error = self._post_gemini_payload(payload=payload)
            if response_payload is None:
                return None

            text = self._extract_text_from_gemini_payload(response_payload).strip()
            if "NOT_FOUND" in text.upper():
                return None

            match = re.search(r"(\d+)\s*,\s*(\d+)", text)
            if not match:
                return None

            x = int(match.group(1))
            y = int(match.group(2))
            if not self._within_screen(x, y):
                return None
            return x, y
        except Exception:
            return None

    @staticmethod
    def _extract_text_from_gemini_payload(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(candidates, list) or not candidates:
            return ""

        first = candidates[0] if isinstance(candidates[0], dict) else {}
        content = first.get("content") if isinstance(first, dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            return ""

        chunks: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = str(part.get("text") or "").strip()
            if text:
                chunks.append(text)
        return "\n".join(chunks).strip()

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, Any] | None:
        source = str(raw or "").strip()
        if not source:
            return None

        try:
            parsed = json.loads(source)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        source = re.sub(r"```(?:json)?", "", source).replace("```", "").strip()
        match = re.search(r"\{[\s\S]*\}", source)
        if not match:
            return None

        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    def _validate_planner_action(self, action: str, args: dict[str, Any]) -> tuple[bool, str]:
        """Validate planner-suggested action and basic args schema.

        Returns (is_valid, reason_code).
        """
        if not action:
            return False, "empty_action"
        if action not in _PLANNER_ALLOWED_ACTIONS:
            return False, "unsupported_action"
        if not isinstance(args, dict):
            return False, "invalid_args"

        # Basic per-action checks
        if action in {"click", "screen_click"}:
            if not (("x" in args and "y" in args) or (args.get("description") or args.get("text"))):
                return False, "missing_target"

        if action in {"type", "smart_type", "paste"}:
            text = str(args.get("text") or args.get("value") or "")
            if not text:
                return False, "missing_text"
            if not self._is_safe_text(text):
                return False, "unsafe_text"

        if action == "hotkey":
            keys = self._parse_keys(args.get("keys"))
            if not keys:
                return False, "missing_keys"
            if not self._is_safe_hotkey(keys):
                return False, "blocked_hotkey"

        return True, ""

    def _build_shortcut_script(self, goal: str, params: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        lowered = str(goal or "").strip().lower()
        if not lowered:
            return []

        browser, inferred_url = self._infer_browser_bootstrap(goal, params)
        search_query = self._extract_search_query(lowered)
        explicit_url = self._sanitize_url(str(params.get("url") or "").strip())

        if browser and ("google.com" in lowered or "youtube" in lowered or "search for" in lowered):
            target_url = inferred_url or explicit_url or "https://www.google.com"
            script: list[tuple[str, dict[str, Any]]] = [
                ("open_browser_manual", {"browser": browser}),
                ("navigate_url_manual", {"url": target_url}),
            ]

            if search_query and "youtube.com/results?search_query=" not in target_url:
                script.extend(
                    [
                        ("wait", {"seconds": 0.8}),
                        ("smart_type", {"text": search_query, "clear_first": False}),
                        ("press", {"key": "enter"}),
                    ]
                )
            return script

        if "open notepad" in lowered and ("python" in lowered or "write" in lowered):
            code = self._build_python_program_for_goal(goal)
            script = [("open_app_manual", {"app": "notepad"})]
            if "new file" in lowered:
                script.append(("hotkey", {"keys": "ctrl+n"}))
            if code:
                script.extend(
                    [
                        ("wait", {"seconds": 0.5}),
                        ("smart_type", {"text": code, "clear_first": False}),
                    ]
                )
            return script

        return []

    def _run_shortcut_script(
        self,
        *,
        task_id: str,
        goal: str,
        script: list[tuple[str, dict[str, Any]]],
        final_reason: str = "deterministic_shortcut",
        completion_message: str = "Autonomous task completed via deterministic shortcut plan.",
    ) -> dict[str, Any]:
        history: list[dict[str, Any]] = []
        for index, (action, args) in enumerate(script, start=1):
            outcome = self._execute_script_step(action, args)
            history.append(
                {
                    "step": index,
                    "action": action,
                    "args": dict(args),
                    "success": outcome.success,
                    "verified": outcome.verified,
                    "message": outcome.message,
                    "error": outcome.error,
                    "reason": final_reason,
                }
            )
            if not outcome.success:
                return self._error(
                    "autonomous_task",
                    outcome.error or "execution_failed",
                    f"Shortcut execution failed: {outcome.message}",
                    state={"task_id": task_id, "goal": goal, "history": history},
                )

        return self._success(
            "autonomous_task",
            completion_message,
            verified=True,
            state={
                "task_id": task_id,
                "goal": goal,
                "steps_executed": len(history),
                "history": history,
                "final_reason": final_reason,
            },
        )

    def _execute_script_step(self, action: str, args: dict[str, Any]) -> ActionResult:
        normalized = str(action or "").strip().lower()
        if normalized == "open_browser_manual":
            return self._open_browser_manual(str(args.get("browser") or "chrome"))
        if normalized == "navigate_url_manual":
            return self._navigate_url_manual(str(args.get("url") or ""))
        if normalized == "open_app_manual":
            return self._open_app_manual(str(args.get("app") or args.get("name") or ""))
        return self._execute_atomic(normalized, args)

    @staticmethod
    def _extract_search_query(text: str) -> str:
        source = str(text or "").strip()
        if not source:
            return ""

        patterns = (
            r"\bsearch(?:\s+on\s+(?:google|google\.com|youtube|youtube\.com))?\s+for\s+(.+)$",
            r"\bsearch\s+(.+?)\s+on\s+(?:google|google\.com|youtube|youtube\.com)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, source, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = str(match.group(1) or "").strip(" .?!,;:")
            candidate = re.sub(r"\s+on\s+(google|google\.com|youtube|youtube\.com)\b.*$", "", candidate, flags=re.IGNORECASE)
            candidate = candidate.strip(" .?!,;:")
            if candidate:
                return candidate
        return ""

    @staticmethod
    def _build_python_program_for_goal(goal: str) -> str:
        lowered = str(goal or "").lower()
        if "calculator" in lowered:
            return (
                "def calculator():\n"
                "    num1 = float(input('Enter first number: '))\n"
                "    op = input('Enter operator (+, -, *, /): ').strip()\n"
                "    num2 = float(input('Enter second number: '))\n\n"
                "    if op == '+':\n"
                "        print('Result:', num1 + num2)\n"
                "    elif op == '-':\n"
                "        print('Result:', num1 - num2)\n"
                "    elif op == '*':\n"
                "        print('Result:', num1 * num2)\n"
                "    elif op == '/':\n"
                "        if num2 == 0:\n"
                "            print('Error: division by zero')\n"
                "        else:\n"
                "            print('Result:', num1 / num2)\n"
                "    else:\n"
                "        print('Invalid operator')\n\n"
                "if __name__ == '__main__':\n"
                "    calculator()\n"
            )
        return "print('Hello from JARVIS automation')\n"

    @staticmethod
    def _reason_indicates_planner_issue(reason: str) -> bool:
        lowered = str(reason or "").strip().lower()
        if not lowered:
            return False
        return any(marker in lowered for marker in _PLANNER_FAILURE_MARKERS)

    def _planner_models(self) -> list[str]:
        candidates = [
            str(self._config.gemini_model or "").strip(),
            str(self._config.gemini_search_model or "").strip(),
            "gemini-2.5-flash",
        ]
        models: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in models:
                models.append(candidate)
        return models or ["gemini-2.5-flash"]

    def _post_gemini_payload(self, *, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        api_key = str(self._config.gemini_api_key or "").strip()
        if not api_key:
            return None, "missing_gemini_api_key"

        timeout_seconds = max(8.0, float(self._config.gemini_request_timeout_seconds))
        last_error = "planner_unavailable"

        for model in self._planner_models():
            for attempt in range(3):
                try:
                    response = requests.post(
                        _GEMINI_URL.format(model=model),
                        params={"key": api_key},
                        headers={"Content-Type": "application/json"},
                        json=payload,
                        timeout=timeout_seconds,
                    )
                    response.raise_for_status()
                    body = response.json()
                    if isinstance(body, dict):
                        try:
                            self._logger.debug("Gemini payload success model=%s", model)
                        except Exception:
                            pass
                        return body, ""
                    return None, "invalid_response_payload"
                except requests.exceptions.HTTPError as exc:
                    status = getattr(exc.response, "status_code", None)
                    last_error = f"http_{status}" if status is not None else "http_error"
                    try:
                        self._logger.warning("Gemini HTTP error model=%s status=%s", model, status)
                    except Exception:
                        pass
                    if status in _RETRYABLE_HTTP_STATUS_CODES and attempt < 2:
                        time.sleep(0.6 * (attempt + 1))
                        continue
                    if status in {400, 404}:
                        break
                    break
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                    last_error = "network_timeout"
                    try:
                        self._logger.warning("Gemini network timeout/connerror model=%s attempt=%s", model, attempt)
                    except Exception:
                        pass
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    break
                except Exception as exc:
                    last_error = f"request_failed: {exc}"
                    try:
                        self._logger.exception("Gemini request failed model=%s: %s", model, exc)
                    except Exception:
                        pass
                    break

        return None, last_error

    def _infer_browser_bootstrap(self, goal: str, params: dict[str, Any]) -> tuple[str, str]:
        lowered = str(goal or "").strip().lower()
        browser = self._normalize_browser(str(params.get("browser") or ""))

        explicit_url = self._sanitize_url(str(params.get("url") or "").strip())
        if explicit_url:
            return browser or "chrome", explicit_url

        if not browser:
            if "edge" in lowered:
                browser = "edge"
            elif "firefox" in lowered:
                browser = "firefox"
            elif "chrome" in lowered or "browser" in lowered or "youtube" in lowered:
                browser = "chrome"

        youtube_query = self._extract_youtube_query(lowered)
        if youtube_query:
            url = f"https://www.youtube.com/results?search_query={quote_plus(youtube_query)}"
            return browser or "chrome", url

        url = self._extract_url_from_text(lowered)
        if url:
            return browser or "chrome", url

        return browser, ""

    @staticmethod
    def _extract_youtube_query(text: str) -> str:
        patterns = (
            r"\bsearch(?:\s+on)?\s+youtube(?:\.com)?\s+(?:for|about)?\s*(.+)$",
            r"\byoutube(?:\.com)?\s+(?:for|about)\s+(.+)$",
            r"\bon\s+youtube\s+(?:for|about)\s+(.+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = str(match.group(1) or "").strip(" .?!,;:")
            if candidate:
                return candidate
        return ""

    def _extract_url_from_text(self, text: str) -> str:
        match = re.search(r"\b((?:https?://)?[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s]*)?)", text, flags=re.IGNORECASE)
        if not match:
            return ""
        return self._sanitize_url(str(match.group(1) or "").strip())

    @staticmethod
    def _sanitize_url(raw_url: str) -> str:
        candidate = str(raw_url or "").strip()
        if not candidate or any(ch.isspace() for ch in candidate):
            return ""

        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", candidate):
            candidate = f"https://{candidate}"

        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"}:
            return ""
        if not parsed.netloc:
            return ""

        host = str(parsed.netloc or "")
        if not re.fullmatch(r"[a-zA-Z0-9.-]+(?::\d{1,5})?", host):
            return ""

        host_without_port = host.split(":", 1)[0]
        if "." not in host_without_port and host_without_port.lower() != "localhost":
            return ""

        return candidate

    @staticmethod
    def _title_token_for_url(url: str) -> str:
        parsed = urlparse(url)
        host = str(parsed.netloc or "").strip().lower()
        if host.startswith("www."):
            host = host[4:]
        if not host:
            return ""
        parts = [part for part in host.split(".") if part]
        if len(parts) >= 2:
            return parts[-2]
        return parts[0]

    def _verify_window_title(self, token: str) -> tuple[bool, str]:
        if gw is None or not token:
            return False, ""

        deadline = time.time() + 5.0
        token_lower = token.lower()

        while time.time() < deadline:
            try:
                for window in gw.getAllWindows():
                    title = str(getattr(window, "title", "") or "").strip()
                    if title and token_lower in title.lower():
                        return True, title
            except Exception:
                return False, ""
            time.sleep(0.25)

        return False, ""

    def _is_browser_running(self, browser: str) -> bool:
        if psutil is None:
            return False

        hints = _BROWSER_PROCESS_HINTS.get(browser, (browser,))
        normalized_hints = {self._normalize_process_name(item) for item in hints if self._normalize_process_name(item)}
        if not normalized_hints:
            return False

        for proc in psutil.process_iter(["name"]):  # type: ignore[union-attr]
            try:
                proc_name = self._normalize_process_name(str(proc.info.get("name") or ""))
            except Exception:
                continue
            if not proc_name:
                continue
            if any(proc_name == hint or proc_name.startswith(hint) for hint in normalized_hints):
                return True
        return False

    def _is_process_running(self, process_hint: str) -> bool:
        if psutil is None:
            return False

        normalized_hint = self._normalize_process_name(process_hint)
        if not normalized_hint:
            return False

        for proc in psutil.process_iter(["name"]):  # type: ignore[union-attr]
            try:
                proc_name = self._normalize_process_name(str(proc.info.get("name") or ""))
            except Exception:
                continue

            if not proc_name:
                continue

            if proc_name == normalized_hint or proc_name.startswith(normalized_hint):
                return True

        return False

    @staticmethod
    def _normalize_process_name(value: str) -> str:
        name = str(value or "").strip().lower()
        if name.endswith(".exe"):
            name = name[:-4]
        return name

    def _within_screen(self, x: int, y: int) -> bool:
        if not _PYAUTOGUI:
            return False
        try:
            width, height = pyautogui.size()
            return 0 <= int(x) < int(width) and 0 <= int(y) < int(height)
        except Exception:
            return False

    @staticmethod
    def _normalize_browser(value: str) -> str:
        lowered = str(value or "").strip().lower()
        aliases = {
            "": "",
            "google chrome": "chrome",
            "chrome.exe": "chrome",
            "microsoft edge": "edge",
            "msedge": "edge",
            "edge.exe": "edge",
            "mozilla firefox": "firefox",
            "firefox.exe": "firefox",
        }
        normalized = aliases.get(lowered, lowered)
        if normalized in {"chrome", "edge", "firefox"}:
            return normalized
        if normalized:
            return normalized
        return ""

    def _is_safe_hotkey(self, keys: tuple[str, ...]) -> bool:
        normalized = tuple(str(key or "").strip().lower() for key in keys if str(key or "").strip())
        if not normalized:
            return False
        if self._safety_mode != "strict":
            return True
        return normalized not in self._policy.blocked_hotkeys

    def _is_safe_text(self, text: str) -> bool:
        payload = str(text or "")
        if len(payload) > int(self._policy.max_typed_chars):
            return False
        if self._safety_mode != "strict":
            return True
        lowered = payload.lower()
        return not any(re.search(pattern, lowered) for pattern in self._policy.blocked_type_patterns)

    @staticmethod
    def _parse_keys(raw: Any) -> tuple[str, ...]:
        if isinstance(raw, str):
            return tuple(part.strip().lower() for part in raw.split("+") if part.strip())
        if isinstance(raw, list):
            return tuple(str(part).strip().lower() for part in raw if str(part).strip())
        return ()

    @staticmethod
    def _maybe_int(value: Any) -> int | None:
        try:
            return int(value)
        except Exception:
            return None

    @staticmethod
    def _maybe_float(value: Any, *, fallback: float) -> float:
        try:
            return float(value)
        except Exception:
            return float(fallback)

    @staticmethod
    def _clamp_int(value: Any, min_value: int, max_value: int) -> int:
        try:
            parsed = int(value)
        except Exception:
            parsed = min_value
        return max(min_value, min(max_value, parsed))

    @staticmethod
    def _load_user_profile() -> dict[str, str]:
        memory_path = Path("data") / "user_memory.json"
        try:
            if memory_path.exists():
                data = json.loads(memory_path.read_text(encoding="utf-8"))
                return {
                    "name": str(data.get("name") or ""),
                    "age": str(data.get("age") or ""),
                    "city": str(data.get("last_city") or ""),
                    "email": str(data.get("email") or ""),
                }
        except Exception:
            pass
        return {}

    @staticmethod
    def _generate_random_data(data_type: str) -> str:
        dt = str(data_type or "").lower().strip()
        if dt == "first_name":
            return random.choice(_FIRST_NAMES)
        if dt == "last_name":
            return random.choice(_LAST_NAMES)
        if dt == "name":
            return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"
        if dt == "email":
            first = random.choice(_FIRST_NAMES).lower()
            last = random.choice(_LAST_NAMES).lower()
            num = random.randint(10, 999)
            return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"
        if dt == "username":
            first = random.choice(_FIRST_NAMES).lower()
            num = random.randint(100, 9999)
            return f"{first}{num}"
        if dt == "password":
            chars = string.ascii_letters + string.digits + "!@#$%"
            raw = (
                random.choice(string.ascii_uppercase)
                + random.choice(string.digits)
                + random.choice("!@#$%")
                + "".join(random.choices(chars, k=9))
            )
            return "".join(random.sample(raw, len(raw)))
        if dt == "phone":
            return f"+1{random.randint(200, 999)}{random.randint(1000000, 9999999)}"
        if dt == "birthday":
            year = random.randint(1980, 2000)
            month = random.randint(1, 12)
            day = random.randint(1, 28)
            return f"{month:02d}/{day:02d}/{year}"
        if dt == "address":
            num = random.randint(100, 9999)
            street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
            return f"{num} {street}"
        if dt == "zip_code":
            return str(random.randint(10000, 99999))
        if dt == "city":
            return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])
        return f"random_{dt}_{random.randint(1000, 9999)}"

    def _ok(self, action: str, message: str, *, verified: bool, state: dict[str, Any] | None = None) -> ActionResult:
        ar = ActionResult(
            status="success",
            action=str(action or "unknown").strip().lower(),
            success=True,
            verified=bool(verified),
            message=str(message or "Action completed."),
            error="",
            state=state or {},
        )
        try:
            # Attempt to audit every successful action
            self._audit(ar)
        except Exception:
            try:
                # best-effort logging
                logging.getLogger("jarvis.computer_control").debug("Audit write failed for ok: %s", ar)
            except Exception:
                pass
        return ar

    def _err(self, action: str, error: str, message: str, *, state: dict[str, Any] | None = None) -> ActionResult:
        ar = ActionResult(
            status="error",
            action=str(action or "unknown").strip().lower(),
            success=False,
            verified=False,
            message=str(message or "Action failed."),
            error=str(error or "execution_failed"),
            state=state or {},
        )
        try:
            # Audit errors as well
            self._audit(ar)
        except Exception:
            try:
                logging.getLogger("jarvis.computer_control").debug("Audit write failed for err: %s", ar)
            except Exception:
                pass
        return ar

    def _audit(self, result: ActionResult, *, extra: dict[str, Any] | None = None) -> None:
        try:
            record = result.to_dict()
            record["timestamp"] = datetime.datetime.utcnow().isoformat() + "Z"
            if extra:
                record["meta"] = extra
            path = Path(self._audit_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            try:
                self._logger.debug("Failed to write audit: %s", exc)
            except Exception:
                pass

    def _success(self, action: str, message: str, *, verified: bool, state: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._ok(action, message, verified=verified, state=state).to_dict()

    def _error(
        self,
        action: str,
        error: str,
        message: str,
        *,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._err(action, error, message, state=state).to_dict()


def computer_control(
    parameters: dict[str, Any],
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> dict[str, Any]:
    config = AppConfig.from_env(".env")
    dry_run = bool((parameters or {}).get("dry_run", False))
    safety_mode = str((parameters or {}).get("safety_mode") or "strict").strip().lower() or "strict"

    controller = ComputerController(config, dry_run=dry_run, safety_mode=safety_mode)
    result = controller.handle(parameters or {})

    if player is not None and hasattr(player, "write_log"):
        try:
            action = str(result.get("action") or "unknown")
            status = str(result.get("status") or "")
            message = str(result.get("message") or "")
            player.write_log(f"[ComputerControl] {action} | {status} | {message}")
        except Exception:
            pass

    return result
