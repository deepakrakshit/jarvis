from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

from services.document.parsers.pdf_parser import PdfParser


class _FakePage:
    def __init__(self) -> None:
        self.calls = 0

    def extract_tables(self) -> list:
        self.calls += 1
        return []


class _FakePdf:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def __enter__(self) -> "_FakePdf":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class PdfParserLimitsStressTest(unittest.TestCase):
    def test_table_extraction_respects_page_limit(self) -> None:
        pages = [_FakePage() for _ in range(10)]

        fake_module = types.SimpleNamespace(open=lambda _path: _FakePdf(pages))
        with patch.dict(sys.modules, {"pdfplumber": fake_module}):
            tables = PdfParser._extract_tables("dummy.pdf", max_pages=3)

        self.assertEqual(tables, [])
        self.assertEqual(sum(page.calls for page in pages), 3)

    def test_table_extraction_can_be_disabled(self) -> None:
        tables = PdfParser._extract_tables("dummy.pdf", max_pages=0)
        self.assertEqual(tables, [])


if __name__ == "__main__":
    unittest.main()
