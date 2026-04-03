# ==============================================================================
# File: utils/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Utilities Package Initializer
#
#    - Exports shared utility modules for the JARVIS system.
#    - TextCleaner: user input normalization and filler word removal.
#    - geocode_resolver: city name to coordinates resolution.
#    - Provides cross-cutting utilities used by multiple packages.
#    - No dependency on service or agent packages for clean layering.
#    - Lightweight modules with focused, single-purpose responsibilities.
#    - All utilities are stateless and thread-safe.
#    - Designed for reuse across different processing pipelines.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from utils.geocode_resolver import resolve_geocode
from utils.text_cleaner import CleanedText, TextCleaner

__all__ = ["TextCleaner", "CleanedText", "resolve_geocode"]
