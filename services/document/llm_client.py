"""Lightweight Groq API client for document processing LLM calls.

Provides retry logic, timeout handling, and structured JSON extraction.
Used by the cleaner, chunk processor, and final intelligence stages.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

_DEFAULT_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_MAX_RETRIES = 2
_RETRY_BACKOFF_BASE = 1.5


class DocumentLLMClient:
    """Reusable LLM client for document pipeline stages."""

    def __init__(
        self,
        *,
        api_key: str,
        fast_model: str = "llama-3.1-8b-instant",
        deep_model: str = "llama-3.3-70b-versatile",
        api_url: str = _DEFAULT_GROQ_URL,
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._fast_model = fast_model
        self._deep_model = deep_model
        self._api_url = api_url
        self._timeout = timeout
        self._thread_local = threading.local()

        if not self._api_key:
            logger.warning("DocumentLLMClient initialized without an API key")

    def _get_session(self) -> requests.Session:
        """Get a thread-local requests session with keep-alive connection pooling."""
        session = getattr(self._thread_local, "session", None)
        if session is not None:
            return session

        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=16)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        self._thread_local.session = session
        return session

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
        if not self._api_key:
            logger.error("Cannot make LLM request: API key is missing")
            return ""

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._get_session().post(
                    self._api_url,
                    headers=headers,
                    json=payload,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                data = response.json()

                choices = data.get("choices")
                if isinstance(choices, list) and choices:
                    message = choices[0].get("message", {})
                    content = str(message.get("content") or "").strip()
                    if content:
                        return content

                logger.warning("LLM returned empty content on attempt %d", attempt + 1)
                return ""

            except requests.exceptions.HTTPError as exc:
                last_error = exc
                status = getattr(exc.response, "status_code", 0)
                if status == 429:
                    wait = _RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning("Rate limited (429), retrying in %.1fs", wait)
                    time.sleep(wait)
                    continue
                if status >= 500:
                    wait = _RETRY_BACKOFF_BASE ** attempt
                    logger.warning("Server error (%d), retrying in %.1fs", status, wait)
                    time.sleep(wait)
                    continue
                logger.error("HTTP error %d from LLM API: %s", status, exc)
                break

            except requests.exceptions.Timeout:
                last_error = TimeoutError(f"LLM request timed out after {self._timeout}s")
                logger.warning("LLM request timed out on attempt %d", attempt + 1)
                continue

            except Exception as exc:
                last_error = exc
                logger.error("Unexpected error calling LLM API: %s", exc)
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
        """Use the fast model (llama-3.1-8b) for cleaning and chunk processing."""
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
        """Use the deep model (llama-3.3-70b) for final intelligence."""
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

        # Try direct parse first
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code fences
        import re

        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if fence_match:
            try:
                return json.loads(fence_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try finding first { or [ and matching to last } or ]
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
