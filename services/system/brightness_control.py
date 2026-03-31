from __future__ import annotations

from typing import Any

try:
    import screen_brightness_control as sbc  # type: ignore
except Exception:  # pragma: no cover
    sbc = None  # type: ignore[assignment]


class BrightnessController:
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
        try:
            sbc.set_brightness(target)
            final_level = self._current_level()
            if final_level is None:
                return self._error(action_override, "verification_failed")
            verified = int(final_level) == target
            return {
                "status": "success" if verified else "error",
                "action": action_override,
                "success": bool(verified),
                "verified": bool(verified),
                "error": "" if verified else "verification_failed",
                "state": {
                    "brightness": int(final_level),
                    "requested_brightness": int(target),
                },
                "message": (
                    f"Brightness set to {int(final_level)}%."
                    if verified
                    else f"Brightness remained at {int(final_level)}% instead of requested {int(target)}%."
                ),
            }
        except Exception:
            return self._error(action_override, "execution_failed")

    @staticmethod
    def _current_level() -> int | None:
        if sbc is None:
            return None
        try:
            levels = sbc.get_brightness()
            if isinstance(levels, list) and levels:
                return int(levels[0])
            if isinstance(levels, int):
                return int(levels)
        except Exception:
            return None
        return None

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
