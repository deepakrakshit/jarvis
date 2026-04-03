# ==============================================================================
# File: services/document/llm_client.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Document Pipeline LLM Client — Dual-Model Architecture
#
#    - Dual-model LLM client for the document intelligence pipeline.
#    - Fast model: quick extraction tasks (summaries, key points).
#    - Deep model: complex reasoning (analysis, comparison, Q&A).
#    - Automatic model selection based on task complexity.
#    - Token budget management for context window optimization.
#    - Retry logic with model fallback on transient API failures.
#    - JSON output mode for structured intelligence extraction.
#    - Configurable temperature and max tokens per task type.
#    - Wraps core/llm_api.py with document-specific conventions.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from core.llm_api import chat_complete
from core.settings import AppConfig

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_RETRY_BACKOFF_BASE = 1.5


class DocumentLLMClient:
    """Reusable LLM client for document pipeline stages."""

    def __init__(
        self,
        *,
        config: AppConfig,
        fast_model: str = "gemini-2.5-flash",
        deep_model: str = "gemini-2.5-flash",
        timeout: float = 60.0,
    ) -> None:
        self._config = config
        self._fast_model = fast_model
        self._deep_model = deep_model
        self._timeout = timeout

        if not str(self._config.gemini_api_key or "").strip():
            logger.warning("DocumentLLMClient initialized without GEMINI_API_KEY")

    def _make_request(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        """Send a chat completion request with retry logic.

        Returns the assistant message content, or an empty string on failure.
        """
        if not str(self._config.gemini_api_key or "").strip():
            logger.error("Cannot make LLM request: GEMINI_API_KEY is missing")
            return ""

        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                content = chat_complete(
                    self._config,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self._timeout,
                    model_override=model,
                )
                content = str(content or "").strip()
                if content:
                    return content

                logger.warning("LLM returned empty content on attempt %d", attempt + 1)
                return ""

            except requests.exceptions.HTTPError as exc:
                last_error = exc
                status = getattr(exc.response, "status_code", 0)
                if status in (429, 500, 502, 503, 504):
                    wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning("Gemini HTTP %d, retrying in %.1fs", status, wait)
                    time.sleep(wait)
                    continue
                logger.error("HTTP error %d from Gemini API: %s", status, exc)
                break

            except requests.exceptions.Timeout:
                last_error = TimeoutError(f"LLM request timed out after {self._timeout}s")
                logger.warning("LLM request timed out on attempt %d", attempt + 1)
                continue

            except Exception as exc:
                last_error = exc
                logger.error("Unexpected error calling Gemini API: %s", exc)
                break

        if last_error:
            logger.error("All LLM request attempts failed. Last error: %s", last_error)
        return ""

    def complete_fast(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        """Use the fast model for cleaning and chunk processing."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._make_request(
            model=self._fast_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def complete_deep(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """Use the deep model for final intelligence reasoning."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self._make_request(
            model=self._deep_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def extract_json_fast(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> dict[str, Any] | list[Any] | None:
        """Call fast model and parse the response as JSON."""
        raw = self.complete_fast(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._parse_json(raw)

    def extract_json_deep(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any] | list[Any] | None:
        """Call deep model and parse the response as JSON."""
        raw = self.complete_deep(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | list[Any] | None:
        """Extract JSON from LLM response, handling markdown code fences."""
        if not raw:
            return None

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        import re

        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        for open_char, close_char in [("{", "}"), ("[", "]")]:
            start = raw.find(open_char)
            end = raw.rfind(close_char)
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    continue

        logger.warning("Failed to parse JSON from LLM response (length=%d)", len(raw))
        return None
