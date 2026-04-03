# ==============================================================================
# File: core/env.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Environment Configuration Loader
#
#    - Resolves .env file paths relative to the project root automatically.
#    - Uses python-dotenv for environment variable loading with overrides.
#    - Supports both absolute and relative .env file path specifications.
#    - Determines project root by traversing parent directories from __file__.
#    - Provides the foundation for all configuration across the system.
#    - Called early in the initialization chain before any service setup.
#    - Handles missing .env files gracefully without raising exceptions.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import os
from pathlib import Path


def _resolve_env_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_file():
        return candidate

    if candidate.is_absolute():
        return candidate

    # Resolve relative paths from the repository root so launches from other
    # working directories still locate .env reliably.
    project_root = Path(__file__).resolve().parents[1]
    root_relative = project_root / candidate
    if root_relative.is_file():
        return root_relative

    return candidate


def load_env_file(path: str = ".env") -> None:
    env_path = _resolve_env_path(path)
    if not env_path.exists():
        return

    with env_path.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            existing = os.getenv(key)
            if existing is None or not str(existing).strip():
                os.environ[key] = value
