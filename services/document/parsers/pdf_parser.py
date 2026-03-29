"""PDF parser for hybrid document intelligence pipeline.

Responsibilities:
- Extract text with PyMuPDF
- Detect scanned pages by low text density
- Extract page image payloads for downstream vision and OCR stages
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from typing import Any

from services.document.models import PageContent, RawExtractionResult, TableData
from services.document.parsers.base_parser import BaseParser

logger = logging.getLogger(__name__)

_MIN_TEXT_CHARS_PER_PAGE = 80
_RENDER_DPI = 140
_MAX_VISION_IMAGES = 10
_MAX_OCR_IMAGES = 16


class PdfParser(BaseParser):
    """PDF parser producing multimodal extraction artifacts."""

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
                if has_images or low_text:
                    payload = self._render_page_payload(page, page_number)

                if payload and len(vision_images) < _MAX_VISION_IMAGES and (has_images or low_text):
                    vision_images.append(payload)

                if payload and low_text and len(ocr_images) < _MAX_OCR_IMAGES:
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
        tables = self._extract_tables(file_path)

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
    def _render_page_payload(page: Any, page_number: int) -> dict[str, Any] | None:
        try:
            pix = page.get_pixmap(dpi=_RENDER_DPI, alpha=False)
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
    def _extract_tables(file_path: str) -> list[TableData]:
        try:
            import pdfplumber
        except ImportError:
            logger.info("pdfplumber not installed - skipping table extraction")
            return []

        tables: list[TableData] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_idx, page in enumerate(pdf.pages):
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
