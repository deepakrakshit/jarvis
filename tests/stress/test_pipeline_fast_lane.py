from __future__ import annotations

import unittest

from core.settings import AppConfig
from services.document.models import PipelineProgress, RawExtractionResult
from services.document.pipeline import DocumentPipeline


class _FastLlmStub:
    def complete_fast(self, **_: object) -> str:
        return ""

    def extract_json_fast(self, **_: object) -> dict:
        return {
            "summary": "ok",
            "insights": [],
            "key_points": [],
            "metrics": [],
            "risks": [],
            "entities": {},
        }

    def extract_json_deep(self, **_: object) -> dict:
        return {
            "summary": "ok",
            "insights": [],
            "key_points": [],
            "metrics": [],
            "risks": [],
            "entities": {},
        }


class PipelineFastLaneStressTest(unittest.TestCase):
    def test_text_rich_flow_runs_text_primary_and_vision_support(self) -> None:
        config = AppConfig.from_env(".env")
        pipeline = DocumentPipeline(_FastLlmStub(), config)
        pipeline._ultra_fast_enabled = True
        pipeline._ultra_fast_min_chars = 180
        pipeline._text_rich_min_chars = 900

        extraction = RawExtractionResult(
            text="\n".join(["Enterprise plan includes API, analytics, and reporting."] * 60),
            pages=[],
            tables=[],
            metadata={
                "vision_images": [
                    {
                        "source": "page_1",
                        "mime_type": "image/png",
                        "bytes": b"fake-image-bytes",
                    }
                ],
                "ocr_images": [
                    {
                        "source": "page_1",
                        "mime_type": "image/png",
                        "bytes": b"fake-image-bytes",
                    }
                ],
                "is_scanned": False,
                "source_type": "pdf",
            },
            source_type="pdf",
            file_path="dummy.pdf",
            error="",
        )

        flags = {"vision_called": False, "ocr_called": False}

        def _vision_ok(*_: object, **__: object) -> list:
            flags["vision_called"] = True
            return [
                {
                    "visible_text": "Pricing table",
                    "layout": "table",
                    "categories": ["pricing"],
                    "key_elements": ["enterprise"],
                    "tables": [],
                    "summary": "Vision summary",
                    "warning": "",
                    "error": "",
                }
            ]

        def _ocr_fail(*_: object, **__: object) -> dict:
            flags["ocr_called"] = True
            raise AssertionError("OCR should be skipped for non-scanned text-rich fast lane")

        pipeline._parse_document = lambda _path: extraction
        pipeline._vision.analyze_images = _vision_ok
        pipeline._ocr.extract_images = _ocr_fail

        result = pipeline._process_document(
            "dummy.pdf",
            PipelineProgress(),
            user_query="summarize this document quickly",
        )

        self.assertTrue(flags["vision_called"])
        self.assertFalse(flags["ocr_called"])
        self.assertFalse(result.metadata.get("vision_skipped_fast_lane"))
        self.assertTrue(result.metadata.get("text_primary_applied"))
        self.assertTrue(result.summary)


if __name__ == "__main__":
    unittest.main()
