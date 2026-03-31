from __future__ import annotations

import re
from typing import Any

from services.system.system_models import SystemControlConfig, SystemValidationResult


class SystemControlValidator:
    _SAFE_ACTIONS = {
        "increase_volume",
        "decrease_volume",
        "set_volume",
        "mute",
        "unmute",
        "increase_brightness",
        "decrease_brightness",
        "set_brightness",
        "switch_window",
        "minimize_window",
        "restore_window",
        "focus_window",
        "close_window",
        "minimize_all_windows",
        "restore_all_windows",
        "show_desktop",
        "restore_specific",
        "lock_screen",
    }
    _BLOCKED_ACTIONS = {
        "shutdown",
        "restart",
        "reboot",
        "delete_system_files",
        "format_disk",
        "run_command",
        "exec",
    }
    _ACTION_ALIASES = {
        "volume_up": "increase_volume",
        "volume_down": "decrease_volume",
        "set_brightness_level": "set_brightness",
        "brightness_up": "increase_brightness",
        "brightness_down": "decrease_brightness",
        "minimise_window": "minimize_window",
        "minimise_all_windows": "minimize_all_windows",
        "lock": "lock_screen",
        "lock_workstation": "lock_screen",
    }

    def __init__(self, config: SystemControlConfig) -> None:
        self._config = config

    def validate(self, action: str, params: dict[str, Any] | None) -> SystemValidationResult:
        raw_action = str(action or "")
        safe_params = dict(params or {})
        normalized_action = self._canonicalize_action(raw_action, safe_params)

        if not normalized_action:
            return SystemValidationResult(False, normalized_action, safe_params, error="missing_action")

        if normalized_action in self._BLOCKED_ACTIONS:
            return SystemValidationResult(False, normalized_action, safe_params, error="action_blocked", blocked=True)

        if normalized_action == "sleep":
            if self._config.safe_mode:
                return SystemValidationResult(False, normalized_action, safe_params, error="action_blocked_safe_mode", blocked=True)
            return SystemValidationResult(True, normalized_action, safe_params)

        if normalized_action not in self._SAFE_ACTIONS:
            return SystemValidationResult(False, normalized_action, safe_params, error="unsupported_action")

        if normalized_action in {"increase_volume", "decrease_volume", "increase_brightness", "decrease_brightness"}:
            safe_params["step"] = self._clamp_int(safe_params.get("step", 10), min_value=1, max_value=100)

        if normalized_action in {"set_volume", "set_brightness"}:
            safe_params["level"] = self._clamp_int(safe_params.get("level", 50), min_value=0, max_value=100)

        if normalized_action in {"focus_window", "close_window", "restore_specific"}:
            app_name = str(safe_params.get("app") or safe_params.get("app_name") or "").strip()
            if not self._is_valid_app_name(app_name):
                return SystemValidationResult(False, normalized_action, safe_params, error="invalid_app_name")
            safe_params["app"] = app_name

        return SystemValidationResult(True, normalized_action, safe_params)

    def _canonicalize_action(self, raw_action: str, params: dict[str, Any]) -> str:
        normalized = self._normalize_action_token(raw_action)
        if not normalized:
            return ""

        if normalized in self._SAFE_ACTIONS or normalized in self._BLOCKED_ACTIONS or normalized == "sleep":
            return normalized

        alias = self._ACTION_ALIASES.get(normalized)
        if alias:
            return alias

        phrase = normalized.replace("_", " ").strip()

        if "brightness" in phrase:
            self._seed_numeric_params_from_phrase(params, phrase)
            if "level" not in params and self._is_max_level_request(phrase):
                params["level"] = 100
                return "set_brightness"
            if "level" not in params and self._is_min_level_request(phrase):
                params["level"] = 0
                return "set_brightness"
            if self._contains_any(phrase, {"increase", "raise", "up", "higher", "brighten"}):
                return "increase_brightness"
            if self._contains_any(phrase, {"decrease", "lower", "down", "reduce", "dim"}):
                return "decrease_brightness"
            if self._contains_any(phrase, {"set", "change", "adjust"}) or "level" in params:
                return "set_brightness"

        if "volume" in phrase or "sound" in phrase:
            self._seed_numeric_params_from_phrase(params, phrase)
            if "level" not in params and self._is_max_level_request(phrase):
                params["level"] = 100
                return "set_volume"
            if "level" not in params and self._is_min_level_request(phrase):
                params["level"] = 0
                return "set_volume"
            if "unmute" in phrase:
                return "unmute"
            if "mute" in phrase:
                return "mute"
            if self._contains_any(phrase, {"increase", "raise", "up", "louder"}):
                return "increase_volume"
            if self._contains_any(phrase, {"decrease", "lower", "down", "reduce", "quieter"}):
                return "decrease_volume"
            if self._contains_any(phrase, {"set", "change", "adjust"}) or "level" in params:
                return "set_volume"

        if self._contains_any(phrase, {"show desktop", "desktop"}) and "show" in phrase:
            return "show_desktop"

        if self._contains_any(phrase, {"minimize all", "minimize all windows", "minimise all", "minimise all windows"}):
            return "minimize_all_windows"

        if self._contains_any(phrase, {"restore all", "restore all windows"}):
            return "restore_all_windows"

        if self._contains_any(phrase, {"switch window", "next window", "change window", "alt tab"}):
            return "switch_window"

        if self._contains_any(phrase, {"minimize window", "minimise window", "minimize this window", "minimise this window"}):
            return "minimize_window"

        if self._contains_any(phrase, {"restore window", "restore this window"}):
            return "restore_window"

        if "focus" in phrase and "window" in phrase:
            inferred_app = self._extract_app_name(phrase, "focus")
            if inferred_app and "app" not in params and "app_name" not in params:
                params["app"] = inferred_app
            return "focus_window"

        if "close" in phrase and "window" in phrase:
            inferred_app = self._extract_app_name(phrase, "close")
            if inferred_app and "app" not in params and "app_name" not in params:
                params["app"] = inferred_app
            return "close_window"

        if self._contains_any(phrase, {"lock screen", "lock workstation"}) or phrase == "lock":
            return "lock_screen"

        if phrase == "sleep" or "sleep mode" in phrase:
            return "sleep"

        return normalized

    def _seed_numeric_params_from_phrase(self, params: dict[str, Any], phrase: str) -> None:
        if "level" not in params:
            level = self._extract_last_int(phrase)
            if level is not None:
                params["level"] = level

        if "step" not in params:
            step = self._extract_step_int(phrase)
            if step is not None:
                params["step"] = step

    @staticmethod
    def _extract_last_int(phrase: str) -> int | None:
        matches = re.findall(r"\b(\d{1,3})\b", phrase)
        if not matches:
            return None
        try:
            return int(matches[-1])
        except Exception:
            return None

    @staticmethod
    def _extract_step_int(phrase: str) -> int | None:
        match = re.search(r"\b(?:by|step|steps?)\s*(\d{1,3})\b", phrase)
        if not match:
            return None
        try:
            return int(match.group(1))
        except Exception:
            return None

    @staticmethod
    def _extract_app_name(phrase: str, verb: str) -> str:
        patterns = (
            rf"\b{verb}\s+(?:the\s+)?(?:window\s+)?(?:for\s+|of\s+)?(.+)$",
            rf"\b{verb}\s+(.+)\s+window\b",
        )
        for pattern in patterns:
            match = re.search(pattern, phrase)
            if not match:
                continue
            candidate = str(match.group(1) or "").strip(" .,!?;:_-")
            if candidate:
                return candidate
        return ""

    @staticmethod
    def _normalize_action_token(value: str) -> str:
        lowered = str(value or "").strip().lower()
        lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
        lowered = re.sub(r"_+", "_", lowered).strip("_")
        return lowered

    @staticmethod
    def _contains_any(text: str, candidates: set[str]) -> bool:
        return any(candidate in text for candidate in candidates)

    @staticmethod
    def _is_max_level_request(text: str) -> bool:
        return bool(re.search(r"\b(max|maximize|maximum|highest|full)\b", text))

    @staticmethod
    def _is_min_level_request(text: str) -> bool:
        return bool(re.search(r"\b(min|minimize|minimum|lowest)\b", text))

    @staticmethod
    def _clamp_int(value: Any, *, min_value: int, max_value: int) -> int:
        try:
            parsed = int(value)
        except Exception:
            parsed = min_value
        return max(min_value, min(max_value, parsed))

    @staticmethod
    def _is_valid_app_name(value: str) -> bool:
        cleaned = str(value or "").strip()
        if not cleaned:
            return False
        if len(cleaned) > 80:
            return False
        return bool(re.fullmatch(r"[a-zA-Z0-9 ._\-()]+", cleaned))
