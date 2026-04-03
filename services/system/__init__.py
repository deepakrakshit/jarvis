# ==============================================================================
# File: services/system/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    System Control Package Initializer
#
#    - Exports system control components for OS-level interaction.
#    - SystemControlService: unified facade for 40+ system actions.
#    - AppControlService: application open/close with process verification.
#    - VolumeController, BrightnessController: hardware-level adjustments.
#    - WindowController, DesktopController: window management operations.
#    - ShortcutController: keyboard shortcut simulation via pyautogui.
#    - SystemControlValidator: NLP action normalization and safety policies.
#    - All controllers follow a consistent execute(action, params) interface.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

from services.system.app_control import AppControlService, AppExecutor, AppResolver
from services.system.system_service import SystemControlService

__all__ = [
	"AppControlService",
	"AppExecutor",
	"AppResolver",
	"SystemControlService",
]
