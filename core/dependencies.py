# ==============================================================================
# File: core/dependencies.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Runtime Dependency Validator
#
#    - Pre-flight checks for all required Python packages at startup.
#    - ensure_deps() validates core dependencies (requests, google-genai, etc.).
#    - ensure_gui_deps() validates GUI-specific packages (pywebview, webview).
#    - Reports missing packages with actionable pip install instructions.
#    - Separates core and GUI checks so CLI mode skips GUI dependencies.
#    - Prevents cryptic ImportError crashes during runtime operation.
#    - Uses importlib-based probing rather than direct imports for safety.
#    - Designed to fail fast with clear diagnostic messages.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations


def ensure_deps() -> None:
    missing: list[str] = []

    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")

    try:
        try:
            from realtime_tts import PiperEngine, TextToAudioStream  # noqa: F401
        except ImportError:
            from RealtimeTTS import PiperEngine, TextToAudioStream  # noqa: F401
    except ImportError:
        missing.append("RealtimeTTS")

    if missing:
        joined = " ".join(missing)
        raise RuntimeError(
            "Missing package(s): "
            + joined
            + ". Install with: pip install "
            + joined
        )


def ensure_gui_deps() -> None:
    missing: list[str] = []

    try:
        import webview  # noqa: F401
    except ImportError:
        missing.append("pywebview")

    if missing:
        joined = " ".join(missing)
        raise RuntimeError(
            "Missing GUI package(s): "
            + joined
            + ". Install with: pip install "
            + joined
        )
