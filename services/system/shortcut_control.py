from __future__ import annotations

import ctypes
from typing import Any

try:
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.02
    _PYAUTOGUI = True
except Exception:  # pragma: no cover
    pyautogui = None  # type: ignore[assignment]
    _PYAUTOGUI = False


class ShortcutController:
    _WM_SYSCOMMAND = 0x0112
    _SC_MONITORPOWER = 0xF170
    _HWND_BROADCAST = 0xFFFF

    _MEDIA_VK: dict[str, int] = {
        "media_play_pause": 0xB3,
        "media_next_track": 0xB0,
        "media_previous_track": 0xB1,
        "media_stop": 0xB2,
    }

    _HOTKEY_ACTIONS: dict[str, tuple[str, ...]] = {
        "task_view": ("win", "tab"),
        "snap_window_left": ("win", "left"),
        "snap_window_right": ("win", "right"),
        "snap_window_up": ("win", "up"),
        "snap_window_down": ("win", "down"),
        "toggle_projection_mode": ("win", "p"),
        "new_tab": ("ctrl", "t"),
        "close_tab": ("ctrl", "w"),
        "reopen_closed_tab": ("ctrl", "shift", "t"),
        "next_tab": ("ctrl", "tab"),
        "previous_tab": ("ctrl", "shift", "tab"),
        "refresh_page": ("f5",),
        "hard_refresh": ("ctrl", "shift", "r"),
        "go_back": ("alt", "left"),
        "go_forward": ("alt", "right"),
        "open_history": ("ctrl", "h"),
        "open_downloads": ("ctrl", "j"),
        "copy": ("ctrl", "c"),
        "paste": ("ctrl", "v"),
        "cut": ("ctrl", "x"),
        "undo": ("ctrl", "z"),
        "redo": ("ctrl", "y"),
        "select_all": ("ctrl", "a"),
        "save": ("ctrl", "s"),
        "find": ("ctrl", "f"),
        "zoom_in": ("ctrl", "+"),
        "zoom_out": ("ctrl", "-"),
        "zoom_reset": ("ctrl", "0"),
    }

    _ACTION_MESSAGES: dict[str, str] = {
        "task_view": "Opened task view.",
        "snap_window_left": "Snapped window to the left.",
        "snap_window_right": "Snapped window to the right.",
        "snap_window_up": "Snapped window upward.",
        "snap_window_down": "Snapped window downward.",
        "toggle_projection_mode": "Opened display projection mode chooser.",
        "new_tab": "Opened a new tab.",
        "close_tab": "Closed the current tab.",
        "reopen_closed_tab": "Reopened the last closed tab.",
        "next_tab": "Moved to the next tab.",
        "previous_tab": "Moved to the previous tab.",
        "refresh_page": "Refreshed the current page.",
        "hard_refresh": "Performed a hard refresh.",
        "go_back": "Navigated back.",
        "go_forward": "Navigated forward.",
        "open_history": "Opened browser history.",
        "open_downloads": "Opened browser downloads.",
        "copy": "Sent copy shortcut.",
        "paste": "Sent paste shortcut.",
        "cut": "Sent cut shortcut.",
        "undo": "Sent undo shortcut.",
        "redo": "Sent redo shortcut.",
        "select_all": "Selected all content.",
        "save": "Sent save shortcut.",
        "find": "Sent find shortcut.",
        "zoom_in": "Sent zoom-in shortcut.",
        "zoom_out": "Sent zoom-out shortcut.",
        "zoom_reset": "Reset zoom to default.",
        "display_off": "Sent display-off command.",
        "display_on": "Sent display wake signal.",
        "media_play_pause": "Toggled media play/pause.",
        "media_next_track": "Skipped to next media track.",
        "media_previous_track": "Returned to previous media track.",
        "media_stop": "Stopped media playback.",
    }

    _VK_CODES: dict[str, int] = {
        "backspace": 0x08,
        "tab": 0x09,
        "enter": 0x0D,
        "return": 0x0D,
        "shift": 0x10,
        "ctrl": 0x11,
        "control": 0x11,
        "alt": 0x12,
        "pause": 0x13,
        "esc": 0x1B,
        "escape": 0x1B,
        "space": 0x20,
        "pageup": 0x21,
        "pagedown": 0x22,
        "end": 0x23,
        "home": 0x24,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
        "insert": 0x2D,
        "delete": 0x2E,
        "0": 0x30,
        "1": 0x31,
        "2": 0x32,
        "3": 0x33,
        "4": 0x34,
        "5": 0x35,
        "6": 0x36,
        "7": 0x37,
        "8": 0x38,
        "9": 0x39,
        "a": 0x41,
        "b": 0x42,
        "c": 0x43,
        "d": 0x44,
        "e": 0x45,
        "f": 0x46,
        "g": 0x47,
        "h": 0x48,
        "i": 0x49,
        "j": 0x4A,
        "k": 0x4B,
        "l": 0x4C,
        "m": 0x4D,
        "n": 0x4E,
        "o": 0x4F,
        "p": 0x50,
        "q": 0x51,
        "r": 0x52,
        "s": 0x53,
        "t": 0x54,
        "u": 0x55,
        "v": 0x56,
        "w": 0x57,
        "x": 0x58,
        "y": 0x59,
        "z": 0x5A,
        "win": 0x5B,
        "lwin": 0x5B,
        "rwin": 0x5C,
        "f1": 0x70,
        "f2": 0x71,
        "f3": 0x72,
        "f4": 0x73,
        "f5": 0x74,
        "f6": 0x75,
        "f7": 0x76,
        "f8": 0x77,
        "f9": 0x78,
        "f10": 0x79,
        "f11": 0x7A,
        "f12": 0x7B,
        "+": 0xBB,
        "=": 0xBB,
        "-": 0xBD,
    }

    def execute(self, action: str, _params: dict[str, Any]) -> dict[str, Any]:
        normalized = str(action or "").strip().lower()

        if normalized in self._MEDIA_VK:
            return self._press_virtual_key_action(normalized, self._MEDIA_VK[normalized])

        if normalized == "display_off":
            return self._display_off()

        if normalized == "display_on":
            # Any user input wakes most displays. Shift is low-risk and unobtrusive.
            return self._press_virtual_key_action(normalized, self._VK_CODES["shift"])

        keys = self._HOTKEY_ACTIONS.get(normalized)
        if keys:
            return self._run_hotkey_action(normalized, keys)

        return self._error(normalized, "unsupported_action")

    def _run_hotkey_action(self, action: str, keys: tuple[str, ...]) -> dict[str, Any]:
        ok, method = self._send_hotkey(keys)
        if not ok:
            return self._error(action, "execution_failed")

        return {
            "status": "success",
            "action": action,
            "success": True,
            "verified": False,
            "error": "",
            "state": {
                "method": method,
                "keys": list(keys),
            },
            "message": self._ACTION_MESSAGES.get(action, "Shortcut command sent."),
        }

    def _press_virtual_key_action(self, action: str, vk_code: int) -> dict[str, Any]:
        if not self._press_virtual_key(vk_code):
            return self._error(action, "execution_failed")
        return {
            "status": "success",
            "action": action,
            "success": True,
            "verified": False,
            "error": "",
            "state": {
                "method": "ctypes_key_event",
                "vk_code": int(vk_code),
            },
            "message": self._ACTION_MESSAGES.get(action, "Media key command sent."),
        }

    def _display_off(self) -> dict[str, Any]:
        try:
            user32 = ctypes.windll.user32
            user32.SendMessageW(self._HWND_BROADCAST, self._WM_SYSCOMMAND, self._SC_MONITORPOWER, 2)
        except Exception:
            return self._error("display_off", "execution_failed")

        return {
            "status": "success",
            "action": "display_off",
            "success": True,
            "verified": False,
            "error": "",
            "state": {"method": "sendmessage_monitor_power"},
            "message": self._ACTION_MESSAGES.get("display_off", "Sent display-off command."),
        }

    def _send_hotkey(self, keys: tuple[str, ...]) -> tuple[bool, str]:
        if _PYAUTOGUI and pyautogui is not None:
            try:
                if len(keys) == 1:
                    pyautogui.press(keys[0])
                else:
                    pyautogui.hotkey(*keys)
                return True, "pyautogui"
            except Exception:
                pass

        if self._send_hotkey_ctypes(keys):
            return True, "ctypes_key_event"

        return False, ""

    def _send_hotkey_ctypes(self, keys: tuple[str, ...]) -> bool:
        vk_codes: list[int] = []
        for token in keys:
            vk = self._vk_for_token(token)
            if vk is None:
                return False
            vk_codes.append(vk)

        user32 = ctypes.windll.user32
        try:
            for vk in vk_codes:
                user32.keybd_event(vk, 0, 0, 0)
            for vk in reversed(vk_codes):
                user32.keybd_event(vk, 0, 2, 0)
            return True
        except Exception:
            return False

    @staticmethod
    def _vk_for_token(token: str) -> int | None:
        normalized = str(token or "").strip().lower()
        if not normalized:
            return None

        if normalized in ShortcutController._VK_CODES:
            return ShortcutController._VK_CODES[normalized]

        if len(normalized) == 1 and normalized.isalnum():
            return ord(normalized.upper())

        return None

    @staticmethod
    def _press_virtual_key(vk_code: int) -> bool:
        try:
            user32 = ctypes.windll.user32
            user32.keybd_event(vk_code, 0, 0, 0)
            user32.keybd_event(vk_code, 0, 2, 0)
            return True
        except Exception:
            return False

    @staticmethod
    def _error(action: str, error: str) -> dict[str, Any]:
        return {
            "status": "error",
            "action": str(action or "").strip().lower() or "unknown",
            "success": False,
            "verified": False,
            "error": error,
            "state": {},
            "message": "Unable to complete shortcut action.",
        }