# ==============================================================================
# File: services/system/window_control.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Window Management Controller — Win32 API
#
#    - Win32 API based window management for desktop automation.
#    - switch_window: Alt+Tab simulation for window cycling.
#    - minimize/maximize/restore: ShowWindow with SW_ flags.
#    - focus_window: SetForegroundWindow with foreground lock workaround.
#    - close_window: WM_CLOSE message dispatch for graceful shutdown.
#    - Foreground window detection via GetForegroundWindow.
#    - Process-aware window enumeration using EnumWindows callback.
#    - Returns structured result with success and window state metadata.
#    - Handles permission elevation requirements for protected windows.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import ctypes
from typing import Any

try:
    import pygetwindow as gw  # type: ignore
except Exception:  # pragma: no cover
    gw = None  # type: ignore[assignment]


class WindowController:
    _VK_MENU = 0x12
    _VK_TAB = 0x09

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        normalized = str(action or "").strip().lower()
        if normalized == "switch_window":
            return self.switch_window()
        if normalized == "minimize_window":
            return self.minimize_window()
        if normalized == "maximize_window":
            return self.maximize_window()
        if normalized == "restore_window":
            return self.restore_window()
        if normalized == "focus_window":
            return self.focus_window(str(params.get("app") or ""))
        if normalized == "close_window":
            return self.close_window(str(params.get("app") or ""))
        return self._error(normalized, "unsupported_action")

    def switch_window(self) -> dict[str, Any]:
        if gw is None:
            return self._error("switch_window", "dependency_unavailable")
        before = self._active_title()
        self._alt_tab_once()
        after = self._active_title()
        changed = bool(after and before != after)
        return {
            "status": "success" if changed else "error",
            "action": "switch_window",
            "success": changed,
            "verified": changed,
            "error": "" if changed else "execution_failed",
            "state": {"active_window": after},
            "message": "Switched active window." if changed else "Unable to switch active window.",
        }

    def minimize_window(self) -> dict[str, Any]:
        window = self._active_window()
        if window is None:
            return self._error("minimize_window", "window_not_found")
        try:
            window.minimize()
            return {
                "status": "success",
                "action": "minimize_window",
                "success": True,
                "verified": bool(getattr(window, "isMinimized", False)),
                "error": "",
                "state": {"title": str(getattr(window, "title", "") or "")},
                "message": "Window minimized.",
            }
        except Exception:
            return self._error("minimize_window", "execution_failed")

    def restore_window(self) -> dict[str, Any]:
        window = self._active_window()
        if window is None:
            return self._error("restore_window", "window_not_found")
        try:
            window.restore()
            return {
                "status": "success",
                "action": "restore_window",
                "success": True,
                "verified": not bool(getattr(window, "isMinimized", False)),
                "error": "",
                "state": {"title": str(getattr(window, "title", "") or "")},
                "message": "Window restored.",
            }
        except Exception:
            return self._error("restore_window", "execution_failed")

    def maximize_window(self) -> dict[str, Any]:
        window = self._active_window()
        if window is None:
            return self._error("maximize_window", "window_not_found")
        try:
            window.maximize()
            return {
                "status": "success",
                "action": "maximize_window",
                "success": True,
                "verified": bool(getattr(window, "isMaximized", False)),
                "error": "",
                "state": {"title": str(getattr(window, "title", "") or "")},
                "message": "Window maximized.",
            }
        except Exception:
            return self._error("maximize_window", "execution_failed")

    def focus_window(self, app_name: str) -> dict[str, Any]:
        target = self._find_window(app_name)
        if target is None:
            return self._error("focus_window", "window_not_found")
        try:
            if bool(getattr(target, "isMinimized", False)):
                target.restore()
            target.activate()
            active = self._active_title()
            matched = str(app_name or "").strip().lower() in str(active or "").lower()
            return {
                "status": "success" if matched else "error",
                "action": "focus_window",
                "success": matched,
                "verified": matched,
                "error": "" if matched else "verification_failed",
                "state": {"active_window": active},
                "message": "Window focused." if matched else "Could not verify focused window.",
            }
        except Exception:
            return self._error("focus_window", "execution_failed")

    def close_window(self, app_name: str) -> dict[str, Any]:
        target = self._find_window(app_name)
        if target is None:
            return self._error("close_window", "window_not_found")
        title = str(getattr(target, "title", "") or "")
        try:
            target.close()
        except Exception:
            return self._error("close_window", "execution_failed")

        still_exists = self._window_exists(title)
        return {
            "status": "success" if not still_exists else "error",
            "action": "close_window",
            "success": not still_exists,
            "verified": not still_exists,
            "error": "" if not still_exists else "verification_failed",
            "state": {"closed_window": title},
            "message": "Window closed." if not still_exists else "Could not verify window close.",
        }

    @staticmethod
    def _alt_tab_once() -> None:
        user32 = ctypes.windll.user32
        user32.keybd_event(WindowController._VK_MENU, 0, 0, 0)
        user32.keybd_event(WindowController._VK_TAB, 0, 0, 0)
        user32.keybd_event(WindowController._VK_TAB, 0, 2, 0)
        user32.keybd_event(WindowController._VK_MENU, 0, 2, 0)

    @staticmethod
    def _active_window() -> Any | None:
        if gw is None:
            return None
        try:
            return gw.getActiveWindow()
        except Exception:
            return None

    def _active_title(self) -> str:
        win = self._active_window()
        if win is None:
            return ""
        return str(getattr(win, "title", "") or "").strip()

    @staticmethod
    def _find_window(app_name: str) -> Any | None:
        if gw is None:
            return None
        token = str(app_name or "").strip().lower()
        if not token:
            return None
        try:
            for window in gw.getAllWindows():
                title = str(getattr(window, "title", "") or "").strip().lower()
                if token in title:
                    return window
        except Exception:
            return None
        return None

    @staticmethod
    def _window_exists(title: str) -> bool:
        if gw is None or not title:
            return False
        try:
            for window in gw.getAllWindows():
                if str(getattr(window, "title", "") or "").strip() == title:
                    return True
        except Exception:
            return False
        return False

    @staticmethod
    def _error(action: str, error: str) -> dict[str, Any]:
        return {
            "status": "error",
            "action": action,
            "success": False,
            "verified": False,
            "error": error,
            "state": {},
            "message": "Unable to complete window action.",
        }
