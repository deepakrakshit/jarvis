from __future__ import annotations

import ctypes
from typing import Any

from services.system.window_control import WindowController


class DesktopController:
    _VK_LWIN = 0x5B
    _VK_D = 0x44
    _VK_M = 0x4D
    _VK_SHIFT = 0x10

    def __init__(self, window_controller: WindowController) -> None:
        self._window = window_controller

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        normalized = str(action or "").strip().lower()
        if normalized == "minimize_all_windows":
            return self.minimize_all_windows()
        if normalized == "restore_all_windows":
            return self.restore_all_windows()
        if normalized == "show_desktop":
            return self.show_desktop()
        if normalized == "restore_specific":
            return self.restore_specific(str(params.get("app") or ""))
        return self._error(normalized, "unsupported_action")

    def minimize_all_windows(self) -> dict[str, Any]:
        self._win_m_shortcut(restore=False)
        return {
            "status": "success",
            "action": "minimize_all_windows",
            "success": True,
            "verified": True,
            "error": "",
            "state": {},
            "message": "All windows minimized.",
        }

    def restore_all_windows(self) -> dict[str, Any]:
        self._win_m_shortcut(restore=True)
        return {
            "status": "success",
            "action": "restore_all_windows",
            "success": True,
            "verified": True,
            "error": "",
            "state": {},
            "message": "All windows restored.",
        }

    def show_desktop(self) -> dict[str, Any]:
        user32 = ctypes.windll.user32
        user32.keybd_event(self._VK_LWIN, 0, 0, 0)
        user32.keybd_event(self._VK_D, 0, 0, 0)
        user32.keybd_event(self._VK_D, 0, 2, 0)
        user32.keybd_event(self._VK_LWIN, 0, 2, 0)
        return {
            "status": "success",
            "action": "show_desktop",
            "success": True,
            "verified": True,
            "error": "",
            "state": {},
            "message": "Desktop shown.",
        }

    def restore_specific(self, app_name: str) -> dict[str, Any]:
        # Reuse window focus flow to restore and bring target to foreground.
        return self._window.focus_window(app_name)

    def _win_m_shortcut(self, *, restore: bool) -> None:
        user32 = ctypes.windll.user32
        user32.keybd_event(self._VK_LWIN, 0, 0, 0)
        if restore:
            user32.keybd_event(self._VK_SHIFT, 0, 0, 0)
        user32.keybd_event(self._VK_M, 0, 0, 0)
        user32.keybd_event(self._VK_M, 0, 2, 0)
        if restore:
            user32.keybd_event(self._VK_SHIFT, 0, 2, 0)
        user32.keybd_event(self._VK_LWIN, 0, 2, 0)

    @staticmethod
    def _error(action: str, error: str) -> dict[str, Any]:
        return {
            "status": "error",
            "action": action,
            "success": False,
            "verified": False,
            "error": error,
            "state": {},
            "message": "Unable to complete desktop action.",
        }
