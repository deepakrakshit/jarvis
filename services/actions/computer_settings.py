# ==============================================================================
# File: services/actions/computer_settings.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Computer Settings Alias Module
#
#    - Thin alias layer for computer settings queries.
#    - Routes settings requests to SystemControlService for unified handling.
#    - Covers brightness, volume, and display configuration queries.
#    - Prevents code duplication between settings and system control paths.
#    - Maintains consistent response format across all system actions.
#    - Registered as 'computer_settings' tool in the agent tool registry.
#    - 35s timeout matching the system_control tool specification.
#    - Provides a semantic alias so the planner can choose the right tool.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

from typing import Any

from services.system.system_service import SystemControlService

_service = SystemControlService()


def computer_settings(
    parameters: dict[str, Any],
    response: Any = None,
    player: Any = None,
    session_memory: Any = None,
) -> dict[str, Any]:
    action = str((parameters or {}).get("action") or (parameters or {}).get("description") or "").strip().lower()
    if not action:
        return {
            "status": "error",
            "action": "",
            "success": False,
            "verified": False,
            "error": "missing_action",
            "message": "computer_settings requires an action or description.",
            "state": {},
        }

    params = (parameters or {}).get("params")
    safe_params = dict(params) if isinstance(params, dict) else {}
    for key in ("step", "level", "app", "app_name", "value", "key", "text", "actions_in_request"):
        if key in (parameters or {}) and key not in safe_params:
            safe_params[key] = (parameters or {}).get(key)

    if "level" not in safe_params and "value" in safe_params:
        try:
            safe_params["level"] = int(safe_params["value"])
        except Exception:
            pass

    if "step" not in safe_params and "value" in safe_params:
        try:
            safe_params["step"] = int(safe_params["value"])
        except Exception:
            pass

    return _service.control(action=action, params=safe_params)
