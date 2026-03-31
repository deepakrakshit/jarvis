from __future__ import annotations

import ctypes
import shutil
import subprocess
from ctypes import POINTER, cast
from typing import Any

try:
    from comtypes import CLSCTX_ALL  # type: ignore
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
except Exception:  # pragma: no cover
    CLSCTX_ALL = None  # type: ignore[assignment]
    AudioUtilities = None  # type: ignore[assignment]
    IAudioEndpointVolume = None  # type: ignore[assignment]


class VolumeController:
    _VK_VOLUME_MUTE = 0xAD
    _VK_VOLUME_DOWN = 0xAE
    _VK_VOLUME_UP = 0xAF

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        normalized = str(action or "").strip().lower()
        if normalized == "increase_volume":
            return self._change_volume(step=int(params.get("step", 10)), increase=True)
        if normalized == "decrease_volume":
            return self._change_volume(step=int(params.get("step", 10)), increase=False)
        if normalized == "set_volume":
            return self._set_volume(level=int(params.get("level", 50)))
        if normalized == "mute":
            return self._set_mute(mute=True)
        if normalized == "unmute":
            return self._set_mute(mute=False)
        return self._error(normalized, "unsupported_action")

    def _change_volume(self, *, step: int, increase: bool) -> dict[str, Any]:
        endpoint = self._endpoint()
        if endpoint is not None:
            current = int(round(float(endpoint.GetMasterVolumeLevelScalar()) * 100.0))
            target = max(0, min(100, current + (step if increase else -step)))
            endpoint.SetMasterVolumeLevelScalar(target / 100.0, None)
            final_value = int(round(float(endpoint.GetMasterVolumeLevelScalar()) * 100.0))
            muted = bool(endpoint.GetMute())
            return self._success(
                "increase_volume" if increase else "decrease_volume",
                final_value,
                muted,
                verified=(final_value == target),
                method="pycaw",
            )

        return self._simulate_key_volume("increase_volume" if increase else "decrease_volume", step, increase=increase)

    def _set_volume(self, *, level: int) -> dict[str, Any]:
        endpoint = self._endpoint()
        target = max(0, min(100, int(level)))
        if endpoint is not None:
            endpoint.SetMasterVolumeLevelScalar(target / 100.0, None)
            final_value = int(round(float(endpoint.GetMasterVolumeLevelScalar()) * 100.0))
            muted = bool(endpoint.GetMute())
            return self._success("set_volume", final_value, muted, verified=(final_value == target), method="pycaw")

        nircmd = shutil.which("nircmd") or shutil.which("nircmd.exe")
        if nircmd:
            scalar = int((target / 100.0) * 65535)
            try:
                completed = subprocess.run([nircmd, "setsysvolume", str(scalar)], capture_output=True, text=True, timeout=2)
            except Exception:
                completed = None
            if completed is not None and int(completed.returncode) == 0:
                return self._success("set_volume", target, muted=False, verified=False, method="nircmd")

        return self._set_volume_via_keys(target)

    def _set_mute(self, *, mute: bool) -> dict[str, Any]:
        endpoint = self._endpoint()
        if endpoint is not None:
            endpoint.SetMute(1 if mute else 0, None)
            muted = bool(endpoint.GetMute())
            level = int(round(float(endpoint.GetMasterVolumeLevelScalar()) * 100.0))
            return self._success("mute" if mute else "unmute", level, muted, verified=(muted is mute), method="pycaw")

        self._key_press(self._VK_VOLUME_MUTE)
        return {
            "status": "success",
            "action": "mute" if mute else "unmute",
            "success": True,
            "verified": False,
            "error": "",
            "state": {"volume": None, "muted": None, "method": "ctypes_key_event"},
            "message": "Mute toggled via keyboard event.",
        }

    def _simulate_key_volume(self, action: str, step: int, *, increase: bool) -> dict[str, Any]:
        presses = max(1, min(20, int(round(step / 2))))
        key = self._VK_VOLUME_UP if increase else self._VK_VOLUME_DOWN
        for _ in range(presses):
            self._key_press(key)
        return {
            "status": "success",
            "action": action,
            "success": True,
            "verified": False,
            "error": "",
            "state": {"volume": None, "muted": None, "method": "ctypes_key_event"},
            "message": "Volume adjusted via keyboard events.",
        }

    def _set_volume_via_keys(self, target: int) -> dict[str, Any]:
        # Best-effort fallback: reset volume low, then raise toward target.
        for _ in range(50):
            self._key_press(self._VK_VOLUME_DOWN)

        up_presses = max(0, min(50, int(round(target / 2))))
        for _ in range(up_presses):
            self._key_press(self._VK_VOLUME_UP)

        return {
            "status": "success",
            "action": "set_volume",
            "success": True,
            "verified": False,
            "error": "",
            "state": {
                "volume": None,
                "requested_volume": int(target),
                "muted": None,
                "method": "ctypes_key_event",
            },
            "message": f"Volume adjusted toward {int(target)}% via keyboard events.",
        }

    @staticmethod
    def _key_press(vk_code: int) -> None:
        user32 = ctypes.windll.user32
        user32.keybd_event(vk_code, 0, 0, 0)
        user32.keybd_event(vk_code, 0, 2, 0)

    @staticmethod
    def _endpoint() -> Any | None:
        if AudioUtilities is None or IAudioEndpointVolume is None or CLSCTX_ALL is None:
            return None
        try:
            speakers = AudioUtilities.GetSpeakers()
            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return cast(interface, POINTER(IAudioEndpointVolume))
        except Exception:
            return None

    @staticmethod
    def _success(action: str, volume: int, muted: bool, *, verified: bool, method: str) -> dict[str, Any]:
        return {
            "status": "success",
            "action": action,
            "success": True,
            "verified": bool(verified),
            "error": "",
            "state": {"volume": int(volume), "muted": bool(muted), "method": method},
            "message": f"Volume is now {int(volume)}%.",
        }

    @staticmethod
    def _error(action: str, error: str) -> dict[str, Any]:
        return {
            "status": "error",
            "action": action,
            "success": False,
            "verified": False,
            "error": error,
            "state": {},
            "message": "Unable to change volume.",
        }
