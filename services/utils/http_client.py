# ==============================================================================
# File: services/utils/http_client.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    HTTP Client Wrapper — Standardized External API Access
#
#    - Lightweight requests-based HTTP client for service API calls.
#    - Configurable default timeout for all requests.
#    - get_json(): JSON response parsing with error handling.
#    - get_text(): plain text response retrieval with encoding support.
#    - Supports custom parameters and headers per request.
#    - Standardized exception handling for network errors.
#    - Used by WeatherService, NetworkService, and geocode resolver.
#    - Returns None on error instead of raising for graceful degradation.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

from typing import Any

import requests


class HttpClient:
    """Small HTTP helper with safe fallbacks for external service calls."""

    def __init__(self, *, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "Jarvis-Assistant/1.0",
                "Accept": "application/json, application/rss+xml, application/xml, text/xml, text/plain, */*",
            }
        )

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        try:
            response = self._session.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout or self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except Exception:
            return None
        return None

    def get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str | None:
        try:
            response = self._session.get(
                url,
                params=params,
                headers=headers,
                timeout=timeout or self.timeout,
            )
            response.raise_for_status()
            return response.text
        except Exception:
            return None
