from __future__ import annotations

import datetime as _dt


MORNING_START_HOUR = 5
AFTERNOON_START_HOUR = 12
EVENING_START_HOUR = 17


def get_time_bucket(now: _dt.datetime | None = None) -> str:
    """Return a stable time-of-day bucket based on local time."""
    local_now = now or _dt.datetime.now()
    hour = local_now.hour

    if MORNING_START_HOUR <= hour < AFTERNOON_START_HOUR:
        return "morning"
    if AFTERNOON_START_HOUR <= hour < EVENING_START_HOUR:
        return "afternoon"
    return "evening"


def get_time_based_greeting(
    *,
    now: _dt.datetime | None = None,
    name: str | None = None,
) -> str:
    """Generate a time-aware greeting with optional name."""
    bucket = get_time_bucket(now)
    if name:
        return f"Good {bucket}, {name}."
    return f"Good {bucket}."
