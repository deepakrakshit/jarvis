from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class SystemControlConfig:
    safe_mode: bool = True
    max_actions_per_request: int = 3
    max_actions_per_minute: int = 30
    action_log_limit: int = 200


@dataclass(frozen=True)
class SystemValidationResult:
    valid: bool
    action: str
    params: dict[str, Any]
    error: str = ""
    blocked: bool = False


@dataclass(frozen=True)
class ActionLogEntry:
    action: str
    params: dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class SystemActionResult:
    status: str
    action: str
    success: bool
    verified: bool
    message: str
    error: str = ""
    state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "action": self.action,
            "success": self.success,
            "verified": self.verified,
            "message": self.message,
            "error": self.error,
            "state": dict(self.state),
        }
