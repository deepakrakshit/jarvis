# ==============================================================================
# File: services/document/parsers/__init__.py
# Project: J.A.R.V.I.S. — Just A Rather Very Intelligent System
# ==============================================================================
#
# Description:
#    Document Parser Package Initializer
#
#    - Exports format-specific document parsers for the extraction pipeline.
#    - PDFParser: text, table, and metadata extraction from PDF files.
#    - DOCXParser: Word document parsing with structure preservation.
#    - OCRParser: image-to-text parsing via OCR engine integration.
#    - BaseParser: abstract interface defining the parser contract.
#    - Format detection and automatic parser selection.
#    - Consistent output structure across all parser implementations.
#    - Extensible design for adding new format parsers.
#
# Author: Deepak Rakshit
# Repository: https://github.com/deepakrakshit/jarvis
#
# Copyright (c) 2025 Deepak Rakshit. All rights reserved.
# See LICENSE file in the project root for license information.
# ==============================================================================

from services.document.parsers.base_parser import BaseParser, detect_parser
from services.document.parsers.pdf_parser import PdfParser
from services.document.parsers.docx_parser import DocxParser
from services.document.parsers.ocr_parser import OcrParser

__all__ = ["BaseParser", "PdfParser", "DocxParser", "OcrParser", "detect_parser"]
