# ==============================================================================
# File: services/document/pipeline_utils.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Pipeline Text Processing Utilities
#
#    - Shared text normalization utilities for the document pipeline.
#    - Whitespace normalization and sentence boundary detection.
#    - Content truncation for LLM context window management.
#    - Text quality scoring for content reliability assessment.
#    - Chunk boundary management for retrieval indexing.
#    - Encoding normalization for cross-platform text handling.
#    - Format-specific text cleaning (PDF artifact removal, etc.).
#    - Used across all pipeline stages for consistent text processing.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

from typing import Any


def coerce_image_payloads(value: Any, *, max_items: int = 16) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    payloads: list[dict[str, Any]] = []
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            continue

        image_bytes = item.get("bytes")
        if not isinstance(image_bytes, (bytes, bytearray)):
            continue

        payloads.append(
            {
                "source": str(item.get("source") or f"image_{idx + 1}"),
                "mime_type": str(item.get("mime_type") or "image/png"),
                "bytes": bytes(image_bytes),
            }
        )

        if len(payloads) >= max_items:
            break

    return payloads


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(metadata)
    sanitized.pop("vision_images", None)
    sanitized.pop("ocr_images", None)
    return sanitized


def vision_results_have_signal(vision_results: list[dict[str, Any]]) -> bool:
    for item in vision_results:
        if not isinstance(item, dict):
            continue
        if str(item.get("visible_text") or "").strip():
            return True
        if str(item.get("layout") or "").strip():
            return True
        if str(item.get("summary") or "").strip():
            return True
        if item.get("categories"):
            return True
        if item.get("key_elements"):
            return True
        if item.get("tables"):
            return True
    return False


def merge_notes(*parts: Any) -> str:
    notes: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        notes.append(text)
    return " | ".join(notes)


def merge_ocr_payloads(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary or {})
    if not isinstance(secondary, dict):
        return merged

    primary_text = str(merged.get("text") or "").strip()
    secondary_text = str(secondary.get("text") or "").strip()
    if not primary_text and secondary_text:
        merged["text"] = secondary_text
        merged["confidence"] = float(secondary.get("confidence") or 0.0)
    elif primary_text:
        merged["confidence"] = float(merged.get("confidence") or 0.0)

    merged["warning"] = merge_notes(merged.get("warning"), secondary.get("warning"))
    merged["error"] = merge_notes(merged.get("error"), secondary.get("error"))

    existing_per_image = merged.get("per_image") if isinstance(merged.get("per_image"), list) else []
    secondary_per_image = secondary.get("per_image") if isinstance(secondary.get("per_image"), list) else []
    merged["per_image"] = [*existing_per_image, *secondary_per_image]
    return merged


def has_vision_signal(vision_bundle: dict[str, Any]) -> bool:
    if str(vision_bundle.get("visible_text") or "").strip():
        return True
    if str(vision_bundle.get("layout") or "").strip():
        return True
    if str(vision_bundle.get("summary") or "").strip():
        return True
    if vision_bundle.get("categories"):
        return True
    if vision_bundle.get("key_elements"):
        return True
    if vision_bundle.get("tables"):
        return True

    items = vision_bundle.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("visible_text") or "").strip():
                return True
            if str(item.get("layout") or "").strip():
                return True
            if str(item.get("summary") or "").strip():
                return True
            if item.get("categories"):
                return True
            if item.get("key_elements"):
                return True
            if item.get("tables"):
                return True

    return False


def limit_chars(value: str, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def compact_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            compact[key] = value
        elif isinstance(value, list):
            compact[key] = value[:20]
        elif isinstance(value, dict):
            compact[key] = {
                sub_key: sub_value
                for sub_key, sub_value in value.items()
                if isinstance(sub_value, (str, int, float, bool))
            }
    return compact


def coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in ("text", "name", "value", "entity", "label", "title"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = [coerce_text(item) for item in value]
        non_empty = [part for part in parts if part]
        return ", ".join(non_empty[:4]).strip()
    return str(value).strip()


def coerce_string_list(value: Any, *, max_items: int = 64) -> list[str]:
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = [value]

    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = coerce_text(candidate)
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        output.append(normalized)
        if len(output) >= max_items:
            break

    return output


def coerce_metrics(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []

    metrics: list[dict[str, Any]] = []
    for item in value[:64]:
        if isinstance(item, dict):
            name = coerce_text(item.get("name"))
            metric_value = coerce_text(item.get("value"))
            context = coerce_text(item.get("context"))

            metric: dict[str, Any] = {}
            if name:
                metric["name"] = name
            if metric_value:
                metric["value"] = metric_value
            if context:
                metric["context"] = context
            if metric:
                metrics.append(metric)
            continue

        fallback_name = coerce_text(item)
        if fallback_name:
            metrics.append({"name": fallback_name})

    return metrics
