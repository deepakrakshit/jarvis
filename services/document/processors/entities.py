# ==============================================================================
# File: services/document/processors/entities.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Named Entity Extractor & Normalizer
#
#    - Extracts named entities from document text with categorization.
#    - Categories: names, dates, prices, companies, plans, features.
#    - Deduplication: merges equivalent entity mentions.
#    - Normalization: standardizes date formats, currency representations.
#    - normalize_entities(): ensures consistent entity dict structure.
#    - LLM-assisted extraction for complex entity recognition.
#    - Pattern-based extraction for high-confidence entity types.
#    - Returns standardized dict with list values per category.
#    - Used by document_service, qa_engine, and display formatters.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import re
from typing import Any


_DEFAULT_KEYS = ("names", "dates", "prices", "companies", "plans", "features")


def empty_entities() -> dict[str, list[str]]:
    return {key: [] for key in _DEFAULT_KEYS}


def normalize_entities(value: Any) -> dict[str, list[str]]:
    base = empty_entities()
    if not isinstance(value, dict):
        return base

    for key in _DEFAULT_KEYS:
        raw = value.get(key)
        if isinstance(raw, list):
            cleaned = _dedupe([str(item or "").strip() for item in raw if str(item or "").strip()])
            base[key] = cleaned[:32]
        elif isinstance(raw, str) and raw.strip():
            base[key] = [raw.strip()]

    return base


def merge_entities(*parts: dict[str, list[str]]) -> dict[str, list[str]]:
    merged = empty_entities()
    for payload in parts:
        normalized = normalize_entities(payload)
        for key in _DEFAULT_KEYS:
            merged[key] = _dedupe([*merged[key], *normalized[key]])[:64]
    return merged


def extract_key_entities(text: str) -> dict[str, list[str]]:
    source = str(text or "")
    if not source.strip():
        return empty_entities()

    entities = empty_entities()

    entities["prices"] = _dedupe(_find_prices(source))[:32]
    entities["dates"] = _dedupe(_find_dates(source))[:32]
    entities["companies"] = _dedupe(_find_companies(source))[:32]
    entities["names"] = _dedupe(_find_names(source))[:32]
    entities["plans"] = _dedupe(_find_plans(source))[:32]
    entities["features"] = _dedupe(_find_features(source))[:48]

    return entities


def _find_prices(text: str) -> list[str]:
    pattern = re.compile(
        r"(?:[\$\u20B9\u20AC\u00A3]\s?\d[\d,]*(?:\.\d+)?(?:\s*/\s*(?:month|mo|year|yr))?)"
        r"|(?:\b\d[\d,]*(?:\.\d+)?\s?(?:usd|inr|eur|gbp|rs\.?|rupees?)\b)",
        flags=re.IGNORECASE,
    )
    return [match.group(0).strip() for match in pattern.finditer(text)]


def _find_dates(text: str) -> list[str]:
    patterns = (
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b",
        r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{2,4}\b",
    )

    found: list[str] = []
    for raw in patterns:
        regex = re.compile(raw, flags=re.IGNORECASE)
        found.extend(match.group(0).strip() for match in regex.finditer(text))
    return found


def _find_companies(text: str) -> list[str]:
    suffix_pattern = re.compile(
        r"\b([A-Z][A-Za-z0-9&.,\- ]{1,80}?(?:Inc\.?|Ltd\.?|LLC|Corp\.?|Corporation|Company|Co\.?|PLC))\b"
    )
    return [match.group(1).strip() for match in suffix_pattern.finditer(text)]


def _find_names(text: str) -> list[str]:
    titled = re.compile(r"\b(?:Mr|Ms|Mrs|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b")
    plain = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")

    names = [match.group(0).strip() for match in titled.finditer(text)]
    names.extend(match.group(0).strip() for match in plain.finditer(text))

    # Filter obvious false positives from section headings.
    blocked = {"Key Points", "Table Of", "Document Analysis", "System Prompt"}
    return [name for name in names if name not in blocked]


def _find_plans(text: str) -> list[str]:
    found: list[str] = []
    tier_pattern = re.compile(r"\b(free|basic|starter|pro|premium|enterprise|business|ultimate)\b", flags=re.IGNORECASE)
    for match in tier_pattern.finditer(text):
        found.append(match.group(1).strip().title())

    labeled_pattern = re.compile(r"\b([A-Z][A-Za-z0-9\- ]{1,40})\s+plan\b", flags=re.IGNORECASE)
    for match in labeled_pattern.finditer(text):
        found.append(match.group(1).strip())

    return found


def _find_features(text: str) -> list[str]:
    lines = [line.strip(" -\t") for line in str(text or "").splitlines()]
    candidates: list[str] = []

    feature_pattern = re.compile(r"\b(feature|features|includes?|supports?|capabilities?)\b", flags=re.IGNORECASE)
    token_pattern = re.compile(r"\b(API|OCR|SDK|Dashboard|Export|Integration|Automation|Search|Analytics|Reporting)\b")

    for line in lines:
        if not line:
            continue
        if feature_pattern.search(line):
            candidates.extend(_split_compound_values(line))
            continue

        for token in token_pattern.findall(line):
            candidates.append(token.strip())

    return [value for value in candidates if len(value) <= 64]


def _split_compound_values(text: str) -> list[str]:
    source = str(text or "")
    source = re.sub(r"\b(feature|features|includes?|supports?|capabilities?)\b\s*:?", "", source, flags=re.IGNORECASE)
    parts = re.split(r"[,;|/]", source)
    return [part.strip() for part in parts if part.strip()]


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output
