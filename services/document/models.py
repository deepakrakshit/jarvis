# ==============================================================================
# File: services/document/models.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Document Intelligence Data Models
#
#    - DocumentIntelligence: structured analysis output with to_dict() serialization.
#    - Fields: summary, insights, tables, key_points, entities, risks, metadata.
#    - PipelineProgress: stage tracking with timing and status information.
#    - Table model: headers list + rows list-of-lists for structured tables.
#    - Entity categories: names, dates, prices, companies, plans, features.
#    - Metadata: processing stats, model versions, error tracking.
#    - Immutable design for safe passage through caching and serialization.
#    - JSON-serializable for SQLite cache storage and API responses.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Raw Extraction ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PageContent:
    """Content extracted from a single page of a document."""

    page_number: int
    text: str
    has_images: bool = False


@dataclass(frozen=True)
class TableData:
    """A single table extracted from a document."""

    page_number: int
    headers: list[str]
    rows: list[list[str]]
    caption: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "headers": self.headers,
            "rows": self.rows,
            "caption": self.caption,
        }


@dataclass(frozen=True)
class RawExtractionResult:
    """Output of the parsing stage — raw content before any cleaning."""

    text: str
    pages: list[PageContent]
    tables: list[TableData]
    metadata: dict[str, Any]
    source_type: str  # "pdf", "docx", "image", "scanned_pdf"
    file_path: str = ""
    error: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.text.strip() and not self.tables

    @property
    def page_count(self) -> int:
        return len(self.pages)


# ── Cleaning ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CleanedContent:
    """Text after LLM-based noise removal and normalization."""

    original_text: str
    cleaned_text: str
    cleaning_notes: str = ""


# ── Structure ───────────────────────────────────────────────────────────────

@dataclass
class Section:
    """A logical section of the document with heading hierarchy."""

    heading: str
    level: int  # 1 = top-level heading, 2 = subheading, etc.
    content: str
    subsections: list[Section] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "heading": self.heading,
            "level": self.level,
            "content": self.content,
            "subsections": [sub.to_dict() for sub in self.subsections],
        }


@dataclass(frozen=True)
class DocumentStructure:
    """Reconstructed logical structure of the entire document."""

    title: str
    sections: list[Section]
    tables: list[TableData]
    metadata: dict[str, Any]


# ── Chunking ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Chunk:
    """A semantically coherent text segment ready for per-chunk processing."""

    index: int
    text: str
    section_heading: str
    token_estimate: int


# ── Final Intelligence ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class DocumentIntelligence:
    """Final structured intelligence output from the pipeline."""

    summary: str
    insights: list[str]
    tables: list[dict[str, Any]]
    key_points: list[str]
    metrics: list[dict[str, Any]]
    risks: list[str]
    entities: dict[str, list[str]]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "insights": self.insights,
            "tables": self.tables,
            "key_points": self.key_points,
            "metrics": self.metrics,
            "risks": self.risks,
            "entities": self.entities,
            "metadata": self.metadata,
        }


# ── Pipeline Progress ──────────────────────────────────────────────────────

@dataclass
class PipelineProgress:
    """Mutable progress tracker for the pipeline stages."""

    stage: str = "idle"
    stage_index: int = 0
    total_stages: int = 7
    detail: str = ""
    error: str = ""

    STAGES = (
        "parsing",
        "cleaning",
        "structuring",
        "chunking",
        "processing_chunks",
        "merging",
        "intelligence",
    )

    def advance(self, stage: str, detail: str = "") -> None:
        self.stage = stage
        self.detail = detail
        try:
            self.stage_index = self.STAGES.index(stage) + 1
        except ValueError:
            self.stage_index += 1

    @property
    def percent(self) -> float:
        if self.total_stages <= 0:
            return 0.0
        return min(100.0, (self.stage_index / self.total_stages) * 100.0)
