# ==============================================================================
# File: services/document/vision.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    AI Vision Analysis Engine — Gemini Vision API Integration
#
#    - Gemini Vision API integration for visual document understanding.
#    - Page-level analysis: extracts content from complex multi-column layouts.
#    - Chart and diagram interpretation with structured data extraction.
#    - Handwritten text recognition via multi-modal LLM capabilities.
#    - Table detection and structured extraction from visual layouts.
#    - Image quality assessment and optimal resolution management.
#    - Dual-model support: fast model for quick scans, deep for complex pages.
#    - Rate limit handling with retry logic for API quota management.
#    - Returns structured analysis with extracted text, tables, and metadata.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import base64
import io
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from core.env import load_env_file
from services.document.vision_payload import (
    build_error_payload,
    clean_json_text,
    extract_message_content,
    has_payload_signal,
    merge_attempted_models,
    merge_notes,
    normalize_payload,
    normalize_str_list,
    parse_json_payload,
)

logger = logging.getLogger(__name__)

_DEFAULT_GEMINI_VISION_MODEL = "gemini-2.5-flash"

_VISION_PROMPT = """You are a document vision extractor.
Analyze the provided document image and return ONLY valid JSON with this exact schema:
{
  "visible_text": "...",
  "layout": "...",
  "categories": ["..."],
  "key_elements": ["..."],
  "tables": [{"title": "...", "headers": ["..."], "rows": [["..."]]}],
  "summary": "..."
}
Rules:
- Output MUST be valid JSON object.
- Do not wrap with markdown fences.
- Do not add commentary outside JSON.
- Keep arrays as arrays, even when empty.
"""


@dataclass(frozen=True)
class VisionConfig:
    api_key: str
    api_url: str = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    primary_model: str = _DEFAULT_GEMINI_VISION_MODEL
    fallback_models: tuple[str, ...] = ()
    timeout_seconds: float = 25.0
    max_retries_per_model: int = 0
    retry_backoff_seconds: float = 1.2
    fast_fail_on_429: bool = True
    min_retry_delay_seconds: float = 0.35
    max_retry_delay_seconds: float = 4.0


