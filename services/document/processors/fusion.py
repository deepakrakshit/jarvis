# ==============================================================================
# File: services/document/processors/fusion.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Multi-Source Content Fusion Engine
#
#    - Merges text from multiple extraction sources into unified output.
#    - Source inputs: text parser, OCR engine, and vision analysis.
#    - Conflict resolution: prioritizes higher-confidence sources.
#    - Overlap deduplication: detects and merges redundant content.
#    - Source reliability scoring based on extraction method and quality.
#    - Preserves unique content from each source.
#    - Handles missing sources gracefully (e.g., no OCR available).
#    - Returns unified text with source provenance metadata.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

from typing import Any


class FusionProcessor:
    """Merge multimodal extraction outputs into a single structured payload."""

    def fuse(
        self,
        *,
        text_content: str,
        ocr_content: str,
        vision_data: list[dict[str, Any]] | dict[str, Any] | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        normalized_vision = self._normalize_vision(vision_data)
        fused_vision = self._aggregate_vision(normalized_vision)

        return {
            "text_content": str(text_content or "").strip(),
            "ocr_content": str(ocr_content or "").strip(),
            "vision_data": {
                "items": normalized_vision,
                **fused_vision,
            },
            "metadata": dict(metadata or {}),
        }

    def _normalize_vision(
        self,
        vision_data: list[dict[str, Any]] | dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if vision_data is None:
            return []

        if isinstance(vision_data, dict):
            items = [vision_data]
        elif isinstance(vision_data, list):
            items = [item for item in vision_data if isinstance(item, dict)]
        else:
            items = []

        normalized: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            normalized.append(
                {
                    "source": str(item.get("source") or f"image_{idx + 1}"),
                    "model": str(item.get("model") or ""),
                    "visible_text": str(item.get("visible_text") or "").strip(),
                    "layout": str(item.get("layout") or "").strip(),
                    "categories": self._normalize_str_list(item.get("categories")),
                    "key_elements": self._normalize_str_list(item.get("key_elements")),
                    "tables": self._normalize_tables(item.get("tables")),
                    "summary": str(item.get("summary") or "").strip(),
                    "warning": str(item.get("warning") or "").strip(),
                    "error": str(item.get("error") or "").strip(),
                }
            )

        return normalized

    def _aggregate_vision(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        visible_texts = [item.get("visible_text", "") for item in items if item.get("visible_text")]
        layouts = [item.get("layout", "") for item in items if item.get("layout")]
        summaries = [item.get("summary", "") for item in items if item.get("summary")]

        categories = self._dedupe(
            value
            for item in items
            for value in item.get("categories", [])
        )
        key_elements = self._dedupe(
            value
            for item in items
            for value in item.get("key_elements", [])
        )
        tables: list[dict[str, Any]] = []
        for item in items:
            for table in item.get("tables", []):
                if isinstance(table, dict):
                    tables.append(table)

        warnings = self._dedupe(
            item.get("warning", "")
            for item in items
            if item.get("warning")
        )
        errors = self._dedupe(
            item.get("error", "")
            for item in items
            if item.get("error")
        )

        return {
            "visible_text": "\n".join(visible_texts).strip(),
            "layout": "\n".join(layouts).strip(),
            "categories": categories,
            "key_elements": key_elements,
            "tables": tables,
            "summary": "\n".join(summaries).strip(),
            "warnings": warnings,
            "errors": errors,
        }

    @staticmethod
    def _normalize_str_list(value: Any) -> list[str]:
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

    @staticmethod
    def _normalize_tables(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]

    @staticmethod
    def _dedupe(values: Any) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in values:
            text = str(item or "").strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                out.append(text)
        return out
