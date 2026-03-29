"""Abstract base class for all document parsers.

Each parser must accept a file path and produce a RawExtractionResult.
The factory function `detect_parser` selects the correct parser by extension.
"""

from __future__ import annotations

import abc
import logging
from pathlib import Path

from services.document.models import RawExtractionResult

logger = logging.getLogger(__name__)


class BaseParser(abc.ABC):
    """Interface contract for document parsers."""

    @abc.abstractmethod
    def parse(self, file_path: str) -> RawExtractionResult:
        """Parse a file and return raw extraction results.

        Must never raise — return RawExtractionResult with error field set on failure.
        """

    @staticmethod
    def _safe_text(value: object) -> str:
        """Safely convert any value to a stripped string."""
        return str(value or "").strip()


def detect_parser(file_path: str) -> BaseParser:
    """Select the appropriate parser based on file extension.

    Returns:
        An instance of the correct parser for the file type.

    Raises:
        ValueError: If the file type is not supported.
    """
    from services.document.parsers.pdf_parser import PdfParser
    from services.document.parsers.docx_parser import DocxParser
    from services.document.parsers.ocr_parser import OcrParser

    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        return PdfParser()
    if ext in {".docx", ".doc"}:
        return DocxParser()
    if ext in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}:
        return OcrParser()

    raise ValueError(f"Unsupported file extension: {ext}")
