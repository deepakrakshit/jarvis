from __future__ import annotations

import ctypes
import logging
import os
import time
from collections import deque
from typing import Any

from services.system.brightness_control import BrightnessController
from services.system.desktop_control import DesktopController
from services.system.system_models import ActionLogEntry, SystemControlConfig
from services.system.system_validator import SystemControlValidator
from services.system.volume_control import VolumeController
from services.system.window_control import WindowController

logger = logging.getLogger(__name__)


class SystemControlService:
    """Unified, deterministic system-control facade for assistant tooling."""

    def __init__(self, config: SystemControlConfig | None = None) -> None:
        safe_mode_env = str(os.getenv("SYSTEM_SAFE_MODE", "true")).strip().lower() in {"1", "true", "yes", "on"}
        cfg = config or SystemControlConfig(safe_mode=safe_mode_env)

        self._config = cfg
        self._validator = SystemControlValidator(cfg)
        self._window = WindowController()
        self._desktop = DesktopController(self._window)
        self._volume = VolumeController()
        self._brightness = BrightnessController()

        self._rate_timestamps: deque[float] = deque()
        self._action_logs: deque[ActionLogEntry] = deque(maxlen=max(20, cfg.action_log_limit))

        self._dispatcher: dict[str, Any] = {
            "increase_volume": self._volume.execute,
            "decrease_volume": self._volume.execute,
            "set_volume": self._volume.execute,
            "mute": self._volume.execute,
            "unmute": self._volume.execute,
            "increase_brightness": self._brightness.execute,
            "decrease_brightness": self._brightness.execute,
            "set_brightness": self._brightness.execute,
            "switch_window": self._window.execute,
            "minimize_window": self._window.execute,
            "restore_window": self._window.execute,
            "focus_window": self._window.execute,
            "close_window": self._window.execute,
            "minimize_all_windows": self._desktop.execute,
            "restore_all_windows": self._desktop.execute,
            "show_desktop": self._desktop.execute,
            "restore_specific": self._desktop.execute,
            "lock_screen": self._execute_system_action,
            "sleep": self._execute_system_action,
        }

    def control(self, *, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = dict(params or {})
        actions_in_request = int(request_params.get("actions_in_request") or 1)

        if actions_in_request > self._config.max_actions_per_request:
            return self._error(action, "too_many_actions_in_request", message="Too many system actions in one request.")

        if not self._consume_rate_limit():
            return self._error(action, "rate_limited", message="System control is temporarily rate limited.")

        validation = self._validator.validate(action, request_params)
        if not validation.valid:
            return self._error(
                validation.action,
                validation.error or "validation_failed",
                message="System action blocked by safety policy." if validation.blocked else "Invalid system action request.",
                blocked=validation.blocked,
            )

        normalized_action = validation.action
        normalized_params = dict(validation.params)
        self._log_action(normalized_action, normalized_params)

        handler = self._dispatcher.get(normalized_action)
        if handler is None:
            return self._error(normalized_action, "unsupported_action", message="Unsupported system action.")

        started = time.perf_counter()
        try:
            result = handler(normalized_action, normalized_params)
        except Exception as exc:
            logger.exception("System control execution failed for action=%s", normalized_action)
            return self._error(normalized_action, "execution_failed", message=str(exc))

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if isinstance(result, dict):
            result.setdefault("latency_ms", round(elapsed_ms, 2))
            result.setdefault("safe_mode", bool(self._config.safe_mode))
            result.setdefault("action_log_size", len(self._action_logs))
            return result

        return self._error(normalized_action, "execution_failed", message="Invalid execution result payload.")

    def get_action_logs(self) -> list[dict[str, Any]]:
        return [
            {
                "action": entry.action,
                "params": dict(entry.params),
                "timestamp": entry.timestamp,
            }
            for entry in self._action_logs
        ]

    def _execute_system_action(self, action: str, _params: dict[str, Any]) -> dict[str, Any]:
        normalized = str(action or "").strip().lower()

        if normalized == "lock_screen":
            try:
                ok = bool(ctypes.windll.user32.LockWorkStation())
            except Exception:
                ok = False
            return {
                "status": "success" if ok else "error",
                "action": "lock_screen",
                "success": ok,
                "verified": ok,
                "error": "" if ok else "execution_failed",
                "state": {},
                "message": "Screen locked." if ok else "Failed to lock screen.",
            }

        if normalized == "sleep":
            if self._config.safe_mode:
                return self._error("sleep", "action_blocked_safe_mode", message="Sleep is blocked in safe mode.", blocked=True)

            try:
                ok = bool(ctypes.windll.powrprof.SetSuspendState(False, True, False))
            except Exception:
                ok = False

            return {
                "status": "success" if ok else "error",
                "action": "sleep",
                "success": ok,
                "verified": ok,
                "error": "" if ok else "execution_failed",
                "state": {},
                "message": "System sleep requested." if ok else "Failed to request system sleep.",
            }

        return self._error(normalized, "unsupported_action", message="Unsupported system action.")

    def _consume_rate_limit(self) -> bool:
        now = time.time()
        while self._rate_timestamps and (now - self._rate_timestamps[0]) > 60.0:
            self._rate_timestamps.popleft()

        if len(self._rate_timestamps) >= max(1, self._config.max_actions_per_minute):
            return False

        self._rate_timestamps.append(now)
        return True

    def _log_action(self, action: str, params: dict[str, Any]) -> None:
        entry = ActionLogEntry(action=str(action), params=dict(params))
        self._action_logs.append(entry)
        logger.info("system_control action=%s params=%s", action, params)

    @staticmethod
    def _error(action: str, error: str, *, message: str, blocked: bool = False) -> dict[str, Any]:
        return {
            "status": "blocked" if blocked else "error",
            "action": str(action or "").strip().lower() or "unknown",
            "success": False,
            "verified": False,
            "error": str(error or "execution_failed"),
            "state": {},
            "message": message,
        }