class VisionProcessor:
    """Gemini-backed vision processor with strict JSON extraction."""

    _SECOND_PASS_DELAY_SECONDS = 0.45
    _SECOND_PASS_MAX_IMAGE_BYTES = 2_400_000

    def __init__(self, config: VisionConfig) -> None:
        self._config = config
        self._thread_local = threading.local()
        self._runtime_api_key = str(config.api_key or "").strip()
        self._api_key_hydration_attempted = False
        self._api_key_lock = threading.Lock()
        self._model_chain = self._resolve_model_chain(config)

    def _get_session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is not None:
            return session

        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=8, pool_maxsize=16)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        self._thread_local.session = session
        return session

    def analyze_image_file(self, file_path: str, *, source: str = "") -> dict[str, Any]:
        """Analyze a local image file via vision model and return strict JSON."""
        path = Path(file_path)
        if not path.is_file():
            return self._error_payload(
                warning="Image file is not accessible for vision processing.",
                error=f"file_not_found:{file_path}",
                source=source or str(path),
            )

        suffix = path.suffix.lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(suffix, "image/png")

        try:
            image_bytes = path.read_bytes()
        except Exception as exc:
            return self._error_payload(
                warning="Unable to read image bytes for vision processing.",
                error=f"file_read_error:{exc}",
                source=source or str(path),
            )

        return self.analyze_image_bytes(image_bytes, mime_type=mime, source=source or path.name)

    def analyze_image_bytes(
        self,
        image_bytes: bytes,
        *,
        mime_type: str = "image/png",
        source: str = "image",
        allow_second_pass: bool = True,
    ) -> dict[str, Any]:
        """Analyze image bytes and return normalized strict JSON payload."""
        if not image_bytes:
            return self._error_payload(
                warning="No image content provided to vision processor.",
                error="empty_image_bytes",
                source=source,
            )

        api_key = self._resolve_api_key()
        if not api_key:
            return self._error_payload(
                warning="GEMINI_API_KEY is missing. Vision analysis skipped.",
                error="vision_api_key_missing",
                source=source,
            )

        encoded = self._to_base64(image_bytes)
        first_pass = self._run_with_fallback_models(
            encoded_image=encoded,
            mime_type=mime_type,
            source=source,
            api_key=api_key,
        )
        if self._has_payload_signal(first_pass):
            return first_pass

        if not allow_second_pass:
            return first_pass

        if not self._should_retry_second_pass(first_pass):
            return first_pass

        time.sleep(self._SECOND_PASS_DELAY_SECONDS)

        retry_bytes, retry_mime, retry_note = self._prepare_retry_image_bytes(
            image_bytes,
            mime_type,
        )
        second_pass = self._run_with_fallback_models(
            encoded_image=self._to_base64(retry_bytes),
            mime_type=retry_mime,
            source=source,
            api_key=api_key,
        )
        if retry_note:
            second_pass["warning"] = self._merge_notes(second_pass.get("warning"), retry_note)

        return self._resolve_retry_payload(first_pass, second_pass, source=source)

    def _resolve_api_key(self) -> str:
        if self._runtime_api_key:
            return self._runtime_api_key

        with self._api_key_lock:
            if self._runtime_api_key:
                return self._runtime_api_key

            if self._api_key_hydration_attempted:
                return ""

            self._api_key_hydration_attempted = True

            env_path = Path(__file__).resolve().parents[2] / ".env"
            load_env_file(str(env_path))

            hydrated = str(os.getenv("GEMINI_API_KEY") or "").strip()
            if hydrated:
                self._runtime_api_key = hydrated
            return self._runtime_api_key

    def analyze_images(
        self,
        images: list[dict[str, Any]],
        *,
        max_workers: int = 3,
        allow_second_pass: bool = False,
    ) -> list[dict[str, Any]]:
        """Analyze multiple images concurrently."""
        if not images:
            return []

        worker_count = max(1, min(max_workers, len(images)))
        outputs: list[dict[str, Any] | None] = [None] * len(images)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_idx = {
                executor.submit(self._analyze_single_item, item, allow_second_pass=allow_second_pass): idx
                for idx, item in enumerate(images)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    outputs[idx] = future.result()
                except Exception as exc:
                    logger.warning("Vision analysis failed for image index %d: %s", idx, exc)
                    outputs[idx] = self._error_payload(
                        warning="Vision analysis failed for one image.",
                        error=f"vision_processing_error:{exc}",
                        source=str(images[idx].get("source") or f"image_{idx + 1}"),
                    )

        return [item for item in outputs if item is not None]

    def _analyze_single_item(self, item: dict[str, Any], *, allow_second_pass: bool) -> dict[str, Any]:
        image_bytes = item.get("bytes")
        if not isinstance(image_bytes, (bytes, bytearray)):
            return self._error_payload(
                warning="Image payload is missing bytes for vision processing.",
                error="invalid_image_payload",
                source=str(item.get("source") or "unknown"),
            )

        return self.analyze_image_bytes(
            bytes(image_bytes),
            mime_type=str(item.get("mime_type") or "image/png"),
            source=str(item.get("source") or "image"),
            allow_second_pass=allow_second_pass,
        )

    @staticmethod
    def _normalize_model_id(model: str) -> str:
        candidate = str(model or "").strip()
        if not candidate:
            return ""

        if ":" in candidate:
            candidate = candidate.split(":", 1)[0].strip()

        return candidate

    def _resolve_model_chain(self, config: VisionConfig) -> list[str]:
        chain: list[str] = []

        raw_primary = str(config.primary_model or "").strip()
        normalized_primary = self._normalize_model_id(raw_primary)
        if not normalized_primary:
            normalized_primary = _DEFAULT_GEMINI_VISION_MODEL

        chain.append(normalized_primary)

        for item in config.fallback_models:
            raw = str(item or "").strip()
            if not raw:
                continue
            normalized = self._normalize_model_id(raw)
            if normalized and normalized not in chain:
                chain.append(normalized)

        return chain

    def _run_with_fallback_models(
        self,
        *,
        encoded_image: str,
        mime_type: str,
        source: str,
        api_key: str,
    ) -> dict[str, Any]:
        model_chain = list(self._model_chain)
        attempted_models: list[str] = []
        last_error = ""
        rate_limit_errors = 0
        total_attempts = 0

        for model in model_chain:
            attempted_models.append(model)
            for attempt in range(self._config.max_retries_per_model + 1):
                total_attempts += 1
                raw_text, status_code, error_text = self._call_model(
                    model=model,
                    encoded_image=encoded_image,
                    mime_type=mime_type,
                    api_key=api_key,
                )
                if raw_text:
                    payload = self._normalize_payload(self._parse_json_payload(raw_text))
                    payload["model"] = model
                    payload["source"] = source
                    payload["attempted_models"] = attempted_models
                    if error_text:
                        payload["warning"] = error_text
                    return payload

                last_error = error_text or last_error or "vision_upstream_failure"

                if status_code == 429:
                    rate_limit_errors += 1
                    if self._config.fast_fail_on_429:
                        time.sleep(self._config.min_retry_delay_seconds)
                        break

                if status_code in (408, 429, 500, 502, 503, 504):
                    wait_seconds = self._config.retry_backoff_seconds ** (attempt + 1)
                    wait_seconds = max(self._config.min_retry_delay_seconds, wait_seconds)
                    wait_seconds = min(wait_seconds, self._config.max_retry_delay_seconds)
                    time.sleep(wait_seconds)
                    continue

                break

        if rate_limit_errors and rate_limit_errors >= total_attempts:
            logger.warning(
                "Vision model chain exhausted due to rate limiting (429). models=%s",
                ",".join(attempted_models),
            )
            return self._error_payload(
                warning=(
                    "Vision API is rate-limited (HTTP 429). "
                    "Proceeding with OCR-focused fallback for speed."
                ),
                error="vision_http_429",
                source=source,
                attempted_models=attempted_models,
            )

        return self._error_payload(
            warning="Vision processing failed across all fallback models.",
            error=last_error or "vision_model_chain_failed",
            source=source,
            attempted_models=attempted_models,
        )

    def _call_model(
        self,
        *,
        model: str,
        encoded_image: str,
        mime_type: str,
        api_key: str,
    ) -> tuple[str, int, str]:
        strict_payload = self._build_payload(
            encoded_image=encoded_image,
            mime_type=mime_type,
            strict_json=True,
        )
        raw_text, status_code, error_text = self._post_for_content(
            model=model,
            api_key=api_key,
            payload=strict_payload,
        )
        if raw_text:
            return raw_text, status_code, error_text

        if status_code == 400:
            compat_payload = self._build_payload(
                encoded_image=encoded_image,
                mime_type=mime_type,
                strict_json=False,
            )
            compat_raw, compat_status, compat_error = self._post_for_content(
                model=model,
                api_key=api_key,
                payload=compat_payload,
            )
            if compat_raw:
                warning = "vision_compat_payload_recovered_after_http_400"
                return compat_raw, compat_status, warning
            return "", compat_status, compat_error or error_text or "vision_http_400"

        return "", status_code, error_text

    def _build_payload(self, *, encoded_image: str, mime_type: str, strict_json: bool) -> dict[str, Any]:
        instruction = "You are a strict JSON generator. " + _VISION_PROMPT
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": instruction},
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": encoded_image,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 900 if strict_json else 700,
            },
        }

        if strict_json:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        return payload

    def _post_for_content(self, *, model: str, api_key: str, payload: dict[str, Any]) -> tuple[str, int, str]:
        try:
            response = self._get_session().post(
                self._config.api_url.format(model=model),
                params={"key": api_key},
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=self._config.timeout_seconds,
            )
            status_code = int(response.status_code)
            if status_code >= 400:
                return "", status_code, f"vision_http_{status_code}"

            data = response.json()
            raw = self._extract_message_content(data)
            if not raw:
                return "", status_code, "vision_empty_response"
            return raw, status_code, ""
        except requests.exceptions.Timeout:
            return "", 408, "vision_timeout"
        except Exception as exc:
            return "", 500, f"vision_request_error:{exc}"

    @staticmethod
    def _has_payload_signal(payload: dict[str, Any]) -> bool:
        return has_payload_signal(payload)

    @staticmethod
    def _should_retry_second_pass(payload: dict[str, Any]) -> bool:
        if VisionProcessor._has_payload_signal(payload):
            return False

        error = str(payload.get("error") or "").strip().lower()
        if not error:
            return True

        if error in {"vision_api_key_missing", "empty_image_bytes"}:
            return False

        return error.startswith("vision_http_") or error.startswith("vision_")

    def _prepare_retry_image_bytes(self, image_bytes: bytes, mime_type: str) -> tuple[bytes, str, str]:
        if len(image_bytes) <= self._SECOND_PASS_MAX_IMAGE_BYTES:
            return image_bytes, mime_type, ""

        compacted = self._try_compact_image(image_bytes)
        if compacted is None:
            return image_bytes, mime_type, ""

        compact_bytes, compact_mime = compacted
        note = "vision_retry_used_compact_image_payload"
        return compact_bytes, compact_mime, note

    @staticmethod
    def _try_compact_image(image_bytes: bytes) -> tuple[bytes, str] | None:
        try:
            from PIL import Image
        except Exception:
            return None

        try:
            with Image.open(io.BytesIO(image_bytes)) as image:
                image = image.convert("RGB")
                width, height = image.size
                max_side = max(width, height)

                if max_side > 1600:
                    scale = 1600.0 / float(max_side)
                    resized_w = max(1, int(width * scale))
                    resized_h = max(1, int(height * scale))
                    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
                    image = image.resize((resized_w, resized_h), resampling)

                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=84, optimize=True)
                compact = buffer.getvalue()
                if compact and len(compact) < len(image_bytes):
                    return compact, "image/jpeg"
        except Exception:
            return None

        return None

    @staticmethod
    def _merge_notes(*parts: Any) -> str:
        return merge_notes(*parts)

    @staticmethod
    def _merge_attempted_models(*attempt_lists: Any) -> list[str]:
        return merge_attempted_models(*attempt_lists)

    def _resolve_retry_payload(
        self,
        first_pass: dict[str, Any],
        second_pass: dict[str, Any],
        *,
        source: str,
    ) -> dict[str, Any]:
        if self._has_payload_signal(second_pass):
            recovered = dict(second_pass)
            recovered["source"] = source
            recovered["warning"] = self._merge_notes(
                second_pass.get("warning"),
                "vision_second_pass_recovered",
            )
            recovered["attempted_models"] = self._merge_attempted_models(
                first_pass.get("attempted_models"),
                second_pass.get("attempted_models"),
            )
            return recovered

        if self._has_payload_signal(first_pass):
            return first_pass

        merged = dict(second_pass if isinstance(second_pass, dict) else first_pass)
        merged["source"] = source
        merged["attempted_models"] = self._merge_attempted_models(
            first_pass.get("attempted_models"),
            second_pass.get("attempted_models"),
        )
        merged["warning"] = self._merge_notes(
            first_pass.get("warning"),
            second_pass.get("warning"),
            "vision_second_pass_failed",
        )
        merged["error"] = self._merge_notes(
            second_pass.get("error"),
            first_pass.get("error"),
        ).replace("; ", " | ")
        if not merged.get("error"):
            merged["error"] = "vision_model_chain_failed"
        return merged

    @staticmethod
    def _extract_message_content(data: dict[str, Any]) -> str:
        return extract_message_content(data)

    @staticmethod
    def _to_base64(image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode("ascii")

    @staticmethod
    def _clean_json_text(raw: str) -> str:
        return clean_json_text(raw)

    def _parse_json_payload(self, raw: str) -> dict[str, Any]:
        parsed = parse_json_payload(raw)
        if not parsed and str(raw or "").strip():
            logger.warning("Vision JSON parse failed. Returning empty payload.")
        return parsed

    @staticmethod
    def _normalize_str_list(value: Any) -> list[str]:
        return normalize_str_list(value)

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return normalize_payload(payload)

    def _error_payload(
        self,
        *,
        warning: str,
        error: str,
        source: str,
        attempted_models: list[str] | None = None,
    ) -> dict[str, Any]:
        return build_error_payload(
            warning=warning,
            error=error,
            source=source,
            attempted_models=attempted_models,
        )
