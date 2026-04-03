# ==============================================================================
# File: core/llm_api.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Gemini LLM API Client with Retry & Fallback Chain
#
#    - Provider-agnostic inference gateway for all LLM calls in the system.
#    - chat_complete() function with configurable model, temperature, and tokens.
#    - Automatic retry logic: up to 2 retries with 0.6s delay for 429/5xx errors.
#    - Multi-model fallback: gemini-2.5-flash -> 2.0-flash -> 2.0-flash-lite.
#    - Structured JSON output mode via response_format_json parameter.
#    - Timeout enforcement to prevent hanging requests from blocking the system.
#    - Constructs Gemini API payloads with proper role mapping and safety settings.
#    - Used by the planner, synthesizer, personality engine, and search reformulator.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import time
from typing import Any

import requests

from core.settings import AppConfig

_GEMINI_CHAT_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS_PER_MODEL = 2
_FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-3.1-flash-lite-preview")


def _gemini_extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(candidates, list) or not candidates:
        return ""

    first = candidates[0] if isinstance(candidates[0], dict) else {}
    content = first.get("content") if isinstance(first, dict) else {}
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return ""

    chunks: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = str(part.get("text") or "").strip()
        if text:
            chunks.append(text)

    return "\n".join(chunks).strip()


def _to_gemini_payload(
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int | None,
    response_format_json: bool,
) -> dict[str, Any]:
    system_lines: list[str] = []
    contents: list[dict[str, Any]] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        role = str(msg.get("role") or "").strip().lower()
        text = str(msg.get("content") or "").strip()
        if not text:
            continue

        if role == "system":
            system_lines.append(text)
            continue

        mapped_role = "model" if role == "assistant" else "user"
        contents.append({"role": mapped_role, "parts": [{"text": text}]})

    if not contents:
        contents = [{"role": "user", "parts": [{"text": "Respond briefly."}]}]

    generation_config: dict[str, Any] = {
        "temperature": float(temperature),
    }
    if max_tokens is not None and int(max_tokens) > 0:
        generation_config["maxOutputTokens"] = int(max_tokens)
    if response_format_json:
        generation_config["responseMimeType"] = "application/json"

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": generation_config,
    }
    if system_lines:
        payload["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_lines)}]
        }

    return payload


def _candidate_models(config: AppConfig, model_override: str | None) -> list[str]:
    configured = str(model_override or config.gemini_model or "gemini-3.1-flash-lite-preview").strip()
    if not configured:
        configured = "gemini-3.1-flash-lite-preview"

    models = [configured]
    # Add fallback models that aren't duplicates of the primary.
    for fallback in _FALLBACK_MODELS:
        if fallback not in models:
            models.append(fallback)
    return models


def chat_complete(
    config: AppConfig,
    *,
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int | None = None,
    timeout: float = 35.0,
    response_format_json: bool = False,
    model_override: str | None = None,
) -> str:
    api_key = str(config.gemini_api_key or "").strip()
    if not api_key:
        return ""

    payload = _to_gemini_payload(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format_json=response_format_json,
    )
    last_error: Exception | None = None

    base_timeout = max(5.0, float(timeout))
    candidates = _candidate_models(config, model_override)

    for model_index, model in enumerate(candidates):
        attempt_count = _MAX_ATTEMPTS_PER_MODEL if model_index == 0 else 1
        for attempt in range(attempt_count):
            attempt_timeout = base_timeout if (model_index == 0 and attempt == 0) else min(base_timeout, 15.0)
            try:
                response = requests.post(
                    _GEMINI_CHAT_URL.format(model=model),
                    params={"key": api_key},
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=attempt_timeout,
                )
                response.raise_for_status()
                return _gemini_extract_text(response.json())
            except requests.exceptions.HTTPError as exc:
                last_error = exc
                status = getattr(exc.response, "status_code", None)
                if status in (400, 404):
                    break  # Model doesn't exist or bad request — try next model.
                if status == 429:
                    # Rate limited — back off more aggressively before trying again.
                    backoff = 1.0 * (attempt + 1)
                    if attempt < (attempt_count - 1):
                        time.sleep(backoff)
                        continue
                    break  # Try next model in fallback chain.
                if status in _RETRYABLE_HTTP_STATUS_CODES and attempt < (attempt_count - 1):
                    time.sleep(0.4 * (attempt + 1))
                    continue
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                if attempt < (attempt_count - 1):
                    time.sleep(0.5 * (attempt + 1))
                    continue
                break
            except Exception as exc:
                last_error = exc
                break

    if last_error is not None:
        raise last_error
    return ""
