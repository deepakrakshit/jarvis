"""Shared helpers for vision payload parsing and normalization."""

from __future__ import annotations

import json
import re
from typing import Any


def has_payload_signal(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False

    for key in ("visible_text", "layout", "summary"):
        if str(payload.get(key) or "").strip():
            return True

    for key in ("categories", "key_elements", "tables"):
        value = payload.get(key)
        if isinstance(value, list) and value:
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
    return "; ".join(notes)


def merge_attempted_models(*attempt_lists: Any) -> list[str]:
    models: list[str] = []
    seen: set[str] = set()
    for attempt_list in attempt_lists:
        if not isinstance(attempt_list, list):
            continue
        for item in attempt_list:
            model = str(item or "").strip()
            lowered = model.lower()
            if not model or lowered in seen:
                continue
            seen.add(lowered)
            models.append(model)
    return models


def extract_message_content(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if isinstance(candidates, list) and candidates:
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        content = first.get("content") if isinstance(first, dict) else None
        if isinstance(content, dict):
            parts = content.get("parts")
            if isinstance(parts, list):
                chunks: list[str] = []
                for item in parts:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        text = item.get("text", "").strip()
                        if text:
                            chunks.append(text)
                if chunks:
                    return "\n".join(chunks).strip()

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item.get("text", "").strip())
        return "\n".join(part for part in parts if part).strip()

    return ""


def clean_json_text(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""

    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]

    return text.strip()


def parse_json_payload(raw: str) -> dict[str, Any]:
    cleaned = clean_json_text(raw)
    if not cleaned:
        return {}

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return {}
    return {}


def normalize_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                out.append(text)
        return out
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    tables = payload.get("tables")
    normalized_tables: list[dict[str, Any]] = []
    if isinstance(tables, list):
        for item in tables:
            if isinstance(item, dict):
                normalized_tables.append(item)

    return {
        "visible_text": str(payload.get("visible_text") or "").strip(),
        "layout": str(payload.get("layout") or "").strip(),
        "categories": normalize_str_list(payload.get("categories")),
        "key_elements": normalize_str_list(payload.get("key_elements")),
        "tables": normalized_tables,
        "summary": str(payload.get("summary") or "").strip(),
    }


def build_error_payload(
    *,
    warning: str,
    error: str,
    source: str,
    attempted_models: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "visible_text": "",
        "layout": "",
        "categories": [],
        "key_elements": [],
        "tables": [],
        "summary": "",
        "warning": warning,
        "error": error,
        "source": source,
        "model": "",
        "attempted_models": attempted_models or [],
    }
    return payload
