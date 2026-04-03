from __future__ import annotations

import logging
import threading
import time
import warnings
from typing import Any

try:
    import screen_brightness_control as sbc  # type: ignore

    # The upstream library can emit noisy, non-actionable monitor EDID warnings.
    warnings.filterwarnings(
        "ignore",
        message=r".*EDID.*",
        module=r"screen_brightness_control(\..*)?",
    )
    logging.getLogger("screen_brightness_control").setLevel(logging.ERROR)
    logging.getLogger("screen_brightness_control.windows").setLevel(logging.ERROR)
except Exception:  # pragma: no cover
    sbc = None  # type: ignore[assignment]


class BrightnessController:
    _CALL_TIMEOUT_SECONDS = 2.5
    _VERIFY_TOLERANCE = 2

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        normalized = str(action or "").strip().lower()
        if normalized == "increase_brightness":
            return self._change(step=int(params.get("step", 10)), increase=True)
        if normalized == "decrease_brightness":
            return self._change(step=int(params.get("step", 10)), increase=False)
        if normalized == "set_brightness":
            return self._set(level=int(params.get("level", 50)))
        return self._error(normalized, "unsupported_action")

    def _change(self, *, step: int, increase: bool) -> dict[str, Any]:
        current = self._current_level()
        if current is None:
            return self._error("increase_brightness" if increase else "decrease_brightness", "dependency_unavailable")
        target = max(0, min(100, current + (step if increase else -step)))
        return self._set(level=target, action_override="increase_brightness" if increase else "decrease_brightness")

    def _set(self, *, level: int, action_override: str = "set_brightness") -> dict[str, Any]:
        if sbc is None:
            return self._error(action_override, "dependency_unavailable")
        target = max(0, min(100, int(level)))
        for _attempt in range(2):
            ok, timed_out = self._run_with_timeout(lambda: sbc.set_brightness(target), self._CALL_TIMEOUT_SECONDS)
            if not ok:
                return self._error(action_override, "operation_timeout" if timed_out else "execution_failed")

            final_level = self._current_level()
            if final_level is None:
                time.sleep(0.15)
                continue

            verified = abs(int(final_level) - int(target)) <= self._VERIFY_TOLERANCE
            if verified:
                return {
                    "status": "success",
                    "action": action_override,
                    "success": True,
                    "verified": True,
                    "error": "",
                    "state": {
                        "brightness": int(final_level),
                        "requested_brightness": int(target),
                    },
                    "message": f"Brightness set to {int(final_level)}%.",
                }

            time.sleep(0.15)

        final_level = self._current_level()
        if final_level is None:
            return self._error(action_override, "verification_failed")

        return {
            "status": "error",
            "action": action_override,
            "success": False,
            "verified": False,
            "error": "verification_failed",
            "state": {
                "brightness": int(final_level),
                "requested_brightness": int(target),
            },
            "message": f"Brightness remained at {int(final_level)}% instead of requested {int(target)}%.",
        }

    @staticmethod
    def _current_level() -> int | None:
        if sbc is None:
            return None
        box: dict[str, Any] = {}
        error_box: dict[str, bool] = {"timeout": False}

        def _read() -> None:
            try:
                box["value"] = sbc.get_brightness()
            except Exception:
                box["error"] = True

        thread = threading.Thread(target=_read, daemon=True)
        thread.start()
        thread.join(timeout=BrightnessController._CALL_TIMEOUT_SECONDS)
        if thread.is_alive():
            error_box["timeout"] = True

        if error_box["timeout"] or box.get("error"):
            return None

        levels = box.get("value")
        if isinstance(levels, list) and levels:
            try:
                return int(levels[0])
            except Exception:
                return None
        if isinstance(levels, int):
            return int(levels)
        return None

    @staticmethod
    def _run_with_timeout(callable_obj: Any, timeout_seconds: float) -> tuple[bool, bool]:
        state: dict[str, Any] = {}

        def _runner() -> None:
            try:
                callable_obj()
                state["ok"] = True
            except Exception:
                state["error"] = True

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join(timeout=max(0.1, float(timeout_seconds)))
        if thread.is_alive():
            return False, True
        if state.get("error"):
            return False, False
        return bool(state.get("ok")), False

    @staticmethod
    def _error(action: str, error: str) -> dict[str, Any]:
        return {
            "status": "error",
            "action": action,
            "success": False,
            "verified": False,
            "error": error,
            "state": {},
            "message": "Unable to change brightness.",
        }
