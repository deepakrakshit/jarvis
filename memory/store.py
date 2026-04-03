# ==============================================================================
# File: memory/store.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Persistent Memory Store — Thread-Safe JSON Key/Value Storage
#
#    - Thread-safe JSON file-backed key/value store (data/user_memory.json).
#    - Atomic writes via temp file + os.replace() for crash safety.
#    - Corruption recovery: renames corrupt files with .corrupt.{timestamp}.
#    - MemoryStore class: get(), set(), delete(), as_dict() operations.
#    - Reentrant lock (RLock) for nested lock acquisition safety.
#    - Auto-creates data/ directory if it does not exist.
#    - extract_user_name(): NLP regex extraction from 'my name is X' patterns.
#    - _normalize_name(): title-cases, trims stop words, limits to 4 parts.
#    - Used by runtime, weather service, and app control for state persistence.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any


_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmy name is\s+([a-zA-Z][a-zA-Z\s\-']{1,60})", re.IGNORECASE),
    re.compile(r"\bname is\s+([a-zA-Z][a-zA-Z\s\-']{1,60})", re.IGNORECASE),
    re.compile(r"\bcall me\s+([a-zA-Z][a-zA-Z\s\-']{1,60})", re.IGNORECASE),
)


def _normalize_name(candidate: str) -> str:
    cleaned = re.sub(r"\s+", " ", candidate.strip(" .,!?:;\"'"))
    for stop_word in (" and ", " but ", " because ", " so "):
        marker = cleaned.lower().find(stop_word)
        if marker > 0:
            cleaned = cleaned[:marker].strip()
            break

    parts = [part for part in cleaned.split(" ") if part]
    if not parts:
        return ""

    if len(parts) > 4:
        parts = parts[:4]

    normalized = " ".join(part[:1].upper() + part[1:] for part in parts)
    return normalized.strip()


def extract_user_name(text: str) -> str | None:
    source = (text or "").strip()
    if not source:
        return None

    for pattern in _NAME_PATTERNS:
        match = pattern.search(source)
        if not match:
            continue
        normalized = _normalize_name(match.group(1))
        if normalized:
            return normalized

    return None


class MemoryStore:
    """Thread-safe JSON-backed key/value memory for persistent user facts."""

    def __init__(self, file_path: str = "data/user_memory.json") -> None:
        self.file_path = file_path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not os.path.exists(self.file_path):
                self._data = {}
                return

            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except Exception:
                corrupt_path = f"{self.file_path}.corrupt.{int(time.time())}"
                try:
                    os.replace(self.file_path, corrupt_path)
                except Exception:
                    pass
                self._data = {}
                return

            if isinstance(payload, dict):
                self._data = payload
            else:
                self._data = {}

    def _persist(self) -> None:
        with self._lock:
            directory = os.path.dirname(self.file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)

            tmp_path = f"{self.file_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=True, sort_keys=True)
            os.replace(tmp_path, self.file_path)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
        self._persist()

    def delete(self, key: str) -> None:
        with self._lock:
            if key in self._data:
                del self._data[key]
            else:
                return
        self._persist()

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)
