# ==============================================================================
# File: services/document/parsers/pdf_parser.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    PDF Document Parser — Multi-Strategy Extraction
#
#    - Extracts text, tables, and metadata from PDF files.
#    - Multiple extraction strategies for different PDF types.
#    - Text-based PDF: direct text extraction with layout preservation.
#    - Image-based PDF: delegates to OCR pipeline for scanned pages.
#    - Table detection: identifies and extracts tabular data structures.
#    - Metadata extraction: title, author, creation date, page count.
#    - Page-level extraction for fine-grained content access.
#    - Handles encrypted and password-protected PDFs gracefully.
#    - Memory-efficient streaming for large multi-page documents.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from typing import Any

from services.document.models import PageContent, RawExtractionResult, TableData
from services.document.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

_MIN_TEXT_CHARS_PER_PAGE = 80


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


class PdfParser(BaseParser):
    """PDF parser producing multimodal extraction artifacts."""

    @staticmethod
    def _render_dpi() -> int:
        return _int_env("DOCUMENT_PDF_RENDER_DPI", 140, 96, 320)

    @staticmethod
    def _max_vision_images() -> int:
        return _int_env("DOCUMENT_PDF_MAX_VISION_IMAGES", 10, 1, 64)

    @staticmethod
    def _max_ocr_images() -> int:
        return _int_env("DOCUMENT_PDF_MAX_OCR_IMAGES", 16, 1, 96)

    @staticmethod
    def _max_table_pages() -> int:
        return _int_env("DOCUMENT_PDF_TABLE_MAX_PAGES", 8, 0, 128)

    def parse(self, file_path: str) -> RawExtractionResult:
        try:
            return self._parse_internal(file_path)
        except Exception as exc:
            logger.exception("PDF parsing failed for %s", file_path)
            return RawExtractionResult(
                text="",
                pages=[],
                tables=[],
                metadata={"file_path": file_path},
                source_type="pdf",
                file_path=file_path,
                error=f"PDF parsing failed: {exc}",
            )

    def _parse_internal(self, file_path: str) -> RawExtractionResult:
        try:
            import fitz  # PyMuPDF
        except ImportError as exc:
            spec = importlib.util.find_spec("fitz")
            if spec is None:
                error_text = (
                    "PyMuPDF (fitz) is not installed in the active interpreter. "
                    f"Interpreter: {sys.executable}. "
                    "Install with: python -m pip install PyMuPDF"
                )
            else:
                error_text = (
                    "PyMuPDF (fitz) appears installed but failed to import in the active interpreter. "
                    f"Interpreter: {sys.executable}. "
                    f"Original import error: {exc}"
                )

            return RawExtractionResult(
                text="",
                pages=[],
                tables=[],
                metadata={"file_path": file_path},
                source_type="pdf",
                file_path=file_path,
                error=error_text,
            )

        doc = fitz.open(file_path)
        metadata = self._extract_metadata(doc, file_path)
        pages: list[PageContent] = []
        all_text_parts: list[str] = []

        render_dpi = self._render_dpi()
        max_vision_images = self._max_vision_images()
        max_ocr_images = self._max_ocr_images()
        max_table_pages = self._max_table_pages()

        low_text_pages: list[int] = []
        vision_images: list[dict[str, Any]] = []
        ocr_images: list[dict[str, Any]] = []

        try:
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                page_number = page_idx + 1
                text = page.get_text("text").strip()
                has_images = bool(page.get_images(full=True))
                low_text = len(text) < _MIN_TEXT_CHARS_PER_PAGE

                if low_text:
                    low_text_pages.append(page_number)

                payload = None
                needs_vision_payload = (has_images or low_text) and len(vision_images) < max_vision_images
                needs_ocr_payload = low_text and len(ocr_images) < max_ocr_images
                if needs_vision_payload or needs_ocr_payload:
                    payload = self._render_page_payload(page, page_number, dpi=render_dpi)

                if payload and len(vision_images) < max_vision_images and (has_images or low_text):
                    vision_images.append(payload)

                if payload and low_text and len(ocr_images) < max_ocr_images:
                    ocr_images.append(payload)

                pages.append(
                    PageContent(
                        page_number=page_number,
                        text=text,
                        has_images=has_images,
                    )
                )
                if text:
                    all_text_parts.append(text)
        finally:
            doc.close()

        combined_text = "\n\n".join(all_text_parts)
        tables = self._extract_tables(file_path, max_pages=max_table_pages)

        total_pages = len(pages)
        scanned_ratio = len(low_text_pages) / max(1, total_pages)
        is_scanned = scanned_ratio >= 0.5 and total_pages > 0

        metadata.update(
            {
                "source_type": "pdf",
                "page_count": total_pages,
                "has_images": bool(vision_images),
                "is_scanned": is_scanned,
                "scanned_ratio": round(scanned_ratio, 3),
                "scanned_page_numbers": low_text_pages,
                "vision_images": vision_images,
                "ocr_images": ocr_images,
                "vision_image_count": len(vision_images),
                "ocr_image_count": len(ocr_images),
            }
        )

        return RawExtractionResult(
            text=combined_text,
            pages=pages,
            tables=tables,
            metadata=metadata,
            source_type="pdf",
            file_path=file_path,
        )

    @staticmethod
    def _render_page_payload(page: Any, page_number: int, *, dpi: int) -> dict[str, Any] | None:
        try:
            pix = page.get_pixmap(dpi=max(96, int(dpi)), alpha=False)
            image_bytes = pix.tobytes("png")
            return {
                "source": f"pdf_page_{page_number}",
                "page_number": page_number,
                "mime_type": "image/png",
                "bytes": image_bytes,
                "width": int(getattr(pix, "width", 0) or 0),
                "height": int(getattr(pix, "height", 0) or 0),
            }
        except Exception as exc:
            logger.debug("PDF page rendering failed for page %d: %s", page_number, exc)
            return None

    @staticmethod
    def _extract_metadata(doc: Any, file_path: str) -> dict[str, Any]:
        meta: dict[str, Any] = {"file_path": file_path, "page_count": len(doc)}
        try:
            pdf_meta = doc.metadata or {}
            for key in ("title", "author", "subject", "creator", "producer"):
                value = pdf_meta.get(key)
                if value:
                    meta[key] = str(value).strip()
        except Exception:
            pass
        return meta

    @staticmethod
    def _extract_tables(file_path: str, *, max_pages: int) -> list[TableData]:
        if max_pages <= 0:
            return []

        try:
            import pdfplumber
        except ImportError:
            logger.info("pdfplumber not installed - skipping table extraction")
            return []

        tables: list[TableData] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    if page_idx >= max_pages:
                        break
                    page_tables = page.extract_tables() or []
                    for raw_table in page_tables:
                        if not raw_table or len(raw_table) < 2:
                            continue

                        headers = [str(cell or "").strip() for cell in raw_table[0]]
                        rows = [
                            [str(cell or "").strip() for cell in row]
                            for row in raw_table[1:]
                            if any(str(cell or "").strip() for cell in row)
                        ]

                        if headers or rows:
                            tables.append(
                                TableData(
                                    page_number=page_idx + 1,
                                    headers=headers,
                                    rows=rows,
                                )
                            )
        except Exception as exc:
            logger.warning("pdfplumber table extraction failed: %s", exc)

        return tables
