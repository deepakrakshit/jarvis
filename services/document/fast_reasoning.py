"""Lightweight deterministic helpers for ultra-fast document reasoning."""

from __future__ import annotations

import re

from services.document.pipeline_utils import limit_chars


def query_needs_visual_reasoning(query: str) -> bool:
    lowered = str(query or "").strip().lower()
    if not lowered:
        return False

    visual_tokens = (
        "image",
        "images",
        "layout",
        "diagram",
        "figure",
        "chart",
        "graph",
        "screenshot",
        "stamp",
        "signature",
        "visual",
        "table",
        "tables",
    )
    return any(token in lowered for token in visual_tokens)


def compact_sentences(text: str, *, max_sentences: int, max_chars: int) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""

    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", normalized) if item.strip()]
    selected = sentences[: max(1, int(max_sentences))] if sentences else [normalized]
    summary = " ".join(selected).strip()
    return limit_chars(summary, max_chars)


def extract_key_points_fast(text: str, *, max_items: int) -> list[str]:
    lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    output: list[str] = []
    seen: set[str] = set()

    for raw in lines:
        candidate = raw.strip(" -*\t")
        if len(candidate) < 28:
            continue
        lowered = candidate.lower()
        if lowered.startswith(("page ", "table of contents", "copyright")):
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        output.append(candidate)
        if len(output) >= max_items:
            return output

    sentences = [
        item.strip()
        for item in re.split(r"(?<=[.!?])\s+", " ".join(str(text or "").split()))
        if item.strip()
    ]
    for sentence in sentences:
        if len(sentence) < 28:
            continue
        lowered = sentence.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        output.append(sentence)
        if len(output) >= max_items:
            break

    return output
