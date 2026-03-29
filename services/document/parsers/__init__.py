"""Document parsers for PDF, DOCX, and image formats."""

from services.document.parsers.base_parser import BaseParser, detect_parser
from services.document.parsers.pdf_parser import PdfParser
from services.document.parsers.docx_parser import DocxParser
from services.document.parsers.ocr_parser import OcrParser

__all__ = ["BaseParser", "PdfParser", "DocxParser", "OcrParser", "detect_parser"]
