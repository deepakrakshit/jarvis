# ==============================================================================
# File: services/actions/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Desktop Automation Package Initializer
#
#    - Exports computer control and screen processing capabilities.
#    - computer_control: autonomous browser and desktop automation.
#    - screen_processor: screen/camera capture with AI vision analysis.
#    - computer_settings: alias routing for system settings queries.
#    - Lazy-imported modules to minimize startup overhead (69KB + 35KB).
#    - Designed for heavyweight automation tasks with extended timeouts.
#    - Integrates with the agent tool registry as registered tools.
#    - Requires pyautogui and PIL for screen interaction capabilities.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

__all__ = [
    "computer_control",
    "computer_settings",
    "screen_processor",
]
