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
