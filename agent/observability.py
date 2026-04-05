# ==============================================================================
# File: agent/observability.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Lightweight Observability Event Recorder
#
#    - Structured event logging for autonomy decisions and tool execution.
#    - JSONL sink with thread-safe writes and best-effort failure handling.
#    - Event timestamps stored in UTC ISO-8601 format.
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
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ObservabilityEvent:
    """Structured observability event payload."""

    event_type: str
    payload: dict[str, Any]
    timestamp_utc: str


class ObservabilityRecorder:
    """Thread-safe JSONL observability sink with best-effort writes."""

    def __init__(self, *, file_path: str) -> None:
        self.file_path = str(file_path or "").strip()
        self._lock = threading.RLock()

    def record(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """Record one observability event to the configured JSONL sink."""
        normalized_type = str(event_type or "").strip()
        if not normalized_type or not self.file_path:
            return

        event = ObservabilityEvent(
            event_type=normalized_type,
            payload=payload if isinstance(payload, dict) else {},
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )
        row = {
            "timestamp_utc": event.timestamp_utc,
            "event_type": event.event_type,
            "payload": event.payload,
        }

        with self._lock:
            try:
                directory = os.path.dirname(self.file_path)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                with open(self.file_path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=True) + "\n")
            except Exception:
                # Observability must never break user-facing runtime execution.
                return