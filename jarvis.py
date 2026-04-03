# ==============================================================================
# File: jarvis.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Application Bootstrap & Virtual Environment Resolver
#
#    - Serves as the top-level entry point for the entire JARVIS application.
#    - Detects whether the current Python interpreter is the project's local
#      virtual environment and performs automatic re-execution if not.
#    - Uses os.execv for seamless process replacement without spawning
#      child processes, preserving the original CLI arguments.
#    - Sets the JARVIS_VENV_REEXECED environment flag to prevent infinite
#      re-execution loops across nested invocations.
#    - Supports both 'venv' and '.venv' directory conventions for maximum
#      compatibility with different project setup workflows.
#    - Resolves all paths using pathlib for cross-platform path safety.
#    - Delegates to app/main.py after environment validation is complete.
#    - Designed for zero-configuration startup — users simply run jarvis.py.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import os
import pathlib
import sys


def _maybe_reexec_into_project_venv() -> None:
    """Ensure JARVIS runs on the project's local virtual environment interpreter."""
    if os.getenv("JARVIS_VENV_REEXECED") == "1":
        return

    project_root = pathlib.Path(__file__).resolve().parent
    candidates = (
        project_root / "venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "Scripts" / "python.exe",
    )
    target = next((path for path in candidates if path.is_file()), None)
    if target is None:
        return

    current = pathlib.Path(sys.executable).resolve()
    target_resolved = target.resolve()
    if current == target_resolved:
        return

    os.environ["JARVIS_VENV_REEXECED"] = "1"
    script = project_root / "jarvis.py"
    os.execv(str(target_resolved), [str(target_resolved), str(script), *sys.argv[1:]])


_maybe_reexec_into_project_venv()

from app.main import main
from core.runtime import JarvisRuntime
from core.settings import AppConfig

__all__ = ["main", "JarvisRuntime", "AppConfig"]


if __name__ == "__main__":
    main()
